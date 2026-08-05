def default_avatar(user_id: str) -> str:
    return f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"


def extract_avatar_hash(avatar: str) -> str:
    """Extract a bare Discord avatar hash from any stored pfp value.

    Handles full CDN URLs (with or without a ?size= suffix), bare hashes, and
    hashes that already carry a file extension. Returns '' when nothing usable."""
    if not avatar:
        return ""
    if avatar.startswith(("https://", "http://", "data:")):
        tail = avatar.split("/")[-1].split("?")[0]
    else:
        tail = avatar
    if "." in tail:
        tail = ".".join(tail.split(".")[:-1])
    return tail


def build_avatar_url(user_id: str, pfp: str) -> str:
    """Build a canonical Discord avatar URL from a user id and a stored pfp value.

    `pfp` may be a full URL (returned as-is), a bare hash, or a hash that
    already carries an extension. Animated avatars (a_ prefix) get .gif."""
    if not pfp:
        return default_avatar(user_id)
    if pfp.startswith(("https://", "http://", "data:")):
        return pfp
    hash_ = extract_avatar_hash(pfp)
    if not hash_:
        return default_avatar(user_id)
    ext = "gif" if hash_.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{hash_}.{ext}"


def resolve_avatar_url(user_id: str, user_data: dict | None) -> str:
    """Best-available avatar URL for a stored user document.

    profile_pfp (custom upload / custom link) wins, then pfp, then the
    Discord default avatar."""
    if not user_data:
        return default_avatar(user_id)
    profile_pfp = user_data.get("profile_pfp")
    if profile_pfp:
        return profile_pfp
    return build_avatar_url(user_id, user_data.get("pfp") or "")
