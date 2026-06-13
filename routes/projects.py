from fastapi import APIRouter, Depends, Request, HTTPException
from . import verify_token

router = APIRouter()

# fetching all the projects
@router.get("/projects")
async def projects(request: Request, id: str, payload: dict = Depends(verify_token)):
    if payload.get("sub") != id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user_data = await request.app.db["users"].find_one({"_id": id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    projects_list = user_data.get("projects", [])
    
    # Calculate progress for each board in projects
    for project in projects_list:
        for board in project.get("boards", []):
            board_doc = await request.app.db["boards"].find_one({"_id": board["id"]})
            if board_doc:
                tasks = board_doc.get("tasks", [])
                progress = {
                    "todo": len([t for t in tasks if t.get("status") == "todo"]),
                    "cooking": len([t for t in tasks if t.get("status") == "cooking"]),
                    "done": len([t for t in tasks if t.get("status") == "done"])
                }
                board["progress"] = progress
            else:
                board["progress"] = {"todo": 0, "cooking": 0, "done": 0}
    return projects_list

@router.get("/project")
async def get_project(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    for project in user_data.get("projects", []):
        if project.get("name") == id:
            for board in project.get("boards", []):
                board_doc = await request.app.db["boards"].find_one({"_id": board["id"]})
                if board_doc:
                    tasks = board_doc.get("tasks", [])
                    progress = {
                        "todo": len([t for t in tasks if t.get("status") == "todo"]),
                        "cooking": len([t for t in tasks if t.get("status") == "cooking"]),
                        "done": len([t for t in tasks if t.get("status") == "done"])
                    }
                    board["progress"] = progress
                else:
                    board["progress"] = {"todo": 0, "cooking": 0, "done": 0}
            return project
    raise HTTPException(status_code=404, detail="Project not found")

@router.post("/project")
async def create_project(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    projects_list = user_data.get("projects", [])
    if any(p.get("name") == id for p in projects_list):
        raise HTTPException(status_code=400, detail="Project already exists")
    
    new_project = {"name": id, "boards": []}
    projects_list.append(new_project)
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"projects": projects_list}}
    )
    return {"status": "success", "project": new_project}

@router.put("/project")
async def update_project(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    body = await request.json()
    new_name = body.get("name")
    if not new_name:
        raise HTTPException(status_code=400, detail="New name is required")
        
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    projects_list = user_data.get("projects", [])
    project_found = False
    for p in projects_list:
        if p.get("name") == id:
            p["name"] = new_name
            project_found = True
            break
            
    if not project_found:
        raise HTTPException(status_code=404, detail="Project not found")
        
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"projects": projects_list}}
    )
    return {"status": "success"}

@router.delete("/project")
async def delete_project(request: Request, id: str, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    projects_list = user_data.get("projects", [])
    new_projects = [p for p in projects_list if p.get("name") != id]
    if len(new_projects) == len(projects_list):
        raise HTTPException(status_code=404, detail="Project not found")
        
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"projects": new_projects}}
    )
    return {"status": "success"}