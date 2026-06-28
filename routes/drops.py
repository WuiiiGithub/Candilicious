import jwt
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
    base_mean = 10 + vc_level * 2
    variance_factor = max(0.1, 1.0 - vc_xp * 0.001)
    variance = base_mean * 0.3 * variance_factor

    mean = base_mean * activity_mult
    spread = variance * activity_mult

    wood = max(1, int(random.uniform(mean - spread, mean + spread)))

    if random.random() < iron_chance:
        amount = max(1, int(wood * random.uniform(5, 10)))
        return "iron", amount

    return "wood", wood

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

    material, amount = calculate_reward(activity_mult, iron_chance, vc_level, vc_xp)

    await request.app.db["drops.claims"].insert_one({
        "drop_token": token,
        "user_id": user_id,
        "material": material,
        "amount": amount,
        "activity_str": act_str,
        "claimed_at": datetime.now(timezone.utc),
    })

    msg = f"You got {amount} 🪙 Wood!" if material == "wood" else f"✨ You got {amount} 🪙 **IRON**! Incredible!"
    return {
        "ok": 1,
        "material": material,
        "amount": amount,
        "activity": act_str,
        "message": msg,
    }
