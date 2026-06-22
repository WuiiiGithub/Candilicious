from fastapi import APIRouter, Request, HTTPException
import uuid
from datetime import datetime, timezone

router = APIRouter()

@router.get("")
async def get_projects(request: Request, user_id: str):
    cursor = request.app.db["projects.docs"].find({"user_id": user_id}).sort("created_at", -1)
    projects_list = await cursor.to_list(length=None)
    
    response = []
    for p in projects_list:
        response.append({
            "project_id": p.get("project_id"),
            "title": p.get("title"),
            "description": p.get("description"),
            "image_link": p.get("image_link"),
            "boards": p.get("boards", {"todo": 0, "cooking": 0, "done": 0}),
            "created_at": p.get("created_at")
        })
    return response

@router.post("")
async def create_project(request: Request, user_id: str):
    body = await request.json()
    project_id = str(uuid.uuid4())
    
    new_project = {
        "user_id": user_id,
        "project_id": project_id,
        "title": body.get("title", ""),
        "description": body.get("description", ""),
        "image_link": body.get("image_link", ""),
        "boards": {"todo": 0, "cooking": 0, "done": 0},
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Using upsert-like logic if we want, but since project_id is new, insert is fine
    await request.app.db["projects.docs"].insert_one(new_project)
    
    new_project.pop("_id", None)
    return {"status": "success", "project": new_project}

@router.put("")
async def update_project(request: Request, project_id: str, user_id: str):
    body = await request.json()
    
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    update_data = {}
    if "title" in body: update_data["title"] = body["title"]
    if "description" in body: update_data["description"] = body["description"]
    if "image_link" in body: update_data["image_link"] = body["image_link"]
    
    if update_data:
        await request.app.db["projects.docs"].update_one(
            {"project_id": project_id},
            {"$set": update_data}
        )
        
    return {"status": "success"}

@router.delete("")
async def delete_project(request: Request, project_id: str, user_id: str):
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    await request.app.db["projects.docs"].delete_one({"project_id": project_id})
    await request.app.db["boards.docs"].delete_many({"project_id": project_id})
    
    return {"status": "success"}