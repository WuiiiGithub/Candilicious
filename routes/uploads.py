import re
import time
import hashlib
import cloudinary
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import config
from . import verify_token, limiter, rate_limit_ip, rate_limit_user

router = APIRouter()

MAX_SIZES = {
    "pfp": 256 * 1024,
    "thumbnail": 128 * 1024,
}

ALLOWED_FOLDERS = {
    "candilicious",
    "candilicious/pfp",
    "candilicious/thumbnails",
    "candilicious/posts",
}


class SignedParamsRequest(BaseModel):
    folder: str = "candilicious"
    max_bytes: Optional[int] = None


@router.post("/signed-params")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def get_signed_params(
    request: Request,
    body: SignedParamsRequest,
    payload: dict = Depends(verify_token),
):
    if not config.CLOUDINARY_URL:
        raise HTTPException(status_code=500, detail="Cloudinary not configured")

    folder = (body.folder or "").strip().strip("/")
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(status_code=400, detail="Folder not allowed")

    cloudinary.config()
    cloud_name = config.CLOUDINARY_URL.split("@")[-1] if "@" in config.CLOUDINARY_URL else ""

    timestamp = int(time.time())
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
    }

    if body.max_bytes:
        params_to_sign["eager"] = "w_800,h_800,c_limit"

    sorted_str = "&".join(f"{k}={v}" for k, v in sorted(params_to_sign.items()))
    api_secret = ""
    if config.CLOUDINARY_URL and ":" in config.CLOUDINARY_URL and "@" in config.CLOUDINARY_URL:
        api_secret = config.CLOUDINARY_URL.split(":")[1].split("@")[0]

    signature = hashlib.sha1(f"{sorted_str}{api_secret}".encode()).hexdigest()

    api_key = ""
    if config.CLOUDINARY_URL and "//" in config.CLOUDINARY_URL:
        cred_part = config.CLOUDINARY_URL.split("//")[1].split("@")[0]
        api_key = cred_part.split(":")[0] if ":" in cred_part else ""

    return {
        "ok": 1,
        "upload_url": f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        "params": {
            "folder": body.folder,
            "timestamp": str(timestamp),
            "api_key": api_key,
            "signature": signature,
        },
    }


def _normalize_public_id(value: object) -> str:
    """Return a clean public_id string or raise 400.

    public_id may be a bare id ("candilicious/pfp/x.png") or a full Cloudinary
    URL; both are accepted, anything else is rejected."""
    if isinstance(value, str):
        public_id = value.strip()
    else:
        raise HTTPException(status_code=400, detail="public_id must be a string")

    if not public_id:
        raise HTTPException(status_code=400, detail="public_id is required")
    if "?" in public_id or "#" in public_id:
        public_id = public_id.split("?")[0].split("#")[0]

    match = re.search(r"/v\d+/(.+)\.\w+$", public_id)
    if match:
        public_id = match.group(1)
    return public_id


async def _owns_public_id(request: Request, user_id: str, public_id: str) -> bool:
    """Only allow deleting assets that are referenced by the caller's own docs.

    This closes the IDOR where any authenticated user could destroy any
    public_id on the account by checking every place app uploads are stored
    against the requesting user's documents."""
    escaped = re.escape(public_id)
    checks = [
        (request.app.db["users"], {"_id": user_id}, ["pfp", "profile_pfp"]),
        (request.app.db["social.posts"], {"user_id": user_id}, ["thumbnail_url"]),
        (request.app.db["posts.custom"], {"user_id": user_id}, ["thumbnail"]),
        (request.app.db["projects.docs"], {"user_id": user_id}, ["thumbnail_link"]),
        (request.app.db["boards.docs"], {"user_id": user_id}, ["thumbnail_link"]),
    ]
    for collection, query, fields in checks:
        for field in fields:
            doc = await collection.find_one({**query, field: {"$regex": escaped}})
            if doc:
                return True
    return False


@router.delete("/destroy")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def destroy_asset(
    request: Request,
    body: dict,
    payload: dict = Depends(verify_token),
):
    public_id = _normalize_public_id(body.get("public_id"))

    if not any(
        public_id == folder or public_id.startswith(folder + "/")
        for folder in ALLOWED_FOLDERS
    ):
        raise HTTPException(status_code=400, detail="public_id must be in an allowed folder")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not await _owns_public_id(request, user_id, public_id):
        raise HTTPException(status_code=403, detail="You can only delete your own uploads")

    if not config.CLOUDINARY_URL:
        raise HTTPException(status_code=500, detail="Cloudinary not configured")

    cloudinary.config()
    try:
        result = cloudinary.uploader.destroy(public_id)
        return {"ok": 1, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
