import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
import config

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
security = HTTPBearer(auto_error=False)

def _decode_token(token: str) -> dict:
    return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])

def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized: no token provided")
    try:
        return _decode_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {str(e)}")

class ExceptionRequest(BaseModel):
    type: str
    download: float
    upload: float
    ping: float

@router.post("/exception")
async def exception(
    data: ExceptionRequest,
    request: Request,
    payload: dict = Depends(verify_token)
):
    if data.type != "low_network":
        raise HTTPException(status_code=400, detail="Invalid exception type")
    
    user_id = payload.get("sub")
    request.app.state.bot.userNetworkConnection[user_id] = {
        "download": data.download,
        "upload": data.upload,
        "ping": data.ping,
    }
    return {
        "ok": 1,
        "detail": "Exception speed data recorded"
    }