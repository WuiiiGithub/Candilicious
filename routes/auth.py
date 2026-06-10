from fastapi import (
    APIRouter,
    HTTPException,
    Depends
)
from starlette.responses import RedirectResponse
import httpx
import os

router = APIRouter()

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

@router.get("/login")
def login():
    discord_url = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify"
    return RedirectResponse(url=discord_url)

@router.get("/callback")
async def callback(code: str):
    async with httpx.AsyncClient() as client:
        response = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI
        })
        token_data = response.json()
        
    return {"access_token": token_data.get("access_token")}