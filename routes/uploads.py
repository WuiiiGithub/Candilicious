import time
import hashlib
import cloudinary
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import config
from . import verify_token

router = APIRouter()

MAX_SIZES = {
    "pfp": 256 * 1024,
    "thumbnail": 128 * 1024,
}


class SignedParamsRequest(BaseModel):
    folder: str = "candilicious"
    max_bytes: Optional[int] = None


@router.post("/signed-params")
async def get_signed_params(
    request: Request,
    body: SignedParamsRequest,
    payload: dict = Depends(verify_token),
):
    if not config.CLOUDINARY_URL:
        raise HTTPException(status_code=500, detail="Cloudinary not configured")

    cloudinary.config()
    cloud_name = config.CLOUDINARY_URL.split("@")[-1] if "@" in config.CLOUDINARY_URL else ""

    timestamp = int(time.time())
    params_to_sign = {
        "folder": body.folder,
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


@router.delete("/destroy")
async def destroy_asset(
    request: Request,
    body: dict,
    payload: dict = Depends(verify_token),
):
    public_id = body.get("public_id")
    if not public_id:
        raise HTTPException(status_code=400, detail="public_id is required")

    if not config.CLOUDINARY_URL:
        raise HTTPException(status_code=500, detail="Cloudinary not configured")

    cloudinary.config()
    try:
        result = cloudinary.uploader.destroy(public_id)
        return {"ok": 1, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
