import jwt
import math
import random
from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone
from pydantic import BaseModel
import config

router = APIRouter()

class ClaimRequest(BaseModel):
    pass

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

    wood = max(0, int(random.gauss(wood_mean * activity_mult, 10 * activity_mult * variance_factor)))
    iron = 0
    if random.random() < iron_chance:
        iron = max(0, int(random.gauss(iron_mean * activity_mult, 5 * activity_mult * variance_factor)))

    return wood, iron

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

    drop = await request.app.db["drops"].find_one({"token": token})
    if not drop:
        raise HTTPException(status_code=404, detail="Drop not found")

    existing = await request.app.db["drops.claims"].find_one({
        "drop_token": token, "user_id": user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="You already claimed this drop")

    bot = request.app.state.bot
    guild = bot.get_guild(int(drop["guild_id"]))
    if not guild:
        raise HTTPException(status_code=400, detail="Guild not found")

    member = guild.get_member(int(user_id))
    if not member or not member.voice:
        raise HTTPException(status_code=400, detail="You are not in a voice channel")

    if str(member.voice.channel.id) != drop["channel_id"]:
        raise HTTPException(status_code=400, detail="You are not in the study voice channel")

    act_str, activity_mult, iron_chance = get_activity_tier(member.voice)

    session = await request.app.db["sessions"].find_one({"_id": drop["channel_id"]})
    vc_level = session.get("vc_level", 1) if session else 1
    vc_xp = session.get("vc_xp", 0) if session else 0

    wood, iron = calculate_reward(activity_mult, iron_chance, vc_level, vc_xp)

    await request.app.db["drops.claims"].insert_one({
        "drop_token": token,
        "user_id": user_id,
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
