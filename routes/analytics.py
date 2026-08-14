"""Analytics hub endpoints — Firebase-home-style overview for Candilicious.

Hybrid data sourcing (see ``ANALYTICS_API.md``):

* **Platform metrics** (active users, new users, sessions, engagement) are read
  from the Google Analytics 4 property via ``library.ga4`` whenever it is
  configured (``GA_PROPERTY_ID`` + a service account). When GA4 is unavailable
  they fall back to ``session.logs`` so the hub still works.
* **App-specific metrics** (study time, personal overview, leaderboard,
  per-server breakdown) are always computed from the database, because GA4 only
  stores web-traffic events.

Endpoints (prefix ``/api/analytics``):

* ``GET /metrics`` — which trend metrics are available and their data source.
* ``GET /overview`` — platform home tiles (GA-backed, DB fallback).
* ``GET /trend`` — current vs previous period (+ per-server peer band for DB
  metrics).
* ``GET /me`` — signed-in user's own trend + peer band + rank (DB).
* ``GET /users`` — leaderboard (DB).
* ``GET /servers`` — per-server comparison (DB).

Results are cached in-process for ``CACHE_TTL_SECONDS``; GA4 API responses are
cached inside ``library.ga4`` for 2 minutes to respect daily quotas.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from . import limiter, rate_limit_ip, verify_token
from .stats import _parse_iso
from library import ga4

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_TTL_SECONDS = 60
PERIODS = {"7d": 7, "14d": 14, "28d": 28}
DEFAULT_PERIOD = "28d"

# Trend metrics read from GA4 (web traffic).
GA_METRIC_INFO = {
    "active_users": ("Active users", "users", "activeUsers"),
    "new_users": ("New users", "users", "newUsers"),
    "sessions": ("Sessions", "sessions", "sessions"),
    "engagement": ("Engagement", "%", "engagementRate"),
}

# Trend metrics always computed from the database.
DB_METRIC_INFO = {
    "study_minutes": ("Study time", "min"),
    "study_hours": ("Study time", "hrs"),
}

LEADERBOARD_METRICS = {"study_minutes", "sessions", "active_days"}

_cache = {}


def _percentile(sorted_vals, p):
    """Linear-interpolated percentile of an ascending list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    k = (n - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _round(value, decimals=1):
    return round(value, decimals) if value is not None else 0


async def _aggregate(db, days_back):
    """One streaming pass over ``session.logs`` building every bucket the DB
    side of the hub needs, cached in-process for ``CACHE_TTL_SECONDS``."""
    now = datetime.now(timezone.utc)
    today = now.date()
    window_start = today - timedelta(days=days_back - 1)
    prev_start = today - timedelta(days=2 * days_back - 1)
    iso = today.isoformat()

    users_per_day = defaultdict(set)
    minutes_per_day = defaultdict(float)
    sessions_per_day = defaultdict(set)
    user_first_day = {}

    server_day = defaultdict(
        lambda: defaultdict(lambda: {"users": set(), "minutes": 0.0, "sessions": set()})
    )
    user_day_minutes = defaultdict(lambda: defaultdict(float))
    user_active_days = defaultdict(set)
    user_sessions = defaultdict(set)

    active_cur = set()
    active_prev = set()
    session_cur = set()
    session_prev = set()
    server_cur = defaultdict(set)
    server_prev = defaultdict(set)
    live_recent = set()

    seg_sum = 0.0
    seg_count = 0
    user_seg_sum = defaultdict(float)
    user_seg_count = defaultdict(int)

    cursor = db["session.logs"].find(
        {},
        {"user_id": 1, "guild_id": 1, "session_id": 1, "joined_at": 1, "left_at": 1},
    )
    async for doc in cursor:
        uid = doc.get("user_id")
        if not uid:
            continue
        joined = doc.get("joined_at") or {}
        start = _parse_iso(joined.get("time"))
        if start is None:
            continue
        end = _parse_iso(doc.get("left_at"))
        live = end is None
        if live:
            end = now
        elif end < start:
            end = start

        total = max(0.0, float(joined.get("total") or 0))
        gid = str(doc.get("guild_id") or "web")
        sid = str(doc.get("session_id") or "")

        end_date = end.date()
        if end_date < prev_start:
            continue

        if uid not in user_first_day or end_date < user_first_day[uid]:
            user_first_day[uid] = end_date

        if live or (now - end).total_seconds() <= 1800:
            live_recent.add(uid)

        days_ago = (today - end_date).days
        in_cur = end_date >= window_start
        in_prev = not in_cur

        if in_cur:
            d = end_date.isoformat()
            users_per_day[d].add(uid)
            minutes_per_day[d] += total
            if sid:
                sessions_per_day[d].add(sid)
                session_cur.add(sid)
            user_day_minutes[uid][d] += total
            user_active_days[uid].add(d)
            if sid:
                user_sessions[uid].add(sid)
            sd = server_day[gid][d]
            sd["users"].add(uid)
            sd["minutes"] += total
            if sid:
                sd["sessions"].add(sid)

            active_cur.add(uid)
            server_cur[gid].add(uid)
            seg_sum += total
            seg_count += 1
            user_seg_sum[uid] += total
            user_seg_count[uid] += 1
        else:
            active_prev.add(uid)
            server_prev[gid].add(uid)
            if sid:
                session_prev.add(sid)

    return {
        "now": now,
        "today": today,
        "today_iso": iso,
        "window_start": window_start,
        "prev_start": prev_start,
        "days_back": days_back,
        "users_per_day": users_per_day,
        "minutes_per_day": minutes_per_day,
        "sessions_per_day": sessions_per_day,
        "server_day": server_day,
        "user_day_minutes": user_day_minutes,
        "user_active_days": user_active_days,
        "user_sessions": user_sessions,
        "user_first_day": user_first_day,
        "active_cur": active_cur,
        "active_prev": active_prev,
        "session_cur": session_cur,
        "session_prev": session_prev,
        "server_cur": server_cur,
        "server_prev": server_prev,
        "live_recent": live_recent,
        "seg_sum": seg_sum,
        "seg_count": seg_count,
        "user_seg_sum": user_seg_sum,
        "user_seg_count": user_seg_count,
    }


async def _cached_aggregate(db, days_back):
    key = ("agg", days_back)
    now = datetime.now(timezone.utc).timestamp()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    result = await _aggregate(db, days_back)
    _cache[key] = (now + CACHE_TTL_SECONDS, result)
    return result


def _day_values(agg, day, metric):
    iso = day.isoformat()
    if metric == "active_users":
        return len(agg["users_per_day"].get(iso, ()))
    if metric == "new_users":
        return sum(1 for _, fd in agg["user_first_day"].items() if fd.isoformat() == iso)
    if metric == "sessions":
        return len(agg["sessions_per_day"].get(iso, ()))
    if metric == "study_minutes":
        return _round(agg["minutes_per_day"].get(iso, 0.0) / 60)
    if metric == "study_hours":
        return _round(agg["minutes_per_day"].get(iso, 0.0) / 3600)
    return 0


def _server_value(server_day, iso, metric):
    if metric == "active_users":
        return len(server_day["users"])
    if metric == "sessions":
        return len(server_day["sessions"])
    if metric == "study_minutes":
        return _round(server_day["minutes"] / 60)
    if metric == "study_hours":
        return _round(server_day["minutes"] / 3600)
    return 0


def _user_value(agg, uid, metric, window_days):
    if metric == "study_minutes":
        return _round(sum(agg["user_day_minutes"][uid].values()) / 60)
    if metric == "sessions":
        return len(agg["user_sessions"].get(uid, ()))
    if metric == "active_days":
        return len(agg["user_active_days"].get(uid, ()))
    return 0


def _span_days(agg):
    days_back = agg["days_back"]
    today = agg["today"]
    current = [today - timedelta(days=i) for i in range(days_back - 1, -1, -1)]
    previous = [today - timedelta(days=days_back + i) for i in range(days_back - 1, -1, -1)]
    return current, previous


async def _load_user_map(db, user_ids):
    """Resolve a {user_id: {username, display_name, avatar_url}} map."""
    from library.avatars import resolve_avatar_url

    mapping = {}
    ids = [u for u in user_ids if u]
    if not ids:
        return mapping
    cursor = db["users"].find(
        {"_id": {"$in": ids}},
        {"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1},
    )
    async for doc in cursor:
        uid = doc["_id"]
        username = doc.get("name") or uid
        mapping[uid] = {
            "username": username,
            "display_name": doc.get("display_name") or username,
            "avatar_url": resolve_avatar_url(uid, doc),
        }
    return mapping


# ─── GA4-backed helpers ────────────────────────────────────────────────────────

async def _ga_overview() -> dict:
    """Platform tiles straight from GA4 (active users, new users, sessions)."""
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    week_ago = (today - timedelta(days=6)).isoformat()
    month_ago = (today - timedelta(days=27)).isoformat()

    resp = await ga4.run_report(
        metrics=[
            "active1dayUsers",
            "active7dayUsers",
            "active28dayUsers",
            "newUsers",
            "sessions",
            "engagedSessions",
        ],
        date_ranges=[{"startDate": month_ago, "endDate": today_iso}],
    )
    rows = ga4.rows_to_dicts(resp)
    r = rows[0]["metrics"] if rows else [0] * 6
    active_today, active_7d, active_28d, new_users, sessions_28d, engaged_28d = r

    sessions_7d = 0
    sessions_today = 0
    for day_iso in (week_ago, today_iso):
        resp_d = await ga4.run_report(
            metrics=["sessions"],
            date_ranges=[{"startDate": day_iso, "endDate": today_iso}],
        )
        rows_d = ga4.rows_to_dicts(resp_d)
        val = rows_d[0]["metrics"][0] if rows_d else 0
        if day_iso == week_ago:
            sessions_7d = val
        else:
            sessions_today = val

    live = 0
    try:
        rt = await ga4.run_realtime(["activeUsers"])
        rows_rt = ga4.rows_to_dicts(rt)
        live = int(rows_rt[0]["metrics"][0]) if rows_rt else 0
    except ga4.GA4Error:
        pass

    returning = ((active_28d - new_users) / active_28d) if active_28d else 0.0
    engagement_rate = (engaged_28d / sessions_28d * 100) if sessions_28d else 0.0

    return {
        "active_users": {
            "last_30m": int(live),
            "today": int(active_today),
            "last_7d": int(active_7d),
            "last_28d": int(active_28d),
        },
        "sessions": {
            "today": int(sessions_today),
            "last_7d": int(sessions_7d),
            "last_28d": int(sessions_28d),
        },
        "new_users_28d": int(new_users),
        "returning_users_28d": _round(returning),
        "engagement_rate_28d": _round(engagement_rate),
    }


async def _ga_trend(metric: str, period: str, days_back: int) -> dict:
    """Daily series from GA4 for a GA-backed metric (no peer band)."""
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    prev_start = (today - timedelta(days=2 * days_back - 1)).isoformat()

    ga_metric = GA_METRIC_INFO[metric][2]
    resp = await ga4.run_report(
        metrics=[ga_metric],
        dimensions=["date"],
        date_ranges=[{"startDate": prev_start, "endDate": today_iso}],
    )

    per_day = {}
    for row in ga4.rows_to_dicts(resp):
        key = row["dimensions"][0]
        per_day[key] = row["metrics"][0]
    factor = 100.0 if metric == "engagement" else 1.0

    def build(days):
        pts = []
        for d in days:
            val = per_day.get(d.strftime("%Y%m%d"), 0.0)
            if metric == "engagement":
                val = min(val * factor, 100.0)
            pts.append({"date": d.isoformat(), "value": _round(val)})
        return pts

    current_days = [today - timedelta(days=i) for i in range(days_back - 1, -1, -1)]
    previous_days = [today - timedelta(days=days_back + i) for i in range(days_back - 1, -1, -1)]
    current = build(current_days)
    previous = build(previous_days)

    def total(pts):
        s = sum(p["value"] for p in pts)
        return _round(s / len(pts)) if metric == "engagement" and pts else _round(s)

    cur_total = total(current)
    prev_total = total(previous)
    delta_pct = _round((cur_total - prev_total) / prev_total * 100) if prev_total else 0.0

    return {
        "ok": 1,
        "metric": metric,
        "period": period,
        "label": GA_METRIC_INFO[metric][0],
        "value_unit": GA_METRIC_INFO[metric][1],
        "source": "ga",
        "current": current,
        "previous": previous,
        "peer": None,
        "totals": {"current": cur_total, "previous": prev_total, "peer_median": None},
        "delta_pct": delta_pct,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/metrics")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_metrics(request: Request, payload: dict = Depends(verify_token)):
    ga = ga4.is_configured()
    metrics = [
        {"key": "active_users", "label": "Active users", "unit": "users", "source": "ga" if ga else "db"},
        {"key": "new_users", "label": "New users", "unit": "users", "source": "ga" if ga else "db"},
        {"key": "sessions", "label": "Sessions", "unit": "sessions", "source": "ga" if ga else "db"},
    ]
    if ga:
        metrics.append({"key": "engagement", "label": "Engagement", "unit": "%", "source": "ga"})
    metrics += [
        {"key": "study_minutes", "label": "Study time", "unit": "min", "source": "db"},
        {"key": "study_hours", "label": "Study time", "unit": "hrs", "source": "db"},
    ]
    return {"ok": 1, "ga_configured": ga, "periods": ["7d", "14d", "28d"], "metrics": metrics}


@router.get("/overview")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_overview(request: Request, payload: dict = Depends(verify_token)):
    db = request.app.db
    agg = await _cached_aggregate(db, PERIODS[DEFAULT_PERIOD])

    users_7d = set()
    sessions_7d = set()
    for i in range(7):
        d = (agg["today"] - timedelta(days=i)).isoformat()
        users_7d |= agg["users_per_day"].get(d, set())
        sessions_7d |= agg["sessions_per_day"].get(d, set())

    users_28d = agg["active_cur"]
    users_prev = agg["active_prev"]
    returning = len(users_28d & users_prev) / len(users_28d) if users_28d else 0.0

    new_users_28d = sum(1 for _, fd in agg["user_first_day"].items() if fd >= agg["window_start"])
    sessions_28d = len(agg["session_cur"])
    avg_session_min = (agg["seg_sum"] / agg["seg_count"] / 60) if agg["seg_count"] else 0.0

    overview = {
        "active_users": {
            "last_30m": len(agg["live_recent"]),
            "today": len(agg["users_per_day"].get(agg["today_iso"], ())),
            "last_7d": len(users_7d),
            "last_28d": len(users_28d),
        },
        "sessions": {
            "today": len(agg["sessions_per_day"].get(agg["today_iso"], ())),
            "last_7d": len(sessions_7d),
            "last_28d": sessions_28d,
        },
        "engagement": {
            "total_study_hours_28d": _round(agg["seg_sum"] / 3600),
            "avg_session_minutes_28d": _round(avg_session_min),
            "returning_users_28d": _round(returning),
            "new_users_28d": new_users_28d,
            "engagement_rate_28d": None,
        },
        "source": "db",
    }

    if ga4.is_configured():
        try:
            ga = await _ga_overview()
            overview["active_users"] = ga["active_users"]
            overview["sessions"] = ga["sessions"]
            overview["engagement"]["new_users_28d"] = ga["new_users_28d"]
            overview["engagement"]["returning_users_28d"] = ga["returning_users_28d"]
            overview["engagement"]["engagement_rate_28d"] = ga["engagement_rate_28d"]
            overview["source"] = "ga"
        except ga4.GA4Error as exc:
            logger.warning("GA4 unavailable, overview falls back to DB: %s", exc)

    return {"ok": 1, "overview": overview}


@router.get("/trend")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_trend(
    request: Request,
    metric: str = "active_users",
    period: str = DEFAULT_PERIOD,
    payload: dict = Depends(verify_token),
):
    if metric not in GA_METRIC_INFO and metric not in DB_METRIC_INFO:
        raise HTTPException(status_code=400, detail="Invalid metric")
    days_back = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])

    if metric in GA_METRIC_INFO:
        if metric == "engagement" and not ga4.is_configured():
            raise HTTPException(status_code=400, detail="engagement requires GA4 to be configured")
        if ga4.is_configured():
            try:
                return await _ga_trend(metric, period, days_back)
            except ga4.GA4Error as exc:
                logger.warning("GA4 trend unavailable for %s, falling back to DB: %s", metric, exc)

    agg = await _cached_aggregate(request.app.db, days_back)

    current_days, previous_days = _span_days(agg)
    current = [
        {"date": d.isoformat(), "value": _day_values(agg, d, metric)} for d in current_days
    ]
    previous = [
        {"date": d.isoformat(), "value": _day_values(agg, d, metric)} for d in previous_days
    ]

    server_ids = sorted(agg["server_day"].keys())
    peer_median, peer_low, peer_high = [], [], []
    if server_ids:
        for d in current_days:
            iso = d.isoformat()
            vals = [
                _server_value(agg["server_day"][gid][iso], iso, metric)
                for gid in server_ids
            ]
            if not vals:
                peer_median.append({"date": iso, "value": 0})
                peer_low.append({"date": iso, "value": 0})
                peer_high.append({"date": iso, "value": 0})
                continue
            s = sorted(vals)
            peer_median.append({"date": iso, "value": _round(_percentile(s, 50))})
            peer_low.append({"date": iso, "value": _round(_percentile(s, 25))})
            peer_high.append({"date": iso, "value": _round(_percentile(s, 75))})
    peer = (
        {"median": peer_median, "low": peer_low, "high": peer_high} if server_ids else None
    )

    def _union_total(series):
        return len(set().union(*(agg["users_per_day"].get(p["date"], set()) for p in series)))

    def _session_union(series):
        return len(set().union(*(agg["sessions_per_day"].get(p["date"], set()) for p in series)))

    if metric == "active_users":
        cur_total = _union_total(current)
        prev_total = _union_total(previous)
    elif metric == "new_users":
        cur_total = sum(
            1 for fd in agg["user_first_day"].values() if agg["window_start"] <= fd <= agg["today"]
        )
        prev_total = sum(
            1 for fd in agg["user_first_day"].values()
            if agg["prev_start"] <= fd < agg["window_start"]
        )
    elif metric == "sessions":
        cur_total = _session_union(current)
        prev_total = _session_union(previous)
    else:
        cur_total = _round(sum(p["value"] for p in current))
        prev_total = _round(sum(p["value"] for p in previous))
    delta_pct = _round((cur_total - prev_total) / prev_total * 100) if prev_total else 0.0

    label, unit = DB_METRIC_INFO.get(metric, GA_METRIC_INFO.get(metric, ("", "")))

    return {
        "ok": 1,
        "metric": metric,
        "period": period,
        "label": label,
        "value_unit": unit,
        "source": "db",
        "current": current,
        "previous": previous,
        "peer": peer,
        "totals": {
            "current": cur_total,
            "previous": prev_total,
            "peer_median": _round(_percentile(
                sorted(len(agg["server_cur"][gid]) for gid in agg["server_cur"]), 50
            )) if agg["server_cur"] else None,
        },
        "delta_pct": delta_pct,
    }


@router.get("/me")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_me(request: Request, payload: dict = Depends(verify_token)):
    uid = payload.get("sub")
    agg = await _cached_aggregate(request.app.db, PERIODS[DEFAULT_PERIOD])
    days_back = agg["days_back"]
    current_days, previous_days = _span_days(agg)

    uid_days = agg["user_day_minutes"].get(uid, {})
    uid_active = agg["user_active_days"].get(uid, set())

    def _minutes_window(days):
        return sum(
            uid_days.get(d.isoformat(), 0.0) for d in days
        ) / 60

    minutes_7d = _minutes_window(current_days[-7:])
    minutes_28d = _minutes_window(current_days)
    today_minutes = uid_days.get(agg["today_iso"], 0.0) / 60

    active_7d = sum(1 for d in current_days[-7:] if d.isoformat() in uid_active)
    active_28d = len(uid_active)

    avg_session_min = (
        agg["user_seg_sum"].get(uid, 0.0) / max(1, agg["user_seg_count"].get(uid, 0)) / 60
    )

    # Rank across every tracked user (study minutes, current window).
    values = [
        (sum(v.values()) / 60, u)
        for u, v in agg["user_day_minutes"].items()
    ]
    values.sort(key=lambda x: x[0], reverse=True)
    total_users = len(values)
    rank = next((i + 1 for i, (v, u) in enumerate(values) if u == uid), total_users)
    percentile = round((1 - (rank - 1) / max(1, total_users)) * 100, 1)

    trend_cur = [
        {"date": d.isoformat(), "value": _round(uid_days.get(d.isoformat(), 0.0) / 60)}
        for d in current_days
    ]
    trend_prev = [
        {"date": d.isoformat(), "value": _round(uid_days.get(d.isoformat(), 0.0) / 60)}
        for d in previous_days
    ]

    peer_median, peer_low, peer_high = [], [], []
    for d in current_days:
        iso = d.isoformat()
        vals = [
            agg["user_day_minutes"][u].get(iso, 0.0) / 60
            for u in agg["users_per_day"].get(iso, set())
        ]
        if not vals:
            peer_median.append({"date": iso, "value": 0})
            peer_low.append({"date": iso, "value": 0})
            peer_high.append({"date": iso, "value": 0})
            continue
        s = sorted(vals)
        peer_median.append({"date": iso, "value": _round(_percentile(s, 50))})
        peer_low.append({"date": iso, "value": _round(_percentile(s, 25))})
        peer_high.append({"date": iso, "value": _round(_percentile(s, 75))})

    return {
        "ok": 1,
        "me": {
            "study_minutes": {
                "today": _round(today_minutes),
                "last_7d": _round(minutes_7d),
                "last_28d": _round(minutes_28d),
            },
            "active_days": {"last_7d": active_7d, "last_28d": active_28d},
            "sessions_28d": len(agg["user_sessions"].get(uid, set())),
            "avg_session_minutes_28d": _round(avg_session_min),
            "rank": rank,
            "total_users": total_users,
            "percentile": percentile,
            "trend": {
                "current": trend_cur,
                "previous": trend_prev,
                "peer_median": peer_median,
                "peer_low": peer_low,
                "peer_high": peer_high,
            },
        },
    }


@router.get("/users")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_users(
    request: Request,
    metric: str = "study_minutes",
    period: str = DEFAULT_PERIOD,
    limit: int = 10,
    payload: dict = Depends(verify_token),
):
    if metric not in LEADERBOARD_METRICS:
        raise HTTPException(status_code=400, detail="Invalid metric")
    limit = max(1, min(100, limit))
    days_back = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])
    agg = await _cached_aggregate(request.app.db, days_back)
    uid = payload.get("sub")

    ranked = [
        (uid, _user_value(agg, uid, metric, days_back)) for uid in agg["user_day_minutes"]
    ]
    ranked.sort(key=lambda x: x[1], reverse=True)
    total_users = len(ranked)

    # Ties share a rank.
    ranked_with_rank = []
    prev_val = None
    prev_rank = 0
    for i, (u, v) in enumerate(ranked):
        rank = prev_rank if v == prev_val else i + 1
        ranked_with_rank.append((rank, u, v))
        prev_val = v
        prev_rank = rank

    me_entry = next((r for r in ranked_with_rank if r[1] == uid), None)
    top = ranked_with_rank[:limit]

    user_map = await _load_user_map(request.app.db, [r[1] for r in top])

    leaderboard = []
    for rank, u, v in top:
        info = user_map.get(u, {})
        leaderboard.append({
            "rank": rank,
            "user_id": u,
            "username": info.get("username", u),
            "display_name": info.get("display_name", u),
            "avatar_url": info.get("avatar_url"),
            "value": v,
            "percentile": _round((1 - (rank - 1) / max(1, total_users)) * 100, 1),
        })

    return {
        "ok": 1,
        "metric": metric,
        "period": period,
        "label": "Study time" if metric == "study_minutes" else ("Sessions" if metric == "sessions" else "Active days"),
        "value_unit": "min" if metric == "study_minutes" else ("sessions" if metric == "sessions" else "days"),
        "total_users": total_users,
        "me": {"rank": me_entry[0], "value": me_entry[2]} if me_entry else None,
        "leaderboard": leaderboard,
    }


@router.get("/servers")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_servers(
    request: Request,
    period: str = DEFAULT_PERIOD,
    payload: dict = Depends(verify_token),
):
    days_back = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])
    agg = await _cached_aggregate(request.app.db, days_back)
    current_days, _previous_days = _span_days(agg)
    bot = getattr(request.app.state, "bot", None)

    servers = []
    for gid in sorted(agg["server_day"].keys()):
        day_map = agg["server_day"][gid]
        cur_users = agg["server_cur"].get(gid, set())
        prev_users = agg["server_prev"].get(gid, set())
        session_ids = set()
        minutes = 0.0
        active_30d = len(cur_users)
        for iso, sd in day_map.items():
            minutes += sd["minutes"]
            session_ids |= sd["sessions"]

        delta = (
            _round((active_30d - len(prev_users)) / len(prev_users) * 100)
            if prev_users
            else 0.0
        )

        trend = []
        for d in current_days:
            iso = d.isoformat()
            sd = day_map.get(iso)
            trend.append({
                "date": iso,
                "active_users": len(sd["users"]) if sd else 0,
                "study_minutes": _round(sd["minutes"] / 60) if sd else 0,
            })

        guild = None
        if bot:
            try:
                guild = bot.get_guild(int(gid))
            except (TypeError, ValueError):
                guild = None

        servers.append({
            "server_id": gid,
            "name": guild.name if guild else gid,
            "icon": str(guild.icon.url) if guild and guild.icon else None,
            "member_count": guild.member_count if guild else None,
            "active_users_28d": active_30d,
            "study_minutes_28d": _round(minutes / 60),
            "sessions_28d": len(session_ids),
            "avg_session_minutes_28d": _round(minutes / max(1, len(session_ids)) / 60),
            "delta_active_pct": delta,
            "trend": trend,
        })

    servers.sort(key=lambda s: s["active_users_28d"], reverse=True)

    return {"ok": 1, "period": period, "servers": servers}
