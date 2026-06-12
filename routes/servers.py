from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/servers")
async def servers(reqest: Request):
    pass