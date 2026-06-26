from fastapi import APIRouter, Request, HTTPException
import uuid
from datetime import datetime, timezone

router = APIRouter()

@router.get("")
async def get_projects(request: Request):
    # Accept user_id and project_id from query parameters
    user_id = request.query_params.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
        
    project_id = request.query_params.get("project_id")
    
    if project_id:
        project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        return {
            "project_id": project.get("project_id"),
            "title": project.get("title"),
            "description": project.get("description"),
            "thumbnail_link": project.get("thumbnail_link"),
            "boards": project.get("boards", {"todo": 0, "cooking": 0, "done": 0}),
            "created_at": project.get("created_at")
        }
    else:
        cursor = request.app.db["projects.docs"].find({"user_id": user_id}).sort("created_at", -1)
        projects_list = await cursor.to_list(length=None)
        
        response = []
        for p in projects_list:
            response.append({
                "project_id": p.get("project_id"),
                "title": p.get("title"),
                "description": p.get("description"),
                "thumbnail_link": p.get("thumbnail_link"),
                "boards": p.get("boards", {"todo": 0, "cooking": 0, "done": 0}),
                "created_at": p.get("created_at")
            })
        return response

@router.post("")
async def create_project(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    title = body.get("title")
    description = body.get("description")
    created_at = body.get("created_at")
    
    if not all([user_id, title, description, created_at]):
        raise HTTPException(status_code=400, detail="user_id, title, description, and created_at are required")
        
    project_id = str(uuid.uuid4())
    
    new_project = {
        "user_id": user_id,
        "project_id": project_id,
        "title": title,
        "description": description,
        "thumbnail_link": body.get("thumbnail_link", ""),
        "boards": {"todo": 0, "cooking": 0, "done": 0},
        "created_at": created_at
    }
    
    await request.app.db["projects.docs"].insert_one(new_project)
    
    new_project.pop("_id", None)
    return {"status": "success", "project": new_project}

@router.patch("")
async def update_project(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    project_id = body.get("project_id")
    
    if not all([user_id, project_id]):
        raise HTTPException(status_code=400, detail="user_id and project_id are required")
    
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    update_data = {}
    if "title" in body: update_data["title"] = body["title"]
    if "description" in body: update_data["description"] = body["description"]
    if "thumbnail_link" in body: update_data["thumbnail_link"] = body["thumbnail_link"]
    
    if update_data:
        await request.app.db["projects.docs"].update_one(
            {"project_id": project_id},
            {"$set": update_data}
        )
        
    return {"status": "success"}

@router.delete("")
async def delete_project(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = body.get("user_id")
    project_id = body.get("project_id")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
        
    if project_id:
        project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found or unauthorized")
            
        await request.app.db["projects.docs"].delete_one({"project_id": project_id})
        await request.app.db["boards.docs"].delete_many({"project_id": project_id})
    else:
        await request.app.db["projects.docs"].delete_many({"user_id": user_id})
        await request.app.db["boards.docs"].delete_many({"user_id": user_id})
        
    return {"status": "success"}