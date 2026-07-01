from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from . import verify_token

router = APIRouter()

class WorkspaceRequest(BaseModel):
    action: str
    data: Optional[dict] = None

class PolicyData(BaseModel):
    id: str
    content: str
    version: Optional[str] = None

class RemindersData(BaseModel):
    gifs: list[str]
    texts: list[str]


@router.post("")
async def workspace(
    body: WorkspaceRequest,
    request: Request,
    payload: dict = Depends(verify_token)
):
    db = request.app.db

    if body.action == "get_policy":
        doc_id = (body.data or {}).get("id", "")
        return await get_policy(db, doc_id)
    elif body.action == "save_policy":
        return await save_policy(db, PolicyData(**(body.data or {})))
    elif body.action == "get_reminders":
        return await get_reminders(db)
    elif body.action == "save_reminders":
        return await save_reminders(db, RemindersData(**(body.data or {})))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")


async def get_policy(db, doc_id: str):
    doc = await db["Self"].find_one({"_id": doc_id})
    if not doc:
        return {"content": "", "version": None}
    return {"content": doc.get("content", ""), "version": doc.get("version")}


async def save_policy(db, data: PolicyData):
    update = {"content": data.content, "updated": datetime.now(timezone.utc)}
    if data.version is not None:
        update["version"] = data.version
    await db["Self"].update_one(
        {"_id": data.id},
        {"$set": update},
        upsert=True
    )
    return {"status": "saved"}


async def get_reminders(db):
    doc = await db["config"].find_one({"_id": "reminders"})
    if not doc:
        return {"gifs": [], "texts": []}
    return {"gifs": doc.get("gifs", []), "texts": doc.get("texts", [])}


async def save_reminders(db, data: RemindersData):
    await db["config"].update_one(
        {"_id": "reminders"},
        {"$set": {"gifs": data.gifs, "texts": data.texts}},
        upsert=True
    )
    return {"status": "saved"}
