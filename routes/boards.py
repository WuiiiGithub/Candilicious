from fastapi import APIRouter, Request, HTTPException
import uuid

router = APIRouter()

async def recalculate_project_counts(request: Request, project_id: str):
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

@router.get("")
async def get_boards(request: Request):
    # Accept user_id, project_id, and board_id from query parameters
    user_id = request.query_params.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
        
    project_id = request.query_params.get("project_id")
    board_id = request.query_params.get("board_id")
    
    if board_id:
        query = {"board_id": board_id, "user_id": user_id}
        if project_id:
            query["project_id"] = project_id
            
        board = await request.app.db["boards.docs"].find_one(query)
        if not board:
            raise HTTPException(status_code=404, detail="Board not found or unauthorized")
            
        return {
            "board_id": board.get("board_id"),
            "project_id": board.get("project_id"),
            "title": board.get("title"),
            "description": board.get("description", ""),
            "thumbnail_link": board.get("thumbnail_link"),
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
                "description": board.get("description", ""),
                "thumbnail_link": board.get("thumbnail_link"),
                "tasks": board.get("tasks", {}),
                "created_at": board.get("created_at")
            })
        return response
    else:
        cursor = request.app.db["boards.docs"].find({"user_id": user_id})
        boards_list = await cursor.to_list(length=None)
        response = []
        for board in boards_list:
            response.append({
                "board_id": board.get("board_id"),
                "project_id": board.get("project_id"),
                "title": board.get("title"),
                "description": board.get("description", ""),
                "thumbnail_link": board.get("thumbnail_link"),
                "tasks": board.get("tasks", {}),
                "created_at": board.get("created_at")
            })
        return response

@router.post("")
async def create_board(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    project_id = body.get("project_id")
    title = body.get("title")
    description = body.get("description")
    created_at = body.get("created_at")
    
    if not all([user_id, project_id, title, description, created_at]):
        raise HTTPException(status_code=400, detail="Missing required fields")
        
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    board_id = str(uuid.uuid4())
    
    new_board = {
        "user_id": user_id,
        "project_id": project_id,
        "board_id": board_id,
        "title": title,
        "description": description,
        "thumbnail_link": body.get("thumbnail_link", ""),
        "tasks": {},
        "created_at": created_at
    }
    
    await request.app.db["boards.docs"].insert_one(new_board)
    new_board.pop("_id", None)
    
    return {"status": "success", "board": new_board}

@router.patch("")
async def update_board(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    
    if not all([user_id, project_id, board_id]):
        raise HTTPException(status_code=400, detail="Missing required fields")
        
    board = await request.app.db["boards.docs"].find_one({"board_id": board_id, "project_id": project_id, "user_id": user_id})
    if not board:
        raise HTTPException(status_code=404, detail="Board not found or unauthorized")
        
    update_data = {}
    if "title" in body: update_data["title"] = body["title"]
    if "description" in body: update_data["description"] = body["description"]
    if "thumbnail_link" in body: update_data["thumbnail_link"] = body["thumbnail_link"]
    
    if update_data:
        await request.app.db["boards.docs"].update_one(
            {"board_id": board_id},
            {"$set": update_data}
        )
        
    return {"status": "success"}

@router.delete("")
async def delete_board(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    project_id = body.get("project_id")
    board_id = body.get("board_id")
    
    if not all([user_id, project_id]):
        raise HTTPException(status_code=400, detail="user_id and project_id are required")
        
    if board_id:
        board = await request.app.db["boards.docs"].find_one({"board_id": board_id, "project_id": project_id, "user_id": user_id})
        if not board:
            raise HTTPException(status_code=404, detail="Board not found or unauthorized")
            
        await request.app.db["boards.docs"].delete_one({"board_id": board_id})
        await recalculate_project_counts(request, project_id)
    else:
        await request.app.db["boards.docs"].delete_many({"project_id": project_id, "user_id": user_id})
        await recalculate_project_counts(request, project_id)
        
    return {"status": "success"}