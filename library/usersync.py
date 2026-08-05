import config
from datetime import datetime, timezone

SYNC_TTL_HOURS = 24


def discord_user_doc(user):
    """Build an upsert doc for the users collection from a discord User/Member."""
    name = getattr(user, "name", None) or "Unknown"
    display_name = getattr(user, "display_name", None) or getattr(user, "global_name", None) or name
    avatar = getattr(user, "avatar", None)
    pfp = avatar.key if avatar else None
    return {
        "name": name,
        "display_name": display_name,
        "pfp": pfp,
    }


DEFAULT_BIO = "Hey! I'm a new user who just joined recently :)"


def needs_discord_sync(user_data: dict | None, max_age_hours: int = SYNC_TTL_HOURS) -> bool:
    """Whether a stored user doc is missing Discord details or is stale.

    Avoids hammering the Discord API: we only re-sync when we have no usable
    name/pfp at all, or the last sync is older than `max_age_hours`."""
    if not user_data:
        return True
    if not user_data.get("name") or not user_data.get("pfp"):
        return True
    synced_at = user_data.get("discord_synced_at")
    if not synced_at:
        return True
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - synced_at).total_seconds() > max_age_hours * 3600


async def sync_user_from_discord(bot, user_collection, user_id: str, force: bool = False) -> dict | None:
    """Fetch a user from Discord (if needed) and store their data in the users
    collection. Returns the stored document, or None.

    Efficient by default: skips the Discord API call entirely when the stored
    doc already has fresh name/avatar data. Pass `force=True` to always fetch."""
    if bot is None:
        return None
    existing = await user_collection.find_one({"_id": user_id})
    if not force and existing and not needs_discord_sync(existing):
        return existing
    discord_data = await fetch_discord_user(bot, user_id)
    if not discord_data:
        return existing
    await user_collection.update_one(
        {"_id": user_id},
        {"$set": {
            "name": discord_data["name"],
            "display_name": discord_data["display_name"],
            "pfp": discord_data.get("pfp"),
            "in_guild": discord_data.get("in_guild", False),
            "discord_synced_at": datetime.now(timezone.utc),
            "last_seen": datetime.now(timezone.utc),
        }, "$setOnInsert": {"bio": DEFAULT_BIO}},
        upsert=True,
    )
    return await user_collection.find_one({"_id": user_id})


def sync_member_from_discord(user_collection, user_id: str, guild=None, force: bool = False) -> dict | None:
    """Efficiently store a Discord user's details without an API call.

    Uses an already-cached guild member when available (free, no API call) and
    only fetches from Discord if the stored doc is missing/stale. This is the
    cheap path to call from frequent interactions (commands, buttons, VC joins).
    """
    existing = user_collection.find_one({"_id": user_id})
    if not force and existing and not needs_discord_sync(existing):
        return existing

    member = None
    if guild is not None:
        try:
            member = guild.get_member(int(user_id))
        except (ValueError, TypeError):
            member = None

    if member is not None:
        doc = discord_user_doc(member)
        user_collection.update_one(
            {"_id": user_id},
            {"$set": {
                "name": doc["name"],
                "display_name": doc["display_name"],
                "pfp": doc.get("pfp"),
                "in_guild": True,
                "discord_synced_at": datetime.now(timezone.utc),
                "last_seen": datetime.now(timezone.utc),
            }, "$setOnInsert": {"bio": DEFAULT_BIO}},
            upsert=True,
        )
        return user_collection.find_one({"_id": user_id})
    return existing


async def fetch_discord_user(bot, user_id):
    """Return normalized Discord profile data for a user, or None on failure.

    Prefers a guild member lookup (gives the server nickname) and falls back
    to a plain user fetch. Never raises.
    """
    try:
        uid = int(user_id)

        member = None
        for gid in config.availableIn.get("guilds", []):
            guild = bot.get_guild(int(gid))
            if not guild:
                continue
            try:
                member = guild.get_member(uid)
                if member is None:
                    member = await guild.fetch_member(uid)
            except Exception:
                member = None
            if member:
                break

        if member is not None:
            name = member.name
            display_name = member.display_name or member.global_name or name
            avatar = member.avatar
            in_guild = True
        else:
            user = await bot.fetch_user(uid)
            name = user.name
            display_name = user.display_name or user.global_name or name
            avatar = user.avatar
            in_guild = False

        data = {
            "name": name,
            "display_name": display_name,
            "in_guild": in_guild,
        }
        if avatar:
            data["pfp"] = avatar.key
            data["avatar_url"] = str(avatar.with_format("png").url)
        else:
            data["avatar_url"] = f"https://cdn.discordapp.com/embed/avatars/{uid % 5}.png"
        return data
    except Exception:
        return None
