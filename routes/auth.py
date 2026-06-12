import secrets
import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse
from . import limiter
import config
from urllib.parse import urlencode

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
        "state": state
    }
    discord_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return {"redirect_url": discord_url}

@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    state_doc = await request.app.db["oauth_pending_states"].find_one_and_delete({"state": state})
    if not state_doc:
        raise HTTPException(status_code=403, detail="Invalid or expired state")

    async with httpx.AsyncClient() as client:
        token_res = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.FRONTEND_DOMAIN
        })

        if token_res.status_code != 200:
            try:
                error_detail = token_res.json()
            except Exception:
                error_detail = token_res.text
            print(f"Token exchange failed: {error_detail}")
            raise HTTPException(status_code=400, detail=f"Invalid token exchange: {error_detail}")

        token_data = token_res.json()

        # User Info Fetch
        user_res = await client.get("https://discord.com/api/users/@me", 
            headers={"Authorization": f"Bearer {token_data['access_token']}"})

        if user_res.status_code != 200:
            try:
                error_detail = user_res.json()
            except Exception:
                error_detail = user_res.text
            print(f"Could not fetch user info: {error_detail}")
            raise HTTPException(status_code=400, detail=f"Could not fetch user info: {error_detail}")

        user_info = user_res.json()
        print(f"DEBUG USER INFO: {user_info}")

    payload = {
        "sub": user_info["id"],
        "username": user_info.get("username"),
        "avatar": user_info.get("avatar"),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    encoded_jwt = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

    return RedirectResponse(url=f"{config.FRONTEND_DOMAIN}/?token={encoded_jwt}")