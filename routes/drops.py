import math
import random
import pymongo
from fastapi import APIRouter, Request, Depends, HTTPException
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
import config
from library import degrade, is_muted
from . import verify_token, limiter

router = APIRouter()

class ClaimRequest(BaseModel):
    screen_size: Optional[str] = None
    avg_pointer_speed: Optional[list[float]] = None
    avg_xyz_jerk: Optional[list[list[float]]] = None
    study_type: Optional[str] = None
    study_type_amount: Optional[str] = None
    respond_time: Optional[int] = None

def get_activity_tier(state):
    tiers = config.ACTIVITY_TIERS
    if state.self_video and state.self_stream:
        return tiers[3]
    elif state.self_video:
        return tiers[2]
    elif state.self_stream:
        return tiers[1]
    else:
        return tiers[0]

def calculate_reward(activity_mult: float, iron_chance: float, vc_level: int, vc_xp: int):
    wood_mean = config.RESOURCE_WOOD_BASE_MEAN - config.RESOURCE_WOOD_BASE_DECAY * math.exp(-config.RESOURCE_WOOD_DECAY_RATE * (vc_level - 1))
    iron_mean = config.RESOURCE_IRON_BASE_MEAN - config.RESOURCE_IRON_BASE_DECAY * math.exp(-config.RESOURCE_IRON_DECAY_RATE * (vc_level - 1))

    variance_factor = max(config.RESOURCE_VARIANCE_FACTOR_MIN, 1.0 - vc_xp * config.RESOURCE_VARIANCE_FACTOR_RATE)

    wood = max(config.RESOURCE_WOOD_MIN, int(random.gauss(wood_mean * activity_mult, config.RESOURCE_WOOD_STD_DEV * activity_mult * variance_factor)))
    iron = 0
    if random.random() < iron_chance:
        iron = max(config.RESOURCE_IRON_MIN, int(random.gauss(iron_mean * activity_mult, config.RESOURCE_IRON_STD_DEV * activity_mult * variance_factor)))

    return wood, iron

@router.get("/check/{token}")
async def check_drop(request: Request, token: str):
    claimed = await request.app.db["activity.drops"].find_one({"drop_token": token})
    return {"claimed": claimed is not None}

@router.post("/claim/{token}")
@limiter.limit("10/minute")
async def claim_drop(request: Request, token: str, body: ClaimRequest, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")

    drop = await request.app.db["drop.offers"].find_one({"token": token})
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found")

    session_id = drop.get("session_id") or drop.get("channel_id")
    guild_id = drop["guild_id"]

    session = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    actual_channel_id = session.get("channel_id", "")
    is_web_session = guild_id == "web" or actual_channel_id.startswith("w")

    bot = request.app.state.bot
    act_str, activity_mult, iron_chance = config.ACTIVITY_TIERS[0]

    if not is_web_session:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            raise HTTPException(status_code=400, detail="Guild not found")

        member = guild.get_member(int(user_id))
        if not member or not member.voice:
            raise HTTPException(status_code=400, detail="You are not in a voice channel")

        if str(member.voice.channel.id) != actual_channel_id:
            raise HTTPException(status_code=400, detail="You are not in the study voice channel")

        act_str, activity_mult, iron_chance = get_activity_tier(member.voice)

    vc_level = session.get("vc_level", 1)
    vc_xp = session.get("vc_xp", 0)

    wood, iron = calculate_reward(activity_mult, iron_chance, vc_level, vc_xp)

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    user_agent = request.headers.get("user-agent")

    drop_number = drop.get("drop_number", 1)
    user_claims_count = await request.app.db["activity.drops"].count_documents({
        "user_id": user_id,
        "session_id": session_id,
    })
    claim_rate = round((user_claims_count + 1) / max(drop_number, 1), 4)

    created_at = drop["created_at"]
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        respond_time = (datetime.now(timezone.utc) - created_at).total_seconds()
    else:
        respond_time = 0

    try:
        await request.app.db["activity.drops"].insert_one({
            "drop_token": token,
            "user_id": user_id,
            "guild_id": guild_id,
            "session_id": session_id,
            "respond_time": respond_time,
            "ip": ip,
            "user_agent": user_agent,
            "screen_size": body.screen_size,
            "avg_pointer_speed": body.avg_pointer_speed,
            "avg_xyz_jerk": body.avg_xyz_jerk,
            "study_type": body.study_type,
            "study_type_amount": body.study_type_amount,
            "claim_rate": claim_rate,
            "wood": wood,
            "iron": iron,
            "activity_str": act_str,
            "claimed_at": datetime.now(timezone.utc),
        })
    except pymongo.errors.DuplicateKeyError:
        raise HTTPException(status_code=400, detail="You already claimed this drop")

    rates_doc = await request.app.db["config"].find_one({"_id": "degradation_rates"})
    wood_rate = rates_doc.get("wood", 0.05) if rates_doc else 0.05
    iron_rate = rates_doc.get("iron", 0.03) if rates_doc else 0.03

    user_data = await request.app.db["users"].find_one({"_id": user_id})
    resources = (user_data or {}).get("economy", {}).get("resources", {})
    wood_data = resources.get("wood", {})
    iron_data = resources.get("iron", {})

    existing_wood, wood_dt = degrade.apply(wood_data.get("amount", 0), wood_data.get("degraded_at"), wood_rate)
    existing_iron, iron_dt = degrade.apply(iron_data.get("amount", 0), iron_data.get("degraded_at"), iron_rate)

    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {
            "economy.resources.wood.amount": existing_wood + wood,
            "economy.resources.wood.degraded_at": wood_dt,
            "economy.resources.iron.amount": existing_iron + iron,
            "economy.resources.iron.degraded_at": iron_dt,
        }},
        upsert=True,
    )

    if not is_web_session:
        channel = bot.get_channel(int(actual_channel_id))
        if channel:
            try:
                who = f"<@{user_id}>" if not is_muted(user_id) else user_id
                await channel.send(
                    content=f"\U0001f381 {who} collected the drop! +**{wood}** \U0001fab5 Wood +**{iron}** \U0001f529 Iron",
                    delete_after=config.DROP_COLLECTION_TIME,
                )
            except Exception:
                pass

    parts = []
    if wood > 0:
        parts.append(f"\U0001FAB5 \U0001FAB5 Wood: **{wood}**")
    if iron > 0:
        parts.append(f"\U0001F529 \U0001F529 Iron: **{iron}**")
    msg = " \u2022 ".join(parts) if parts else "Nothing this time..."

    return {
        "ok": 1,
        "wood": wood,
        "iron": iron,
        "activity": act_str,
        "message": msg,
    }
