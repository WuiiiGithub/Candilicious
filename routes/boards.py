from fastapi import APIRouter, Depends, Request
from . import verify_token
router = APIRouter()

# fetching all the boards
@router.get("/boards", dependencies=Depends([verify_token]))
async def boards(request: Request, id: str):
    pass

@router.get("/board", dependencies=Depends[verify_token])
async def get_board(request: Request, id: str):
    pass

@router.post("/board", dependencies=Depends[verify_token])
async def create_board(request: Request, id: str):
    pass

@router.put("/board", dependencies=Depends[verify_token])
async def update_board(request: Request, id: str):
    pass

@router.delete("/board", dependencies=Depends[verify_token])
async def delete_board(request: Request, id: str):
    pass