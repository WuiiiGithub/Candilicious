from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from . import verify_token

router = APIRouter()


class ReportBody(BaseModel):
    subject: str = Field(..., min_length=20, max_length=100)
    description: str = Field(..., min_length=1, max_length=250)
    route: str = ""
    device: str = ""
    state_info: Optional[Dict[str, Any]] = None


@router.post("/")
async def create_report(
    request: Request,
    body: ReportBody,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    user_agent = request.headers.get("user-agent", "")

    guild_ids = []
    bot = request.app.state.bot
    if bot:
        for guild in bot.guilds:
            member = guild.get_member(int(user_id))
            if member:
                guild_ids.append(str(guild.id))

    report = {
        "user_id": user_id,
        "guild_ids": guild_ids,
        "ip": ip,
        "user_agent": user_agent,
        "device": body.device,
        "route": body.route,
        "state_info": body.state_info or {},
        "subject": body.subject,
        "description": body.description,
        "created_at": datetime.now(timezone.utc),
    }

    await request.app.db["reports"].insert_one(report)

    return {"ok": 1, "detail": "Report submitted"}
