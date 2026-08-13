import os
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
import config

router = APIRouter()


def _client_ip(request: Request) -> str:
    """Resolve the real client IP.

    In production (behind a proxy), trusts X-Forwarded-For. Locally, uses the
    direct connection IP since X-Forwarded-For is spoofable when exposed."""
    if config.IS_PROD:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return get_remote_address(request)


def _rate_limit_key(request: Request) -> str:
    """Per-request limiter key: real client IP, plus the authenticated user id
    when a valid JWT is present. Binds limits to both IP and account."""
    try:
        token = request.cookies.get("session_token")
        if not token:
            auth = request.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        if token:
            payload = _decode_token(token)
            sub = payload.get("sub")
            if sub:
                return f"{_client_ip(request)}:{sub}"
    except Exception:
        pass
    return _client_ip(request)


def rate_limit_ip(request: Request) -> str:
    return _client_ip(request)


def rate_limit_user(request: Request) -> str:
    return _rate_limit_key(request)


limiter = Limiter(key_func=_client_ip)
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


def optional_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get("session_token")
    if not token:
        return None
    try:
        return _decode_token(token)
    except jwt.PyJWTError:
        return None

class ExceptionRequest(BaseModel):
    type: str
    download: float
    upload: float
    ping: float

@router.post("/exception")
@limiter.limit("10/minute", key_func=rate_limit_ip)
@limiter.limit("20/hour", key_func=rate_limit_user)
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