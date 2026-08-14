"""Google Analytics 4 Data API client for the analytics hub.

The platform-level tiles (active users, new users, sessions, engagement) are
read straight from the GA4 property backing the site's Measurement ID
``G-NT1K27R0DW``. App-specific metrics (study time, leaderboard, per-server)
are not web-traffic events, so they keep coming from the database.

Configuration (``.env``):

* ``GA_PROPERTY_ID`` — the numeric GA4 property id (from Admin → Property
  settings; NOT the ``G-`` measurement string).
* ``GA_SERVICE_ACCOUNT`` — inline service-account JSON, OR
* ``GA_SERVICE_ACCOUNT_JSON`` — path to a service-account JSON file, OR
* ``GOOGLE_APPLICATION_CREDENTIALS`` — path to a service-account JSON file.

The service account needs the **Analytics Viewer** role on the GA4 property.
Auth uses a signed JWT (RS256, PyJWT) + OAuth token exchange via ``httpx`` —
no extra dependencies. Responses are cached in-process for
``_RESULT_TTL_SECONDS`` because the Data API has tight daily quotas.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import jwt

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
TOKEN_URL = "https://oauth2.googleapis.com/token"

_RESULT_TTL_SECONDS = 120
_token_cache = {"token": None, "expires": 0}
_result_cache = {}
_creds_cache = None


class GA4Error(Exception):
    """Raised when GA4 is misconfigured or the API rejects the request."""


def _load_credentials() -> Optional[dict]:
    global _creds_cache
    if _creds_cache is not None:
        return _creds_cache or None

    inline = os.getenv("GA_SERVICE_ACCOUNT")
    if inline:
        try:
            _creds_cache = json.loads(inline)
            return _creds_cache
        except ValueError:
            logger.warning("GA_SERVICE_ACCOUNT is not valid JSON")
            _creds_cache = {}
            return None

    for var in ("GA_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS"):
        path = os.getenv(var)
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _creds_cache = json.load(fh)
                return _creds_cache
        except (OSError, ValueError) as exc:
            logger.warning("Could not load service account from %s: %s", path, exc)
            _creds_cache = {}
            return None

    _creds_cache = {}
    return None


def _property_id() -> Optional[str]:
    value = os.getenv("GA_PROPERTY_ID", "").strip()
    return value or None


def is_configured() -> bool:
    return bool(_property_id() and _load_credentials())


async def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now + 60:
        return _token_cache["token"]

    creds = _load_credentials()
    if not creds:
        raise GA4Error("GA4 is not configured")

    now_ts = int(now)
    claims = {
        "iss": creds.get("client_email"),
        "scope": SCOPE,
        "aud": creds.get("token_uri") or TOKEN_URL,
        "iat": now_ts,
        "exp": now_ts + 3600,
    }
    assertion = jwt.encode(claims, creds.get("private_key"), algorithm="RS256")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            creds.get("token_uri") or TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = now + int(data.get("expires_in", 3600)) - 60
    return _token_cache["token"]


def _cache_key(kind: str, payload: dict) -> str:
    return f"{kind}|{json.dumps(payload, sort_keys=True, default=str)}"


def _cached(kind: str, payload: dict, result: dict) -> dict:
    key = _cache_key(kind, payload)
    _result_cache[key] = (time.time() + _RESULT_TTL_SECONDS, result)
    return result


def _from_cache(kind: str, payload: dict) -> Optional[dict]:
    key = _cache_key(kind, payload)
    hit = _result_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


async def _post(payload: dict, realtime: bool = False) -> dict:
    pid = _property_id()
    if not pid:
        raise GA4Error("GA_PROPERTY_ID is not set")
    cached = _from_cache("rt" if realtime else "report", payload)
    if cached is not None:
        return cached

    token = await _get_access_token()
    if realtime:
        url = f"{BASE_URL}/properties/{pid}:runRealtimeReport"
    else:
        url = f"{BASE_URL}/properties/{pid}:runReport"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        if resp.status_code == 429:
            raise GA4Error("GA4 Data API rate limit exceeded")
        if resp.status_code >= 400:
            logger.error("GA4 error %s: %s", resp.status_code, resp.text[:500])
            raise GA4Error(f"GA4 API error {resp.status_code}")
        data = resp.json()

    return _cached("rt" if realtime else "report", payload, data)


async def run_report(
    metrics: list[str],
    date_ranges: list[dict],
    dimensions: Optional[list[str]] = None,
) -> dict:
    """Run a GA4 ``runReport`` call. Returns the raw API response dict."""
    payload = {"dateRanges": date_ranges, "metrics": [{"name": m} for m in metrics]}
    if dimensions:
        payload["dimensions"] = [{"name": d} for d in dimensions]
    return await _post(payload, realtime=False)


async def run_realtime(metrics: list[str]) -> dict:
    """Run a GA4 ``runRealtimeReport`` call (last 30 minutes of activity)."""
    payload = {"metrics": [{"name": m} for m in metrics]}
    return await _post(payload, realtime=True)


def rows_to_dicts(resp: dict) -> list[dict]:
    """Flatten the raw response into [{dimensions:[...], metrics:[float,...]}]."""
    out = []
    for row in resp.get("rows", []):
        dims = [d.get("value", "") for d in row.get("dimensionValues", [])]
        vals = [float(m.get("value", 0)) for m in row.get("metricValues", [])]
        out.append({"dimensions": dims, "metrics": vals})
    return out
