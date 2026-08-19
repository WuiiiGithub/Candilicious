"""Lightweight per-IP abuse guard.

Tracks request rates with sliding windows, logs suspicious activity to
/logs/abuse/, and auto-bans IPs that exceed sustained thresholds.

Design:
- Per-IP counters in a dict: ip -> deque of (timestamp, path_category)
- Sliding window check on every request
- Ban list persisted to /logs/abuse/banned.json (loaded once at startup)
- Logs: /logs/abuse/YYYY-MM-DD.log
- Response: 403 for banned IPs, 429 for burst-spike IPs

Thresholds (tuned for a study bot with ~100 concurrent users):
  AUTH_BURST   = 30 req/10s  on /auth/* paths   → immediate temp block 60s
  AUTH_SUSTAIN = 120 req/min on /auth/* paths   → ban 1h
  API_BURST    = 60 req/10s  on any path        → immediate temp block 30s
  API_SUSTAIN  = 300 req/min on any path        → ban 15min
"""

import json
import os
import time
import logging
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger("abuse")

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "abuse"
_BANNED_FILE = _LOG_DIR / "banned.json"

# ── thresholds ──────────────────────────────────────────────────────
AUTH_BURST = 30          # requests in 10s window on /auth/*
AUTH_BURST_WINDOW = 10   # seconds
AUTH_SUSTAIN = 120       # requests in 60s window on /auth/*
AUTH_SUSTAIN_WINDOW = 60

API_BURST = 60           # requests in 10s window on any path
API_BURST_WINDOW = 10
API_SUSTAIN = 300        # requests in 60s window on any path
API_SUSTAIN_WINDOW = 60

# ── ban durations (seconds) ─────────────────────────────────────────
BAN_BURST_DURATION = 60
BAN_SUSTAIN_DURATION = 3600     # 1 hour
BAN_REPEAT_ESCALATION = [3600, 7200, 86400]  # escalating bans

# ── internal state ──────────────────────────────────────────────────
_ip_windows: dict[str, deque] = {}
_banned: dict[str, float] = {}   # ip -> unban_timestamp (0 = permanent)
_temp_blocked: dict[str, float] = {}  # ip -> unban_timestamp


def _load_bans():
    """Load persisted ban list from disk (called once at import)."""
    try:
        if _BANNED_FILE.exists():
            with open(_BANNED_FILE) as f:
                data = json.load(f)
            _banned.update({k: float(v) for k, v in data.items() if v > time.time()})
            # clean expired on load
            expired = [k for k, v in _banned.items() if v < time.time() and v > 0]
            for k in expired:
                _banned.pop(k, None)
    except Exception:
        logger.exception("Failed to load ban list")


def _save_bans():
    """Persist ban list to disk (called on every ban/unban)."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Only save non-expired permanent bans
        active = {k: v for k, v in _banned.items() if v == 0 or v > time.time()}
        with open(_BANNED_FILE, "w") as f:
            json.dump(active, f, indent=2)
    except Exception:
        logger.exception("Failed to save ban list")


def _log_event(ip: str, event: str, details: str = ""):
    """Append a line to today's abuse log file."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = _LOG_DIR / f"{today}.log"
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"[{ts}] {event} ip={ip}"
        if details:
            line += f" {details}"
        with open(log_file, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _path_category(path: str) -> str:
    """Classify a path into a category."""
    if path.startswith("/api/auth"):
        return "auth"
    if path.startswith("/api/sessions"):
        return "sessions"
    if path.startswith("/api/drops"):
        return "drops"
    return "api"


def _prune_window(window: deque, now: float, max_age: float):
    """Remove entries older than max_age from the front of a deque."""
    cutoff = now - max_age
    while window and window[0][0] < cutoff:
        window.popleft()


def _ban_ip(ip: str, duration: float, reason: str):
    """Ban an IP for a duration (0 = permanent)."""
    now = time.time()
    unban_at = 0 if duration == 0 else now + duration
    _banned[ip] = unban_at

    # Escalate repeat offenders
    prev_bans = sum(1 for v in _banned.values() if v != 0 and v < now)
    if prev_bans >= len(BAN_REPEAT_ESCALATION):
        _banned[ip] = 0  # permanent
        _log_event(ip, "BAN_PERMANENT", f"reason={reason} repeat_offender")
    else:
        _log_event(ip, "BAN", f"duration={int(duration)}s reason={reason}")
    _save_bans()


def _unban_check(ip: str) -> bool:
    """Returns True if IP is currently banned."""
    unban_at = _banned.get(ip)
    if unban_at is None:
        return False
    if unban_at == 0:
        return True  # permanent ban
    if time.time() >= unban_at:
        _banned.pop(ip, None)
        _log_event(ip, "UNBAN", "expired")
        _save_bans()
        return False
    return True


def _temp_block_check(ip: str) -> bool:
    """Check if IP is in a temp block."""
    unban_at = _temp_blocked.get(ip)
    if unban_at is None:
        return False
    if time.time() >= unban_at:
        _temp_blocked.pop(ip, None)
        return False
    return True


class AbuseGuard:
    """ASGI middleware that tracks per-IP request rates and auto-bans abusers.

    Placement: add AFTER OriginGuard (outermost) and BEFORE SecurityHeaders.
    Request flow: OriginGuard → AbuseGuard → SecurityHeaders → CORS → routes
    """

    def __init__(self, app):
        self.app = app
        _load_bans()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        # Skip non-API paths (static files, health checks)
        if not path.startswith("/api"):
            return await self.app(scope, receive, send)

        # Resolve IP
        headers = dict(
            (k.decode("latin-1").lower(), v.decode("latin-1"))
            for k, v in (scope.get("headers") or [])
        )
        ip = headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not ip:
            ip = headers.get("host", "unknown")

        # ── permanent ban check ─────────────────────────────────────
        if _unban_check(ip):
            body = b'{"detail":"Your IP has been banned for abuse."}'
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # ── temp block check ────────────────────────────────────────
        if _temp_block_check(ip):
            body = b'{"detail":"Too many requests. Please wait."}'
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # ── rate tracking ───────────────────────────────────────────
        now = time.time()
        cat = _path_category(path)

        if ip not in _ip_windows:
            _ip_windows[ip] = deque()
        window = _ip_windows[ip]
        window.append((now, cat))

        # Check auth burst (10s window)
        if cat == "auth":
            _prune_window(window, now, AUTH_BURST_WINDOW)
            auth_count = sum(1 for _, c in window if c == "auth")
            if auth_count > AUTH_BURST:
                _log_event(ip, "AUTH_BURST", f"count={auth_count}/{AUTH_BURST_WINDOW}s path={path}")
                _temp_blocked[ip] = now + BAN_BURST_DURATION
                _log_event(ip, "TEMP_BLOCK", f"duration={BAN_BURST_DURATION}s")
                body = b'{"detail":"Rate limit exceeded. Please wait."}'
                await send({
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

            # Check auth sustain (60s window)
            _prune_window(window, now, AUTH_SUSTAIN_WINDOW)
            auth_count_60 = sum(1 for _, c in window if c == "auth")
            if auth_count_60 > AUTH_SUSTAIN:
                _ban_ip(ip, BAN_SUSTAIN_DURATION, f"auth_sustain_{auth_count_60}req/60s")
                body = b'{"detail":"Banned for sustained abuse."}'
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

        # Check API burst (10s window)
        _prune_window(window, now, API_BURST_WINDOW)
        total_10s = len(window)
        if total_10s > API_BURST:
            _log_event(ip, "API_BURST", f"count={total_10s}/{API_BURST_WINDOW}s path={path}")
            _temp_blocked[ip] = now + BAN_BURST_DURATION
            _log_event(ip, "TEMP_BLOCK", f"duration={BAN_BURST_DURATION}s")
            body = b'{"detail":"Rate limit exceeded. Please wait."}'
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # Check API sustain (60s window)
        _prune_window(window, now, API_SUSTAIN_WINDOW)
        total_60s = len(window)
        if total_60s > API_SUSTAIN:
            _ban_ip(ip, BAN_SUSTAIN_DURATION, f"api_sustain_{total_60s}req/60s")
            body = b'{"detail":"Banned for sustained abuse."}'
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        # ── periodic cleanup of stale IPs ───────────────────────────
        # Only clean every ~1000 requests to avoid O(n) on every request
        if len(_ip_windows) > 200 and len(_ip_windows) % 100 == 0:
            stale_cutoff = now - API_SUSTAIN_WINDOW
            stale = [k for k, v in _ip_windows.items()
                     if not v or v[-1][0] < stale_cutoff]
            for k in stale:
                _ip_windows.pop(k, None)

        return await self.app(scope, receive, send)


def ban_ip_permanent(ip: str, reason: str = "manual"):
    """Manually ban an IP permanently (callable from admin endpoints or bot)."""
    _ban_ip(ip, 0, reason)


def unban_ip(ip: str):
    """Manually unban an IP."""
    _banned.pop(ip, None)
    _log_event(ip, "UNBAN", "manual")
    _save_bans()


def get_banned_ips() -> dict[str, float]:
    """Return current ban list."""
    _unban_check_all()
    return dict(_banned)


def get_stats() -> dict:
    """Return current tracking stats for monitoring."""
    _unban_check_all()
    return {
        "tracked_ips": len(_ip_windows),
        "banned_ips": len(_banned),
        "temp_blocked": len(_temp_blocked),
    }


def _unban_check_all():
    """Clean expired bans."""
    now = time.time()
    expired = [k for k, v in _banned.items() if v != 0 and v < now]
    for k in expired:
        _banned.pop(k, None)
        _log_event(k, "UNBAN", "expired")
    if expired:
        _save_bans()
