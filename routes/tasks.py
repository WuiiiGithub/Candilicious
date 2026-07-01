from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
from . import verify_token

router = APIRouter()


@router.get("")
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
                "priority": task.get("priority", "normal"),
                "status": task.get("status", "todo"),
                "created_at": task.get("created_at"),
            })

    return result


@router.post("")
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
    new_task = {
        "text": text,
        "priority": "normal",
        "status": "todo",
        "created_at": created_at,
    }

    await request.app.db["boards.docs"].update_one(
        {"board_id": board_id},
        {"$set": {f"tasks.{task_id}": new_task}}
    )

    return {"status": "success", "task_id": task_id, "task": new_task}


@router.patch("")
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

    if update_fields:
        await request.app.db["boards.docs"].update_one(
            {"board_id": board_id},
            {"$set": update_fields}
        )

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

    return {"status": "success"}


@router.delete("")
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

    return {"status": "success"}
