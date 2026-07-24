import secrets
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError
from typing import Optional
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from . import verify_token
import config

logger = logging.getLogger(__name__)

router = APIRouter()

OTP_TTL_MINUTES = 5
SESSION_TTL_SECONDS = 600

class WorkspaceRequest(BaseModel):
    action: str
    data: Optional[dict] = None

class PolicyData(BaseModel):
    id: str
    content: str
    version: Optional[str] = None

class RemindersData(BaseModel):
    gifs: list[str]
    texts: list[str]

class DropsData(BaseModel):
    mean_time: float = 30
    variance: float = 0.5
    collection_time: float = 30

class ResourceTier(BaseModel):
    base_mean: float = 60
    base_decay: float = 35
    decay_rate: float = 0.1
    std_dev: float = 10
    min: float = 2

class ResourcesData(BaseModel):
    wood: ResourceTier = ResourceTier()
    iron: ResourceTier = ResourceTier(base_mean=20, base_decay=12, decay_rate=0.1, std_dev=5, min=0)
    variance_factor_rate: float = 0.001
    variance_factor_min: float = 0.1

class ActivityTier(BaseModel):
    name: str
    multiplier: float
    bonus: float

class PremiumData(BaseModel):
    cost: float = 100
    ttl_days: float = 7
    unit: str = "iron"

class LevelUpData(BaseModel):
    xp_per_minute: int = 15
    xp_threshold: int = 5000
    wood_base: int = 100

class VariablesData(BaseModel):
    drops: DropsData = DropsData()
    resources: ResourcesData = ResourcesData()
    activity_tiers: list[list] = []
    premium: PremiumData = PremiumData()
    level_up: LevelUpData = LevelUpData()


VARIABLES_DEFAULTS = {
    "drops": {"mean_time": 30, "variance": 0.5, "collection_time": 30},
    "resources": {
        "wood": {"base_mean": 60, "base_decay": 35, "decay_rate": 0.1, "std_dev": 10, "min": 2},
        "iron": {"base_mean": 20, "base_decay": 12, "decay_rate": 0.1, "std_dev": 5, "min": 0},
        "variance_factor_rate": 0.001,
        "variance_factor_min": 0.1,
    },
    "activity_tiers": [
        ["No Activity", 1.0, 0.0],
        ["Stream", 1.5, 0.03],
        ["Cam", 2.0, 0.08],
        ["Cam + Stream", 2.5, 0.15],
    ],
    "premium": {"cost": 100, "ttl_days": 7, "unit": "iron"},
    "level_up": {"xp_per_minute": 15, "xp_threshold": 5000, "wood_base": 100},
}


async def get_owner_id(db) -> str:
    doc = await db["config"].find_one({"_id": "bot"}, projection={"owner_id": 1})
    if doc and doc.get("owner_id"):
        return str(doc["owner_id"])
    logger.warning("Bot config document missing owner_id — falling back to config.OWNER_ID")
    return str(config.OWNER_ID)


@router.post("")
async def workspace(
    body: WorkspaceRequest,
    request: Request,
    payload: dict = Depends(verify_token)
):
    db = request.app.db
    user_id = payload.get("sub")
    owner_id = await get_owner_id(db)

    if body.action == "request_otp":
        return await request_otp(db, request, user_id, owner_id)
    elif body.action == "verify_otp":
        return await verify_otp(db, user_id, body.data or {})
    elif body.action == "revoke_session":
        return await revoke_session(db, user_id, body.data or {})

    if user_id != owner_id:
        session = await db["admin_sessions"].find_one({"_id": user_id})
        if not session or session.get("expires_at", datetime.now(timezone.utc)) < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Only the bot owner can access the workspace")

    if body.action == "get_policy":
        doc_id = (body.data or {}).get("id", "")
        return await get_policy(db, doc_id)
    elif body.action == "save_policy":
        return await save_policy(db, PolicyData(**(body.data or {})))
    elif body.action == "get_reminders":
        return await get_reminders(db)
    elif body.action == "save_reminders":
        return await save_reminders(db, RemindersData(**(body.data or {})))
    elif body.action == "get_variables":
        return await get_variables(db)
    elif body.action == "save_variables":
        return await save_variables(db, body.data or {})
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")


async def request_otp(db, request, user_id: str, owner_id: str):
    if user_id != owner_id:
        raise HTTPException(status_code=403, detail="Only the bot owner can request an OTP")

    otp = str(secrets.randbelow(900000) + 100000)
    otp_hash = sha256(otp.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    await db["admin_otp"].update_one(
        {"_id": user_id},
        {"$set": {
            "otp_hash": otp_hash,
            "created_at": now,
            "expires_at": now + timedelta(minutes=OTP_TTL_MINUTES),
        }},
        upsert=True,
    )

    bot = request.app.state.bot
    try:
        user = bot.get_user(int(owner_id))
        if not user:
            user = await bot.fetch_user(int(owner_id))
        if user:
            await user.send(f"Your admin workspace OTP: **{otp}**\nThis code expires in {OTP_TTL_MINUTES} minutes.")
            logger.info(f"OTP sent to owner {owner_id}")
        else:
            logger.error(f"Could not find Discord user for owner {owner_id}")
            raise HTTPException(status_code=500, detail="Could not send OTP: owner not found")
    except Exception as e:
        logger.error(f"Failed to send OTP DM: {e}")
        raise HTTPException(status_code=500, detail="Could not send OTP via Discord DM")

    return {"sent": True}


async def verify_otp(db, user_id: str, data: dict):
    otp_attempt = str(data.get("otp", ""))
    otp_hash_attempt = sha256(otp_attempt.encode()).hexdigest()

    stored = await db["admin_otp"].find_one({"_id": user_id})
    if not stored:
        raise HTTPException(status_code=400, detail="No OTP requested. Please request an OTP first.")

    if stored.get("expires_at", datetime.now(timezone.utc)) < datetime.now(timezone.utc):
        await db["admin_otp"].delete_one({"_id": user_id})
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if stored["otp_hash"] != otp_hash_attempt:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    await db["admin_otp"].delete_one({"_id": user_id})

    now = datetime.now(timezone.utc)
    await db["admin_sessions"].update_one(
        {"_id": user_id},
        {"$set": {
            "created_at": now,
            "expires_at": now + timedelta(seconds=SESSION_TTL_SECONDS),
        }},
        upsert=True,
    )

    return {"verified": True, "session_ttl_seconds": SESSION_TTL_SECONDS}


async def revoke_session(db, user_id: str, data: dict):
    await db["admin_sessions"].delete_one({"_id": user_id})
    return {"revoked": True}


async def get_policy(db, doc_id: str):
    doc = await db["Self"].find_one({"_id": doc_id})
    if not doc:
        return {"content": "", "version": None}
    return {"content": doc.get("content", ""), "version": doc.get("version")}


async def save_policy(db, data: PolicyData):
    update = {"content": data.content, "updated": datetime.now(timezone.utc)}
    if data.version is not None:
        update["version"] = data.version
    await db["Self"].update_one(
        {"_id": data.id},
        {"$set": update},
        upsert=True
    )
    return {"status": "saved"}


async def get_reminders(db):
    doc = await db["config"].find_one({"_id": "reminders"})
    if not doc:
        return {"gifs": [], "texts": []}
    return {"gifs": doc.get("gifs", []), "texts": doc.get("texts", [])}


async def save_reminders(db, data: RemindersData):
    await db["config"].update_one(
        {"_id": "reminders"},
        {"$set": {"gifs": data.gifs, "texts": data.texts}},
        upsert=True
    )
    return {"status": "saved"}


def merge_defaults(raw: dict) -> dict:
    merged = {}
    for key, defaults in VARIABLES_DEFAULTS.items():
        val = raw.get(key)
        if isinstance(defaults, dict):
            if isinstance(val, dict):
                merged[key] = {**defaults, **val}
            else:
                merged[key] = dict(defaults)
        elif isinstance(defaults, list):
            merged[key] = val if isinstance(val, list) and len(val) > 0 else list(defaults)
        else:
            merged[key] = val if val is not None else defaults
    return merged


async def get_variables(db):
    doc = await db["config"].find_one({"_id": "variables"})
    raw = doc if doc else {}
    return merge_defaults(raw)


async def save_variables(db, data: dict):
    merged = merge_defaults(data)
    try:
        VariablesData(**merged)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid variable data: {e.errors()}")
    await db["config"].update_one(
        {"_id": "variables"},
        {"$set": {
            "drops": merged["drops"],
            "resources": merged["resources"],
            "activity_tiers": merged["activity_tiers"],
            "premium": merged["premium"],
            "level_up": merged["level_up"],
        }},
        upsert=True
    )
    _apply_to_config(merged)
    return {"status": "saved"}


def _apply_to_config(merged: dict):
    drops = merged.get("drops", {})
    resources = merged.get("resources", {})
    activity_tiers = merged.get("activity_tiers", [])
    premium = merged.get("premium", {})

    config.DROP_MEAN_TIME = drops.get("mean_time", config.DROP_MEAN_TIME)
    config.DROP_VARIANCE = drops.get("variance", config.DROP_VARIANCE)
    config.DROP_COLLECTION_TIME = drops.get("collection_time", config.DROP_COLLECTION_TIME)

    wood = resources.get("wood", {})
    config.RESOURCE_WOOD_BASE_MEAN = wood.get("base_mean", config.RESOURCE_WOOD_BASE_MEAN)
    config.RESOURCE_WOOD_BASE_DECAY = wood.get("base_decay", config.RESOURCE_WOOD_BASE_DECAY)
    config.RESOURCE_WOOD_DECAY_RATE = wood.get("decay_rate", config.RESOURCE_WOOD_DECAY_RATE)
    config.RESOURCE_WOOD_STD_DEV = wood.get("std_dev", config.RESOURCE_WOOD_STD_DEV)
    config.RESOURCE_WOOD_MIN = wood.get("min", config.RESOURCE_WOOD_MIN)

    iron = resources.get("iron", {})
    config.RESOURCE_IRON_BASE_MEAN = iron.get("base_mean", config.RESOURCE_IRON_BASE_MEAN)
    config.RESOURCE_IRON_BASE_DECAY = iron.get("base_decay", config.RESOURCE_IRON_BASE_DECAY)
    config.RESOURCE_IRON_DECAY_RATE = iron.get("decay_rate", config.RESOURCE_IRON_DECAY_RATE)
    config.RESOURCE_IRON_STD_DEV = iron.get("std_dev", config.RESOURCE_IRON_STD_DEV)
    config.RESOURCE_IRON_MIN = iron.get("min", config.RESOURCE_IRON_MIN)

    config.RESOURCE_VARIANCE_FACTOR_RATE = resources.get("variance_factor_rate", config.RESOURCE_VARIANCE_FACTOR_RATE)
    config.RESOURCE_VARIANCE_FACTOR_MIN = resources.get("variance_factor_min", config.RESOURCE_VARIANCE_FACTOR_MIN)

    if isinstance(activity_tiers, list) and len(activity_tiers) == 4:
        config.ACTIVITY_TIERS = [tuple(t) for t in activity_tiers]

    config.PREMIUM_COST = premium.get("cost", config.PREMIUM_COST)
    config.PREMIUM_TTL_DAYS = premium.get("ttl_days", config.PREMIUM_TTL_DAYS)
    config.PREMIUM_UNIT = premium.get("unit", config.PREMIUM_UNIT)

    level_up = merged.get("level_up", {})
    config.LEVEL_UP_XP_PER_MINUTE = level_up.get("xp_per_minute", config.LEVEL_UP_XP_PER_MINUTE)
    config.LEVEL_UP_XP_THRESHOLD = level_up.get("xp_threshold", config.LEVEL_UP_XP_THRESHOLD)
    config.LEVEL_UP_WOOD_BASE = level_up.get("wood_base", config.LEVEL_UP_WOOD_BASE)


async def load_variables_from_db(db):
    doc = await db["config"].find_one({"_id": "variables"})
    if doc:
        merged = merge_defaults(doc)
        _apply_to_config(merged)
