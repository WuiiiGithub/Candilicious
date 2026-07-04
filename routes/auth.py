import secrets
import logging
import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request
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

    return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?token={encoded_jwt}", status_code=302)


@router.get("/verify")
async def verify(token: str):
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
        return {"valid": True}
    except jwt.PyJWTError:
        return {"valid": False}
