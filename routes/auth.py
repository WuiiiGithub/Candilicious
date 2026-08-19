import os
import secrets
import logging
import hashlib
import base64
import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from starlette.responses import RedirectResponse
from . import limiter, rate_limit_ip, rate_limit_user, _client_ip, revoke_token, _is_revoked
from library.avatars import extract_avatar_hash
import config
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

GUILD_ID = str(config.availableIn["guilds"][0])

router = APIRouter()


async def record_ip(db, user_id: str, ip: str):
    """Record a successful login IP on the user document as a count map.

    Stores `ip_addresses: {ip: count}`. The IP is baked into the pipeline as a
    literal constant so each counter is updated atomically and concurrent
    logins from the same address never lose a count.
    """
    if not ip:
        return
    await db["users"].update_one(
        {"_id": user_id},
        [
            {"$set": {
                "ip_addresses": {
                    "$setField": {
                        "field": ip,
                        "input": {"$ifNull": ["$ip_addresses", {}]},
                        "value": {"$add": [
                            {"$ifNull": [
                                {"$getField": {
                                    "field": ip,
                                    "input": {"$ifNull": ["$ip_addresses", {}]},
                                }},
                                0
                            ]},
                            1
                        ]},
                    }
                }
            }}
        ],
        upsert=True,
    )


def _pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256 code challenge derived from the verifier."""
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@router.get("/login")
@limiter.limit("5/minute", key_func=rate_limit_ip)
async def login(request: Request, redirect_uri: str = None):
    """Start Discord OAuth. `redirect_uri` (the frontend origin) is validated
    against the allowed frontend domains and carried through the OAuth state so
    the callback bounces the user back to whichever site started the login.

    PKCE is used so the authorization code alone is worthless: the S256
    challenge goes to Discord and the verifier stays server-side, bound to the
    (single-use) state document."""
    target = _resolve_redirect_uri(redirect_uri)
    state = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(64)
    await request.app.db["oauth_pending_states"].insert_one({
        "state": state,
        "redirect_uri": target,
        "code_verifier": code_verifier,
        "createdAt": datetime.now(timezone.utc)
    })
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": target,
        "response_type": "code",
        "scope": "identify guilds email",
        "state": state,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    discord_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return {"redirect_url": discord_url}


def _resolve_redirect_uri(uri: str | None) -> str:
    """Normalise a requested frontend origin and reject anything not allowlisted."""
    allowed = config.allowed_frontend_domains()
    if uri:
        uri = uri.strip().strip("/")
        if uri in allowed:
            return uri
    return config.FRONTEND_DOMAIN


AUTH_CODE_TTL_SECONDS = 60
SESSION_LIFETIME_HOURS = 24


@router.get("/callback")
@limiter.limit("10/minute", key_func=rate_limit_ip)
async def callback(request: Request, code: str, state: str):
    state_doc = await request.app.db["oauth_pending_states"].find_one_and_delete({"state": state})
    if not state_doc:
        logger.warning("Invalid or expired state during OAuth callback")
        return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?error=session_expired", status_code=302)

    target = state_doc.get("redirect_uri") or config.FRONTEND_DOMAIN

    async with httpx.AsyncClient() as client:
        token_res = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": target,
            "code_verifier": state_doc.get("code_verifier") or "",
        })

        if token_res.status_code != 200:
            try:
                error_detail = token_res.json()
            except Exception:
                error_detail = token_res.text
            logger.error(f"Discord token exchange failed: {error_detail}")
            return RedirectResponse(url=f"{target}/?error=auth_failed", status_code=302)

        token_data = token_res.json()
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        user_res = await client.get("https://discord.com/api/users/@me", headers=headers)
        if user_res.status_code != 200:
            try:
                error_detail = user_res.json()
            except Exception:
                error_detail = user_res.text
            logger.error(f"Failed to fetch Discord user info: {error_detail}")
            return RedirectResponse(url=f"{target}/?error=auth_failed", status_code=302)

        user_info = user_res.json()

        guilds_res = await client.get("https://discord.com/api/users/@me/guilds", headers=headers)
        in_guild = False
        if guilds_res.status_code == 200:
            guilds = guilds_res.json()
            in_guild = any(g["id"] == GUILD_ID for g in guilds)

    user_id = user_info["id"]
    avatar_hash = user_info.get("avatar")
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}"
    else:
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/0.png"

    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {
            "name": user_info.get("username"),
            "display_name": user_info.get("global_name") or user_info.get("username"),
            "pfp": avatar_url,
            "email": user_info.get("email"),
            "last_login": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    await record_ip(request.app.db, user_id, _client_ip(request))

    payload = {
        "sub": user_id,
        "username": user_info.get("username"),
        "avatar": user_info.get("avatar"),
        "in_guild": in_guild,
        "is_owner": user_id == str(config.OWNER_ID),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=SESSION_LIFETIME_HOURS),
    }
    encoded_jwt = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

    # Never put the JWT in a URL. The frontend only ever sees a random,
    # single-use code that it swaps for the token via POST /exchange. The
    # explicit expires_at (not just the Mongo TTL index) enforces the strict
    # 60s window even though the TTL sweeper can lag a full cycle.
    now = datetime.now(timezone.utc)
    auth_code = secrets.token_urlsafe(32)
    await request.app.db["auth_codes"].insert_one({
        "code": auth_code,
        "token": encoded_jwt,
        "createdAt": now,
        "expires_at": now + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
    })

    return RedirectResponse(url=f"{target}/#auth={auth_code}", status_code=302)


class AuthExchangeRequest(BaseModel):
    code: str


@router.post("/exchange")
@limiter.limit("10/minute", key_func=rate_limit_ip)
@limiter.limit("30/hour", key_func=rate_limit_user)
async def exchange_auth_code(request: Request, body: AuthExchangeRequest):
    """Swap the single-use OAuth callback code for the session JWT.

    The code is burned atomically on first use (find_one_and_delete) and is
    additionally hard-rejected past its explicit expires_at, so even if it
    leaks via history, logs or analytics it is worthless after one redemption
    or the strict 60-second window."""
    doc = await request.app.db["auth_codes"].find_one_and_delete({
        "code": body.code,
        "expires_at": {"$gte": datetime.now(timezone.utc)},
    })
    if not doc or not doc.get("token"):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    return {"ok": 1, "token": doc["token"]}


@router.get("/verify")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def verify(request: Request):
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return {"valid": False}
    token = auth[7:].strip()
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return {"valid": False}
    if _is_revoked(token):
        return {"valid": False}
    return {"valid": True, "payload": payload}


@router.post("/logout")
async def logout(request: Request):
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if token:
        try:
            payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
            revoke_token(token, float(payload.get("exp", 0)))
        except jwt.PyJWTError:
            pass
    return {"ok": 1}


class WebTokenRequest(BaseModel):
    token: str


@router.post("/webtoken")
@limiter.limit("10/minute", key_func=rate_limit_ip)
@limiter.limit("30/hour", key_func=rate_limit_user)
async def exchange_web_token(request: Request, body: WebTokenRequest):
    """
    Exchange a bot-generated web token for a JWT.
    Single-use: the token is burned atomically on exchange.
    The bot sets webTokenExpiresAt when generating the token.
    """
    user_data = await request.app.db["users"].find_one_and_update(
        {"webToken": body.token},
        {"$unset": {"webToken": "", "webTokenExpiresAt": ""}},
        projection={"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1, "webTokenExpiresAt": 1},
    )
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired web token")

    expires_at = user_data.get("webTokenExpiresAt")
    try:
        if not expires_at or datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Invalid or expired web token")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired web token")

    user_id = user_data["_id"]

    await record_ip(request.app.db, user_id, _client_ip(request))

    bot = request.app.state.bot
    in_guild = False
    if bot:
        try:
            guild = bot.get_guild(int(GUILD_ID))
            if guild:
                member = guild.get_member(int(user_id))
                if member:
                    in_guild = True
        except (ValueError, TypeError):
            pass

    username = user_data.get("name", "Unknown")
    avatar = extract_avatar_hash(user_data.get("pfp", ""))

    payload = {
        "sub": user_id,
        "username": username,
        "avatar": avatar,
        "in_guild": in_guild,
        "is_owner": user_id == str(config.OWNER_ID),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    encoded_jwt = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

    return {"ok": 1, "token": encoded_jwt}
