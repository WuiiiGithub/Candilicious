import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from . import verify_token, limiter, rate_limit_ip, rate_limit_user

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_PATHS = {
    ("PATCH", "/api/projects/boards/tasks"),
    ("DELETE", "/api/projects/boards/tasks"),
}


class BulkOp(BaseModel):
    method: str
    path: str
    body: dict


class BulkRequest(BaseModel):
    ops: list[BulkOp]


async def _handle_patch_task(request: Request, user_id: str, body: dict):
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    task_id = body.get("task_id")

    if not all([user_id, project_id, board_id, task_id]):
        return

    board = await request.app.db["boards.docs"].find_one(
        {"board_id": board_id, "project_id": project_id, "user_id": user_id}
    )
    if not board:
        return

    tasks = board.get("tasks", {})
    if task_id not in tasks:
        return

    update_fields = {}
    if "text" in body:
        update_fields[f"tasks.{task_id}.text"] = body["text"]
    if "priority" in body:
        update_fields[f"tasks.{task_id}.priority"] = body["priority"]
    if "status" in body:
        update_fields[f"tasks.{task_id}.status"] = body["status"]
    if "created_at" in body:
        update_fields[f"tasks.{task_id}.created_at"] = body["created_at"]
    if "completed_at" in body:
        update_fields[f"tasks.{task_id}.completed_at"] = body["completed_at"]
    if "note_name" in body:
        update_fields[f"tasks.{task_id}.note_name"] = body["note_name"]
    if "note_id" in body:
        update_fields[f"tasks.{task_id}.note_id"] = body["note_id"]

    if update_fields:
        await request.app.db["boards.docs"].update_one(
            {"board_id": board_id},
            {"$set": update_fields}
        )

        if "text" in body:
            await _log_task_event(request, user_id, project_id, board_id, "task_renamed", body.get("session_id"))
        if "priority" in body:
            await _log_task_event(request, user_id, project_id, board_id, "task_priority_changed", body.get("session_id"))
        if "status" in body:
            await _log_task_event(request, user_id, project_id, board_id, "task_status_changed", body.get("session_id"))

        if "status" in body:
            await _recalculate_counts(request, project_id)


async def _handle_delete_task(request: Request, user_id: str, body: dict):
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    task_id = body.get("task_id")

    if not all([user_id, project_id, board_id, task_id]):
        return

    board = await request.app.db["boards.docs"].find_one(
        {"board_id": board_id, "project_id": project_id, "user_id": user_id}
    )
    if not board:
        return

    tasks = board.get("tasks", {})
    if task_id not in tasks:
        return

    await request.app.db["boards.docs"].update_one(
        {"board_id": board_id},
        {"$unset": {f"tasks.{task_id}": ""}}
    )

    await _log_task_event(request, user_id, project_id, board_id, "task_deleted", body.get("session_id"))
    await _recalculate_counts(request, project_id)


async def _log_task_event(
    request: Request, user_id: str, project_id: str,
    board_id: str, event_name: str, session_id: str | None = None
):
    await request.app.db["tasks.log"].insert_one({
        "user_id": user_id,
        "avg_jerk": None,
        "avg_pointer_speed": None,
        "event_name": event_name,
        "occured_at": datetime.now(timezone.utc),
        "project_id": project_id,
        "board_id": board_id,
        "session_id": session_id,
    })


async def _recalculate_counts(request: Request, project_id: str):
    boards = await request.app.db["boards.docs"].find(
        {"project_id": project_id}
    ).to_list(length=None)
    counts = {"todo": 0, "cooking": 0, "done": 0}
    for b in boards:
        for t_id, t in b.get("tasks", {}).items():
            s = t.get("status", "todo")
            if s in counts:
                counts[s] += 1
    await request.app.db["projects.docs"].update_one(
        {"project_id": project_id},
        {"$set": {"boards": counts}}
    )


HANDLERS = {
    ("PATCH", "/api/projects/boards/tasks"): _handle_patch_task,
    ("DELETE", "/api/projects/boards/tasks"): _handle_delete_task,
}


@router.post("")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def bulk_execute(
    request: Request,
    body: BulkRequest,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if len(body.ops) > 50:
        raise HTTPException(status_code=400, detail="Batch size exceeded (max 50)")

    results = []
    for op in body.ops:
        key = (op.method.upper(), op.path)
        if key not in ALLOWED_PATHS:
            results.append({"ok": 0, "error": "forbidden_path"})
            continue

        handler = HANDLERS.get(key)
        if not handler:
            results.append({"ok": 0, "error": "no_handler"})
            continue

        try:
            await handler(request, user_id, op.body)
            results.append({"ok": 1})
        except Exception as e:
            logger.warning(f"Bulk op failed: {op.method} {op.path} — {e}")
            results.append({"ok": 0, "error": "internal"})

    return {"ok": 1, "results": results}
