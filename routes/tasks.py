from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
from library.ga_mp import track_event
from . import verify_token, limiter, rate_limit_ip, rate_limit_user

router = APIRouter()


async def log_task_event(
    request: Request, user_id: str, project_id: str, board_id: str,
    event_name: str, avg_jerk: list | None = None,
    avg_pointer_speed: float | None = None,
    session_id: str | None = None
):
    await request.app.db["tasks.log"].insert_one({
        "user_id": user_id,
        "avg_jerk": avg_jerk,
        "avg_pointer_speed": avg_pointer_speed,
        "event_name": event_name,
        "occured_at": datetime.now(timezone.utc),
        "project_id": project_id,
        "board_id": board_id,
        "session_id": session_id,
    })


async def log_progress(
    request: Request, user_id: str, project_id: str, project: dict,
    avg_jerk: list | None = None, avg_pointer_speed: float | None = None,
    session_id: str | None = None
):
    counts = project.get("boards", {})
    total = sum(counts.values())
    done = counts.get("done", 0)
    progress = round((done / total) * 100) if total > 0 else 0
    await request.app.db["tasks.log"].insert_one({
        "user_id": user_id,
        "avg_jerk": avg_jerk,
        "avg_pointer_speed": avg_pointer_speed,
        "event_name": "progress_updated",
        "occured_at": datetime.now(timezone.utc),
        "project_id": project_id,
        "board_id": None,
        "progress_percent": progress,
        "total_tasks": total,
        "done_tasks": done,
        "session_id": session_id,
    })


@router.get("")
@limiter.limit("120/minute", key_func=rate_limit_ip)
async def get_tasks(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    project_id = body.get("project_id")
    board_id = body.get("board_id")

    # Build board query
    query = {"user_id": user_id}
    if project_id:
        query["project_id"] = project_id
    if board_id:
        query["board_id"] = board_id

    boards = await request.app.db["boards.docs"].find(query).to_list(length=None)
    if not boards:
        return []

    result = []
    for board in boards:
        tasks = board.get("tasks", {})
        for task_id, task in tasks.items():
            result.append({
                "task_id": task_id,
                "board_id": board.get("board_id"),
                "project_id": board.get("project_id"),
                "text": task.get("text"),
                "priority": task.get("priority", 1),
                "status": task.get("status", "todo"),
                "created_at": task.get("created_at"),
                "completed_at": task.get("completed_at"),
            })

    return result


@router.post("")
@limiter.limit("60/minute", key_func=rate_limit_ip)
@limiter.limit("120/hour", key_func=rate_limit_user)
async def create_task(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    text = body.get("text")
    created_at = body.get("created_at")

    if not all([user_id, project_id, board_id, text, created_at]):
        raise HTTPException(
            status_code=400,
            detail="user_id, project_id, board_id, text, and created_at are required"
        )

    board = await request.app.db["boards.docs"].find_one(
        {"board_id": board_id, "project_id": project_id, "user_id": user_id}
    )
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")

    task_id = str(uuid.uuid4())
    priority = body.get("priority", 1)
    new_task = {
        "text": text,
        "priority": priority,
        "status": "todo",
        "created_at": created_at,
    }

    await request.app.db["boards.docs"].update_one(
        {"board_id": board_id},
        {"$set": {f"tasks.{task_id}": new_task}}
    )

    await log_task_event(
        request, user_id, project_id, board_id, "task_created",
        avg_jerk=body.get("avg_jerk"),
        avg_pointer_speed=body.get("avg_pointer_speed"),
        session_id=body.get("session_id"),
    )

    project = await request.app.db["projects.docs"].find_one({"project_id": project_id})
    if project:
        # update project counts
        boards = await request.app.db["boards.docs"].find({"project_id": project_id}).to_list(length=None)
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
        project = await request.app.db["projects.docs"].find_one({"project_id": project_id})
        if project:
            await log_progress(
                request, user_id, project_id, project,
                avg_jerk=body.get("avg_jerk"),
                avg_pointer_speed=body.get("avg_pointer_speed"),
                session_id=body.get("session_id"),
            )

    return {"status": "success", "task_id": task_id, "task": new_task}


@router.patch("")
@limiter.limit("60/minute", key_func=rate_limit_ip)
@limiter.limit("120/hour", key_func=rate_limit_user)
async def update_task(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    task_id = body.get("task_id")

    if not all([user_id, project_id, board_id, task_id]):
        raise HTTPException(
            status_code=400,
            detail="user_id, project_id, board_id, and task_id are required"
        )

    board = await request.app.db["boards.docs"].find_one(
        {"board_id": board_id, "project_id": project_id, "user_id": user_id}
    )
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")

    tasks = board.get("tasks", {})
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

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

    if update_fields:
        await request.app.db["boards.docs"].update_one(
            {"board_id": board_id},
            {"$set": update_fields}
        )

        # Log each type of change
        if "text" in body:
            await log_task_event(
                request, user_id, project_id, board_id, "task_renamed",
                avg_jerk=body.get("avg_jerk"),
                avg_pointer_speed=body.get("avg_pointer_speed"),
                session_id=body.get("session_id"),
            )
        if "priority" in body:
            await log_task_event(
                request, user_id, project_id, board_id, "task_priority_changed",
                avg_jerk=body.get("avg_jerk"),
                avg_pointer_speed=body.get("avg_pointer_speed"),
                session_id=body.get("session_id"),
            )
        if "status" in body:
            await log_task_event(
                request, user_id, project_id, board_id, "task_status_changed",
                avg_jerk=body.get("avg_jerk"),
                avg_pointer_speed=body.get("avg_pointer_speed"),
                session_id=body.get("session_id"),
            )
            if body["status"] == "done":
                track_event("task_completed", {
                    "project_id": str(project_id),
                    "board_id": str(board_id),
                    "task_id": str(task_id),
                    "session_id": str(body.get("session_id") or ""),
                }, user_id=user_id)

        # Recalculate project counts if status changed
        if "status" in body:
            boards = await request.app.db["boards.docs"].find({"project_id": project_id}).to_list(length=None)
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
            project = await request.app.db["projects.docs"].find_one({"project_id": project_id})
            if project:
                await log_progress(
                    request, user_id, project_id, project,
                    avg_jerk=body.get("avg_jerk"),
                    avg_pointer_speed=body.get("avg_pointer_speed"),
                    session_id=body.get("session_id"),
                )

    return {"status": "success"}


@router.delete("")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def delete_task(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    task_id = body.get("task_id")

    if not all([user_id, project_id, board_id, task_id]):
        raise HTTPException(
            status_code=400,
            detail="user_id, project_id, board_id, and task_id are required"
        )

    board = await request.app.db["boards.docs"].find_one(
        {"board_id": board_id, "project_id": project_id, "user_id": user_id}
    )
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")

    tasks = board.get("tasks", {})
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    await request.app.db["boards.docs"].update_one(
        {"board_id": board_id},
        {"$unset": {f"tasks.{task_id}": ""}}
    )

    await log_task_event(
        request, user_id, project_id, board_id, "task_deleted",
        avg_jerk=body.get("avg_jerk"),
        avg_pointer_speed=body.get("avg_pointer_speed"),
        session_id=body.get("session_id"),
    )

    # Recalculate project counts after deletion
    boards = await request.app.db["boards.docs"].find({"project_id": project_id}).to_list(length=None)
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
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id})
    if project:
        await log_progress(
            request, user_id, project_id, project,
            avg_jerk=body.get("avg_jerk"),
            avg_pointer_speed=body.get("avg_pointer_speed"),
            session_id=body.get("session_id"),
        )

    return {"status": "success"}
