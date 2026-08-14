from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
from datetime import datetime, timezone
from library.ga_mp import track_event
from . import verify_token, limiter, rate_limit_ip, rate_limit_user
from .uploads import destroy_image_if_cloudinary

router = APIRouter()

@router.get("")
@limiter.limit("120/minute", key_func=rate_limit_ip)
async def get_projects(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
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

        board_counts = {p.get("project_id"): 0 for p in projects_list}
        boards_cursor = request.app.db["boards.docs"].find({"user_id": user_id}, {"project_id": 1})
        async for b in boards_cursor:
            pid = b.get("project_id")
            if pid in board_counts:
                board_counts[pid] += 1

        response = []
        for p in projects_list:
            response.append({
                "project_id": p.get("project_id"),
                "title": p.get("title"),
                "description": p.get("description"),
                "thumbnail_link": p.get("thumbnail_link"),
                "boards": p.get("boards", {"todo": 0, "cooking": 0, "done": 0}),
                "board_count": board_counts.get(p.get("project_id"), 0),
                "created_at": p.get("created_at")
            })
        return response

@router.post("")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def create_project(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = payload.get("sub")
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

    track_event("project_created", {
        "project_id": project_id,
    }, user_id=user_id)

    new_project.pop("_id", None)
    return {"status": "success", "project": new_project}

@router.patch("")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def update_project(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = payload.get("sub")
    project_id = body.get("project_id")
    
    if not all([user_id, project_id]):
        raise HTTPException(status_code=400, detail="user_id and project_id are required")
    
    project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or unauthorized")
        
    update_data = {}
    if "title" in body: update_data["title"] = body["title"]
    if "description" in body: update_data["description"] = body["description"]
    if "thumbnail_link" in body:
        if body["thumbnail_link"] != project.get("thumbnail_link"):
            destroy_image_if_cloudinary(project.get("thumbnail_link", ""))
        update_data["thumbnail_link"] = body["thumbnail_link"]
    
    if update_data:
        await request.app.db["projects.docs"].update_one(
            {"project_id": project_id},
            {"$set": update_data}
        )
        
    return {"status": "success"}

@router.delete("")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("40/hour", key_func=rate_limit_user)
async def delete_project(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    user_id = payload.get("sub")
    project_id = body.get("project_id")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
        
    if project_id:
        project = await request.app.db["projects.docs"].find_one({"project_id": project_id, "user_id": user_id})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found or unauthorized")

        destroy_image_if_cloudinary(project.get("thumbnail_link", ""))
        boards = await request.app.db["boards.docs"].find({"project_id": project_id}).to_list(length=None)
        for b in boards:
            destroy_image_if_cloudinary(b.get("thumbnail_link", ""))
        await request.app.db["projects.docs"].delete_one({"project_id": project_id})
        await request.app.db["boards.docs"].delete_many({"project_id": project_id})
    else:
        all_projects = await request.app.db["projects.docs"].find({"user_id": user_id}).to_list(length=None)
        for p in all_projects:
            destroy_image_if_cloudinary(p.get("thumbnail_link", ""))
        all_boards = await request.app.db["boards.docs"].find({"user_id": user_id}).to_list(length=None)
        for b in all_boards:
            destroy_image_if_cloudinary(b.get("thumbnail_link", ""))
        await request.app.db["projects.docs"].delete_many({"user_id": user_id})
        await request.app.db["boards.docs"].delete_many({"user_id": user_id})

    track_event("project_deleted", {"project_id": project_id or "all"}, user_id=user_id)

    return {"status": "success"}