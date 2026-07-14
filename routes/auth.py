import secrets
import logging
import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from starlette.responses import RedirectResponse
from . import limiter
import config
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

GUILD_ID = "1491471841716605062"

router = APIRouter()


@router.get("/login")
@limiter.limit("5/minute")
async def login(request: Request):
    state = secrets.token_urlsafe(16)
    await request.app.db["oauth_pending_states"].insert_one({
        "state": state,
        "createdAt": datetime.now(timezone.utc)
    })
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.FRONTEND_DOMAIN,
        "response_type": "code",
        "scope": "identify guilds email",
        "state": state,
    }
    discord_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return {"redirect_url": discord_url}


@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    state_doc = await request.app.db["oauth_pending_states"].find_one_and_delete({"state": state})
    if not state_doc:
        logger.warning("Invalid or expired state during OAuth callback")
        return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?error=session_expired", status_code=302)

    async with httpx.AsyncClient() as client:
        token_res = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.FRONTEND_DOMAIN,
        })

        if token_res.status_code != 200:
            try:
                error_detail = token_res.json()
            except Exception:
                error_detail = token_res.text
            logger.error(f"Discord token exchange failed: {error_detail}")
            return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?error=auth_failed", status_code=302)

        token_data = token_res.json()
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        user_res = await client.get("https://discord.com/api/users/@me", headers=headers)
        if user_res.status_code != 200:
            try:
                error_detail = user_res.json()
            except Exception:
                error_detail = user_res.text
            logger.error(f"Failed to fetch Discord user info: {error_detail}")
            return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?error=auth_failed", status_code=302)

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

    from urllib.parse import quote
    response = RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/#token={quote(encoded_jwt, safe='')}", status_code=302)
    response.set_cookie(
        key="session_token",
        value=encoded_jwt,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    return response


@router.get("/verify")
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


class WebTokenRequest(BaseModel):
    token: str


@router.post("/webtoken")
async def exchange_web_token(request: Request, body: WebTokenRequest):
    """
    Exchange a bot-generated web token for a JWT.
    The bot creates webToken when a user joins a voice channel.
    Only valid while the user is still in the VC (bot removes token on leave).
    """
    user_data = await request.app.db["users"].find_one(
        {"webToken": body.token},
        {"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1},
    )
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid or expired web token")

    user_id = user_data["_id"]

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
    avatar_hash = user_data.get("pfp", "")
    avatar = ""
    if avatar_hash:
        if avatar_hash.startswith("https://") or avatar_hash.startswith("data:"):
            avatar = ""
        else:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_hash_clean = avatar_hash.split("/")[-1].split(".")[0] if "/" in avatar_hash else avatar_hash
            avatar = avatar_hash_clean

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

    from fastapi.responses import JSONResponse
    response = JSONResponse(content={"ok": 1, "token": encoded_jwt})
    response.set_cookie(
        key="session_token",
        value=encoded_jwt,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=12 * 60 * 60,
        path="/",
    )
    return response
