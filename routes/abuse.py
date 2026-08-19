from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from . import verify_token
from library import abuse
import config

router = APIRouter()


def _require_owner(payload: dict):
    if payload.get("sub") != str(config.OWNER_ID):
        raise HTTPException(status_code=403, detail="Owner only")


class BanRequest(BaseModel):
    ip: str
    reason: str = "manual"


@router.get("/abuse/stats")
async def abuse_stats(request: Request, payload: dict = Depends(verify_token)):
    _require_owner(payload)
    return abuse.get_stats()


@router.get("/abuse/banned")
async def list_banned(request: Request, payload: dict = Depends(verify_token)):
    _require_owner(payload)
    return {"banned": abuse.get_banned_ips()}


@router.post("/abuse/ban")
async def ban_ip(body: BanRequest, request: Request, payload: dict = Depends(verify_token)):
    _require_owner(payload)
    abuse.ban_ip_permanent(body.ip, body.reason)
    return {"ok": 1, "banned": body.ip}


@router.post("/abuse/unban")
async def unban_ip(body: BanRequest, request: Request, payload: dict = Depends(verify_token)):
    _require_owner(payload)
    abuse.unban_ip(body.ip)
    return {"ok": 1, "unbanned": body.ip}
