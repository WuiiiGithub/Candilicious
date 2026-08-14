import math
import random
import pymongo
from fastapi import APIRouter, Request, Depends, HTTPException
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
import config
from library import degrade, is_muted
from library.ga_mp import track_event
from . import verify_token, limiter, rate_limit_ip, rate_limit_user
from .sessions import _is_live_guild_member

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
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def check_drop(request: Request, token: str):
    claimed = await request.app.db["activity.drops"].find_one({"drop_token": token})
    return {"claimed": claimed is not None}


@router.get("/active/{session_id}")
@limiter.limit("120/minute", key_func=rate_limit_ip)
@limiter.limit("300/hour", key_func=rate_limit_user)
async def get_active_drop(
    request: Request,
    session_id: str,
    payload: dict = Depends(verify_token),
):
    """Return the currently-live drop for a session, if any.

    The `drop_created` SSE event is fire-and-forget, so a client that was
    suspended / away (mobile background tabs, etc.) never sees it. This lets
    the frontend catch up by asking "is there a live drop right now?" on
    session load, stream reconnect, or focus return."""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    session = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    members_raw = session.get("members", {})
    is_member = user_id in members_raw
    guild_id = session.get("guild_id", "")
    if not is_member and guild_id != "web":
        in_guild = payload.get("in_guild", False)
        if not await _is_live_guild_member(request, guild_id, user_id, bool(in_guild)):
            raise HTTPException(status_code=403, detail="You must be in the guild to view this session")

    now = datetime.now(timezone.utc)
    offer = await request.app.db["drop.offers"].find_one(
        {"session_id": session_id, "expire_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if not offer:
        return {"ok": 1, "drop": None}

    already_claimed = await request.app.db["activity.drops"].find_one(
        {"drop_token": offer["token"], "user_id": user_id},
    )
    if already_claimed:
        return {"ok": 1, "drop": None}

    def _iso(value) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return str(value)

    return {
        "ok": 1,
        "drop": {
            "token": offer["token"],
            "drop_number": offer.get("drop_number", 0),
            "created_at": _iso(offer.get("created_at")),
            "expire_at": _iso(offer.get("expire_at")),
        },
    }


@router.post("/claim/{token}")
@limiter.limit("10/minute", key_func=rate_limit_ip)
@limiter.limit("30/hour", key_func=rate_limit_user)
async def claim_drop(request: Request, token: str, body: ClaimRequest, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")

    drop = await request.app.db["drop.offers"].find_one({"token": token})
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found")

    expire_at = drop.get("expire_at")
    if isinstance(expire_at, datetime):
        if expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
        if expire_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Drop has expired")

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

    track_event("drop_claimed", {
        "session_id": session_id,
        "guild_id": guild_id,
        "study_type": body.study_type,
        "wood": int(wood),
        "iron": int(iron),
    }, user_id=user_id)

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
        if not channel:
            try:
                channel = await bot.fetch_channel(int(actual_channel_id))
            except Exception:
                channel = None
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
