from fastapi import APIRouter, Depends, Request, HTTPException
from . import verify_token

router = APIRouter()

@router.get("/check")
async def check(request: Request):
    return request.app.state.bot.__dict__

# fetching all the boards
@router.get("/boards")
async def boards(request: Request, id: str, payload: dict = Depends(verify_token)):
    if payload.get("sub") != id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user_data = await request.app.db["users"].find_one({"_id": id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    board_ids = []
    for project in user_data.get("projects", []):
        for board in project.get("boards", []):
            board_ids.append(board["id"])
            
    cursor = request.app.db["boards"].find({"_id": {"$in": board_ids}})
    boards_list = await cursor.to_list(length=100)
    return boards_list

@router.get("/board")
async def get_board(request: Request, id: str, payload: dict = Depends(verify_token)):
    board_doc = await request.app.db["boards"].find_one({"_id": id})
    if not board_doc:
        raise HTTPException(status_code=404, detail="Board not found")
    if board_doc.get("user_id") != payload.get("sub"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return board_doc

@router.post("/board")
async def create_board(request: Request, id: str, project_name: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
        
    project = next((p for p in user_data.get("projects", []) if p.get("name") == project_name), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if any(b.get("id") == id for b in project.get("boards", [])):
        raise HTTPException(status_code=400, detail="Board already exists in project")
        
    board_doc = {
        "_id": id,
        "user_id": user_id,
        "tasks": []
    }
    await request.app.db["boards"].insert_one(board_doc)
    
    new_board_ref = {"id": id, "name": id}
    project["boards"].append(new_board_ref)
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"projects": user_data["projects"]}}
    )
    return {"status": "success", "board": board_doc}

@router.put("/board")
async def update_board(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    body = await request.json()
    new_tasks = body.get("tasks")
    new_name = body.get("name")
    
    board_doc = await request.app.db["boards"].find_one({"_id": id})
    if not board_doc:
        raise HTTPException(status_code=404, detail="Board not found")
    if board_doc.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
        
    update_data = {}
    if new_tasks is not None:
        update_data["tasks"] = new_tasks
        
    if update_data:
        await request.app.db["boards"].update_one(
            {"_id": id},
            {"$set": update_data}
        )
        
    if new_name is not None:
        user_data = await request.app.db["users"].find_one({"_id": user_id})
        if user_data:
            updated = False
            for project in user_data.get("projects", []):
                for board in project.get("boards", []):
                    if board["id"] == id:
                        board["name"] = new_name
                        updated = True
            if updated:
                await request.app.db["users"].update_one(
                    {"_id": user_id},
                    {"$set": {"projects": user_data["projects"]}}
                )
    return {"status": "success"}

@router.delete("/board")
async def delete_board(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    board_doc = await request.app.db["boards"].find_one({"_id": id})
    if not board_doc:
        raise HTTPException(status_code=404, detail="Board not found")
    if board_doc.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
        
    await request.app.db["boards"].delete_one({"_id": id})
    
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if user_data:
        for project in user_data.get("projects", []):
            project["boards"] = [b for b in project.get("boards", []) if b["id"] != id]
        await request.app.db["users"].update_one(
            {"_id": user_id},
            {"$set": {"projects": user_data["projects"]}}
        )
    return {"status": "success"}