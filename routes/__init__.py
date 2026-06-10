from fastapi import APIRouter
import speedtest

router = APIRouter()

@router.get("/except")
def exception():
    pass

@router.get("/privacy")
def privacy():
    pass

@router.get("/about")
def about():
    pass

@router.get("/tos")
def tos():
    pass