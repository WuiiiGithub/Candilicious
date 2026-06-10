import secrets
import httpx
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse
import config

router = APIRouter(prefix="/auth")

@router.get("/login")
async def login():
    state = secrets.token_urlsafe(16)
    
    scope_list = "identify email guilds"
    discord_url = (
        f"https://discord.com/api/oauth2/authorize?client_id={config.DISCORD_CLIENT_ID}"
        f"&redirect_uri={config.REDIRECT_URI}&response_type=code&scope={scope_list}&state={state}"
    )
    return RedirectResponse(url=discord_url)

@router.get("/callback")
async def callback(code: str, state: str):
    async with httpx.AsyncClient() as client:
        response = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.REDIRECT_URI
        })
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid token exchange")
        
        token_data = response.json()

    async with httpx.AsyncClient() as client:
        user_res = await client.get("https://discord.com/api/users/@me", 
            headers={"Authorization": f"Bearer {token_data['access_token']}"})
        
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not fetch user info")
        
        user_info = user_res.json()

    payload = {
        "sub": user_info["id"],
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    encoded_jwt = jwt.encode(payload, config.SECRET_KEY, algorithm="HS256")

    return RedirectResponse(url=f"https://candilicious.web.app/auth?token={encoded_jwt}")