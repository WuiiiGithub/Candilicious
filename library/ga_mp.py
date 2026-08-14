"""GA4 Measurement Protocol client — server-side events straight into Google Analytics.

Backend operations (study sessions, drops, tasks, projects) report themselves to the
GA4 property via the Measurement Protocol instead of being re-aggregated from the
database for the analytics hub. Every event is tagged with ``app_name=candilicious``
and ``platform=backend`` so reports can be filtered.

Environment (see ``ANALYTICS_API.md``):

* ``GA_MEASUREMENT_ID`` — the ``G-`` measurement id of the web data stream.
* ``GA_API_SECRET`` — Measurement Protocol API secret (Admin → Data streams →
  Measurement Protocol API secrets).
* ``GA_TRACKING_ENABLED`` — ``true``/``1`` to turn server-side tracking on.
* ``GA_MP_DEBUG`` — ``true``/``1`` to hit the validation endpoint
  ``/debug/mp/collect`` and log the validation result instead of the live one.

Usage is fire-and-forget: ``track_event(...)`` schedules a background task and never
raises, so tracking can never break a study session or an HTTP request.
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MP_URL = "https://www.google-analytics.com/mp/collect"
MP_DEBUG_URL = "https://www.google-analytics.com/debug/mp/collect"
APP_NAME = "candilicious"

# Max events per request (Measurement Protocol limit is 25).
MAX_BATCH = 25


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    return _env_bool("GA_TRACKING_ENABLED") and bool(
        os.getenv("GA_API_SECRET") and os.getenv("GA_MEASUREMENT_ID")
    )


def _client_id(user_id: Optional[str]) -> str:
    """A stable, namespaced client id so server events don't collide with the
    browser's numeric client ids in the same web stream."""
    if user_id:
        return f"backend_{user_id}"
    return "backend_platform"


def _clean_param(value):
    """Measurement Protocol accepts strings and numbers only."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, dict)):
        # GA4 flattens nested objects itself with "_" separators; for plain
        # arrays we just keep the JSON string.
        import json as _json

        return _json.dumps(value, default=str)[:100]
    return str(value)[:100]


def _sanitize_params(params: dict) -> dict:
    out = {}
    for key, value in (params or {}).items():
        safe_key = str(key).replace("-", "_")[:40]
        if not safe_key:
            continue
        out[safe_key] = _clean_param(value)
    return out


def _event_payload(name: str, params: dict, user_id: Optional[str]) -> dict:
    payload = {
        "client_id": _client_id(user_id),
        "events": [
            {
                "name": name[:40].replace("-", "_"),
                "params": {
                    "app_name": APP_NAME,
                    "platform": "backend",
                    **_sanitize_params(params),
                },
            }
        ],
    }
    if user_id:
        payload["user_id"] = str(user_id)
    return payload


async def _send(name: str, params: dict, user_id: Optional[str], attempts: int = 2) -> None:
    measurement_id = os.getenv("GA_MEASUREMENT_ID")
    api_secret = os.getenv("GA_API_SECRET")
    if not (measurement_id and api_secret):
        return

    url = MP_DEBUG_URL if _env_bool("GA_MP_DEBUG") else MP_URL
    payload = _event_payload(name, params, user_id)

    last_error = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    params={"api_secret": api_secret, "measurement_id": measurement_id},
                    json=payload,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "GA4 MP error %s for %s: %s", resp.status_code, name, resp.text[:300]
                    )
                    return
                if _env_bool("GA_MP_DEBUG"):
                    validation = resp.json().get("validationMessages", [])
                    if validation:
                        logger.info("GA4 MP validation %s: %s", name, validation)
                    else:
                        logger.info("GA4 MP validation %s: OK", name)
                return
        except Exception as exc:  # noqa: BLE001 — network blips must not bubble up
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.5)

    logger.debug("GA4 MP failed to send %s: %s", name, last_error)


def track_event(
    name: str,
    params: Optional[dict] = None,
    *,
    user_id: Optional[str] = None,
) -> None:
    """Fire-and-forget: schedule an async Measurement Protocol send.

    Safe to call from sync or async code; never raises."""
    if not is_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("GA4 MP: no running loop, dropping event %s", name)
        return
    loop.create_task(_send(name, params or {}, user_id))


async def track_event_async(
    name: str,
    params: Optional[dict] = None,
    *,
    user_id: Optional[str] = None,
) -> None:
    """Awaitable variant for async endpoints that want to await the send."""
    if not is_enabled():
        return
    await _send(name, params or {}, user_id)
