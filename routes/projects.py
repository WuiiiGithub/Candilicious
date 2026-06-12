from fastapi import APIRouter, Depends, Request
from . import verify_token
router = APIRouter()

# fetching all the projects
@router.get("/projects", dependencies=Depends([verify_token]))
async def projects(request: Request, id: str):
    pass

@router.get("/project", dependencies=Depends[verify_token])
async def get_project(request: Request, id: str):
    pass

@router.post("/project", dependencies=Depends[verify_token])
async def create_project(request: Request, id: str):
    pass

@router.put("/project", dependencies=Depends[verify_token])
async def update_project(request: Request, id: str):
    pass

@router.delete("/project", dependencies=Depends[verify_token])
async def delete_project(request: Request, id: str):
    pass