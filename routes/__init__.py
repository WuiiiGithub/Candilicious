from fastapi import APIRouter
import speedtest, jwt, config
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)

def verify_token(token: str):
    try:
        payload = jwt.decode(
            token, 
            config.SECRET_KEY, 
            algorithms=["HS256"]
        )
        return payload
    except jwt.InvalidSignatureError:
        raise Exception("Unauthorized: Tampered token detected")

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