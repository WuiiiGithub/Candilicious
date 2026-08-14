import os
import secrets
import logging
import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from starlette.responses import RedirectResponse
from . import limiter, rate_limit_ip, rate_limit_user, _client_ip
from library.avatars import extract_avatar_hash
import config
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

GUILD_ID = str(config.availableIn["guilds"][0])

router = APIRouter()


def _cookie_flags(request: Request) -> dict:
    """Cookie flags tuned to the connection.

    Production (HTTPS behind a proxy): SameSite=None + Secure so the cookie
    travels cross-site between frontend and API on different origins.
    Local dev (plain HTTP on a LAN IP): SameSite=Lax without Secure, which
    is the only combination browsers accept over HTTP.
    """
    is_secure = config.IS_PROD
    return {
        "httponly": True,
        "secure": is_secure,
        "samesite": "none" if is_secure else "lax",
    }


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


@router.get("/login")
@limiter.limit("5/minute", key_func=rate_limit_ip)
async def login(request: Request, redirect_uri: str = None):
    """Start Discord OAuth. `redirect_uri` (the frontend origin) is validated
    against the allowed frontend domains and carried through the OAuth state so
    the callback bounces the user back to whichever site started the login."""
    target = _resolve_redirect_uri(redirect_uri)
    state = secrets.token_urlsafe(16)
    await request.app.db["oauth_pending_states"].insert_one({
        "state": state,
        "redirect_uri": target,
        "createdAt": datetime.now(timezone.utc)
    })
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": target,
        "response_type": "code",
        "scope": "identify guilds email",
        "state": state,
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
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    encoded_jwt = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

    response = RedirectResponse(url=f"{target}/#login", status_code=302)
    response.set_cookie(
        key="session_token",
        value=encoded_jwt,
        **_cookie_flags(request),
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return response


@router.get("/verify")
@limiter.limit("120/minute", key_func=rate_limit_ip)
async def verify(token: str = None, request: Request = None):
    if not token and request:
        token = request.cookies.get("session_token")
    if not token:
        return {"valid": False}
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
        return {"valid": True, "payload": payload}
    except jwt.PyJWTError:
        return {"valid": False}


@router.post("/logout")
async def logout(request: Request = None):
    response = JSONResponse(content={"ok": 1})
    response.delete_cookie(key="session_token", path="/", **_cookie_flags(request))
    return response


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

    response = JSONResponse(content={"ok": 1, "token": encoded_jwt})
    response.set_cookie(
        key="session_token",
        value=encoded_jwt,
        **_cookie_flags(request),
        max_age=12 * 60 * 60,
        path="/",
    )
    return response
