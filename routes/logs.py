from datetime import datetime, timezone
from typing import List, Any
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from . import verify_token

router = APIRouter()

class BoardLogRequest(BaseModel):
    board_id: str
    logs: List[Any]

@router.post("/boards")
async def log_board_activity(
    data: BoardLogRequest,
    request: Request,
    payload: dict = Depends(verify_token)
):
    user_id = payload.get("sub")
    if not data.logs:
        raise HTTPException(status_code=400, detail="Logs data is empty")

    # Enrich logs with metadata
    for log_entry in data.logs:
        log_entry["user_id"] = user_id
        log_entry["board_id"] = data.board_id
        log_entry["ip"] = request.client.host if request.client else "unknown"
        log_entry["mac_id"] = None
        log_entry["created_at"] = datetime.now(timezone.utc)

    await request.app.db["boards.log"].insert_many(data.logs)
    return {"status": "success"}