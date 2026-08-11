"""
GIF URL helpers for reminder images.

Reminders render a random image/GIF via ``embed.set_image``. Discord only
renders direct media URLs (gif/png/jpg/webp), so URLs that come from page
links, proxies or with query strings need to be normalized before they are
stored and used. This module centralizes that normalization/repair logic so
every entry point (Discord context menu, web admin workspace, cache refresh)
uses the same pipeline.
"""
import re
from urllib.parse import unquote, urlsplit, urlunsplit

# Known content hosts that Discord can render directly.
_IMAGE_EXT = re.compile(r"\.(gif|gifv|webp|png|jpe?g|apng)(\?|#|$)", re.I)
_TENOR_VIEW = re.compile(r"tenor\.com/view/", re.I)
_TENOR_MEDIA = re.compile(r"media\.tenor\.com", re.I)
_DISCORD_PROXY = re.compile(r"(?:images|media)-ext\d?\.discordapp\.net/external/", re.I)
_DISCORD_CDN = re.compile(r"(?:media|images)\.discord(app)?\.net", re.I)

# og:image extraction for tenor page links.
_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_OG_IMAGE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Candilicious-Bot/1.0)",
}


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def _unwrap_discord_proxy(url: str) -> str:
    """Discord's external proxy stores the real URL percent-encoded after
    ``/external/<token>/``. Unescape it so we can get back the original media."""
    match = re.search(r"/external/[^/]+/(.*)$", url)
    if not match:
        return url
    inner = unquote(match.group(1))
    if inner.startswith("http://") or inner.startswith("https://"):
        return inner
    return url


def is_usable_image_url(url: str) -> bool:
    """Checks the URL shape is something Discord can render as an embed image."""
    if not url:
        return False
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.netloc or "").lower()
    if _DISCORD_CDN.search(host) and not _DISCORD_PROXY.search(host):
        return True
    if _TENOR_MEDIA.search(host):
        return True
    if _IMAGE_EXT.search(parts.path):
        return True
    return False


def fix_gif_url(url: str):
    """Synchronous, best-effort normalization of a GIF URL.

    Returns a repaired URL, or ``None`` when the URL is unusable / unfixable
    without a network call. Tenor ``tenor.com/view/...`` page links cannot be
    fixed here (they need an async page fetch for the real media URL) — they
    are returned unchanged so :func:`resolve_gif_url` can handle them later.
    """
    if not url:
        return None
    url = url.strip().strip("<>").strip()
    if not url.startswith(("http://", "https://")):
        return None

    url = _unwrap_discord_proxy(url)

    # Tenor page links need an async fetch to resolve — leave them intact so
    # the async resolver (and the caller) can still pick them up.
    if _TENOR_VIEW.search(url):
        return url

    if _TENOR_MEDIA.search(url) or is_usable_image_url(url):
        # Strip query params — tenor media links often carry tracking keys
        # that break Discord's image proxy.
        return _strip_query(url)

    return None


async def resolve_gif_url(url: str, client=None):
    """Asynchronously resolve a GIF URL to a Discord-renderable media URL.

    Handles ``tenor.com/view/...`` page links by extracting the ``og:image``
    meta tag. Returns ``None`` if the URL cannot be resolved.
    """
    if not url:
        return None
    url = url.strip().strip("<>").strip()
    if not url.startswith(("http://", "https://")):
        return None

    url = _unwrap_discord_proxy(url)

    if _TENOR_VIEW.search(url):
        try:
            import httpx

            close_client = client is None
            async_client = client or httpx.AsyncClient(
                headers=_DEFAULT_HEADERS,
                timeout=10.0,
                follow_redirects=True,
            )
            try:
                resp = await async_client.get(url)
                if resp.status_code == 200:
                    match = _OG_IMAGE.search(resp.text) or _OG_IMAGE_ALT.search(resp.text)
                    if match:
                        resolved = fix_gif_url(match.group(1))
                        if resolved:
                            return resolved
            finally:
                if close_client:
                    await async_client.aclose()
        except Exception:
            pass
        return None

    return fix_gif_url(url)


async def repair_reminder_gifs(gif_collection, urls=None, client=None):
    """Repair a list of stored GIF URLs in-place and persist the fixed list.

    ``gif_collection`` is a pymongo collection (the ``config`` collection).
    Returns a summary dict with the repaired count and the final list.
    """
    if urls is None:
        doc = gif_collection.find_one({"_id": "reminders"}) if gif_collection else None
        urls = (doc or {}).get("gifs", [])

    fixed = []
    repaired_count = 0
    for raw in urls:
        if not isinstance(raw, str):
            continue
        resolved = await resolve_gif_url(raw, client=client)
        if resolved is None or not is_usable_image_url(resolved):
            continue
        if resolved != raw.strip().strip("<>").strip():
            repaired_count += 1
        fixed.append(resolved)

    if gif_collection is not None:
        try:
            gif_collection.update_one(
                {"_id": "reminders"},
                {"$set": {"gifs": fixed}},
                upsert=True,
            )
        except Exception:
            pass

    return {"repaired": repaired_count, "total": len(urls), "gifs": fixed}
