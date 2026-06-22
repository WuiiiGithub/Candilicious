from fastapi import APIRouter, Request, HTTPException
import uuid
from datetime import datetime, timezone

router = APIRouter()

async def recalculate_project_counts(request: Request, project_id: str):
    # Recalculate tasks counts across all boards in a project
    boards = await request.app.db["boards.docs"].find({"project_id": project_id}).to_list(length=None)
    
    counts = {"todo": 0, "cooking": 0, "done": 0}
    for board in boards:
        tasks = board.get("tasks", {})
        for task_id, task in tasks.items():
            status = task.get("status", "todo")
            if status in counts:
                counts[status] += 1
                
    await request.app.db["projects.docs"].update_one(
        {"project_id": project_id},
        {"$set": {"boards": counts}}
    )

@router.post("")
async def create_board(request: Request, user_id: str, project_id: str):
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    body = await request.json()
    board_id = str(uuid.uuid4())
    
    new_board = {
        "user_id": user_id,
        "project_id": project_id,
        "board_id": board_id,
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "image_link": body.get("image_link", ""),
        "tasks": {},
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await request.app.db["boards.docs"].insert_one(new_board)
    new_board.pop("_id", None)
    
    return {"status": "success", "board": new_board}

from typing import Optional

@router.get("")
async def get_board(request: Request, user_id: str, board_id: Optional[str] = None, project_id: Optional[str] = None):
    if board_id:
        board = await request.app.db["boards.docs"].find_one({"board_id": board_id, "user_id": user_id})
        if not board:
            raise HTTPException(status_code=404, detail="Board not found or unauthorized")
            
        return {
            "board_id": board.get("board_id"),
            "project_id": board.get("project_id"),
            "title": board.get("title"),
            "image_link": board.get("image_link"),
            "tasks": board.get("tasks", {}),
            "created_at": board.get("created_at")
        }
    elif project_id:
        cursor = request.app.db["boards.docs"].find({"project_id": project_id, "user_id": user_id})
        boards_list = await cursor.to_list(length=None)
        
        response = []
        for board in boards_list:
            response.append({
                "board_id": board.get("board_id"),
                "project_id": board.get("project_id"),
                "title": board.get("title"),
                "image_link": board.get("image_link"),
                "tasks": board.get("tasks", {}),
                "created_at": board.get("created_at")
            })
        return response
    else:
        raise HTTPException(status_code=400, detail="Must provide board_id or project_id")

@router.put("")
async def update_board(request: Request, board_id: str, user_id: str):
    board = await request.app.db["boards.docs"].find_one({"board_id": board_id, "user_id": user_id})
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")
        
    body = await request.json()
    update_data = {}
    
    if "title" in body: update_data["title"] = body["title"]
    if "description" in body: update_data["description"] = body["description"]
    if "image_link" in body: update_data["image_link"] = body["image_link"]
    
    recount_needed = False
    
    if "tasks" in body:
        # Merge task updates
        current_tasks = board.get("tasks", {})
        for t_id, t_data in body["tasks"].items():
            if t_id not in current_tasks:
                current_tasks[t_id] = {}
            # Update specific fields or delete if requested (could be None to delete, but for now just update)
            if t_data is None:
                current_tasks.pop(t_id, None)
            else:
                current_tasks[t_id].update(t_data)
        update_data["tasks"] = current_tasks
        recount_needed = True
        
    if update_data:
        await request.app.db["boards.docs"].update_one(
            {"board_id": board_id},
            {"$set": update_data}
        )
        
    if recount_needed:
        await recalculate_project_counts(request, board.get("project_id"))
        
    return {"status": "success"}

@router.delete("")
async def delete_board(request: Request, board_id: str, user_id: str):
    board = await request.app.db["boards.docs"].find_one({"board_id": board_id, "user_id": user_id})
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")
        
    await request.app.db["boards.docs"].delete_one({"board_id": board_id})
    
    await recalculate_project_counts(request, board.get("project_id"))
    
    return {"status": "success"}