import jwt
import math
import random
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
import config

router = APIRouter()

class ClaimRequest(BaseModel):
    screen_size: Optional[str] = None
    avg_pointer_speed: Optional[list[float]] = None
    avg_xyz_jerk: Optional[list[list[float]]] = None
    study_type: Optional[str] = None
    study_type_amount: Optional[str] = None
    respond_time: Optional[int] = None

ACTIVITY_TIERS = [
    ("No Activity", 1.0, 0.00),
    ("Stream", 1.5, 0.03),
    ("Cam", 2.0, 0.08),
    ("Cam + Stream", 2.5, 0.15),
]

def get_activity_tier(state):
    if state.self_video and state.self_stream:
        return ACTIVITY_TIERS[3]
    elif state.self_video:
        return ACTIVITY_TIERS[2]
    elif state.self_stream:
        return ACTIVITY_TIERS[1]
    else:
        return ACTIVITY_TIERS[0]

def calculate_reward(activity_mult: float, iron_chance: float, vc_level: int, vc_xp: int):
    wood_mean = 60 - 35 * math.exp(-0.1 * (vc_level - 1))
    iron_mean = 20 - 12 * math.exp(-0.1 * (vc_level - 1))

    variance_factor = max(0.1, 1.0 - vc_xp * 0.001)

    wood = max(2, int(random.gauss(wood_mean * activity_mult, 10 * activity_mult * variance_factor)))
    iron = 0
    if random.random() < iron_chance:
        iron = max(0, int(random.gauss(iron_mean * activity_mult, 5 * activity_mult * variance_factor)))

    return wood, iron

@router.get("/check/{token}")
async def check_drop(request: Request, token: str):
    claimed = await request.app.db["activity.drops"].find_one({"drop_token": token})
    return {"claimed": claimed is not None}

@router.post("/claim/{token}")
async def claim_drop(request: Request, token: str, body: ClaimRequest):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = jwt.decode(auth[7:], config.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")

    drop = await request.app.db["drop.offers"].find_one({"token": token})
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found")

    session_id = drop["channel_id"]
    guild_id = drop["guild_id"]

    existing = await request.app.db["activity.drops"].find_one({
        "drop_token": token, "user_id": user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="You already claimed this drop")

    bot = request.app.state.bot
    guild = bot.get_guild(int(guild_id))
    if not guild:
        raise HTTPException(status_code=400, detail="Guild not found")

    member = guild.get_member(int(user_id))
    if not member or not member.voice:
        raise HTTPException(status_code=400, detail="You are not in a voice channel")

    if str(member.voice.channel.id) != session_id:
        raise HTTPException(status_code=400, detail="You are not in the study voice channel")

    act_str, activity_mult, iron_chance = get_activity_tier(member.voice)

    session = await request.app.db["sessions"].find_one({"_id": session_id})
    vc_level = session.get("vc_level", 1) if session else 1
    vc_xp = session.get("vc_xp", 0) if session else 0

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

    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$inc": {"economy.wood": wood, "economy.iron": iron}},
        upsert=True,
    )

    bot = request.app.state.bot
    channel = bot.get_channel(int(session_id))
    if channel:
        try:
            await channel.send(
                content=f"\U0001f381 <@{user_id}> collected the drop! +**{wood}** \U0001fab5 Wood +**{iron}** \U0001f529 Iron",
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
