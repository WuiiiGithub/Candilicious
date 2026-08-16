import os
import time
import hashlib
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
import config

router = APIRouter()

# In-memory revocation denylist: sha256(token) -> expiry (unix seconds).
# Logged-out JWTs are rejected here until they naturally expire. Zero per-request
# DB cost (a dict lookup is ~microseconds); the only trade-off is that the list
# is cleared on process restart, so a revoked token revives at most until its
# own exp claim after a restart.
_revoked_tokens: dict[str, float] = {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def revoke_token(token: str, expires_at: float) -> None:
    """Server-side kill switch for a JWT. Call on logout."""
    if expires_at and expires_at > time.time():
        _revoked_tokens[_token_hash(token)] = expires_at


def _is_revoked(token: str) -> bool:
    key = _token_hash(token)
    exp = _revoked_tokens.get(key)
    if exp is None:
        return False
    if exp < time.time():
        _revoked_tokens.pop(key, None)
        return False
    return True


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
        token = None
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
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized: no token provided")
    try:
        payload = _decode_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {str(e)}")
    if _is_revoked(token):
        raise HTTPException(status_code=401, detail="Unauthorized: session revoked")
    return payload


def optional_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    if not token:
        return None
    try:
        payload = _decode_token(token)
    except jwt.PyJWTError:
        return None
    if _is_revoked(token):
        return None
    return payload

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