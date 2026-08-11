from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Depends

from . import verify_token, limiter, rate_limit_ip

router = APIRouter()

DAILY_LOOKBACK_DAYS = 56
WEEKS_LOOKBACK = 8


def _parse_iso(value):
    """Parse an ISO datetime that may be stored as a string, datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _hour_overlap(start: datetime, end: datetime, hour: datetime) -> float:
    """Seconds of [start, end) that fall inside the given UTC hour bucket."""
    hour_end = hour + timedelta(hours=1)
    overlap_start = max(start, hour)
    overlap_end = min(end, hour_end)
    if overlap_end <= overlap_start:
        return 0.0
    return (overlap_end - overlap_start).total_seconds()


@router.get("/me")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_my_stats(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")

    now = datetime.now(timezone.utc)
    today = now.date()
    days = [
        today - timedelta(days=offset)
        for offset in range(DAILY_LOOKBACK_DAYS - 1, -1, -1)
    ]

    # ── Daily study seconds (attributed to the day the segment ended, which is
    #    how the streak counts "studied on day X") ───────────────────────────
    daily = {
        d.isoformat(): {"date": d.isoformat(), "seconds": 0, "cam": 0, "ss": 0, "noact": 0}
        for d in days
    }
    split = {"cam": 0, "ss": 0, "noact": 0, "total": 0}
    hourly = defaultdict(float)
    hourly_seen = defaultdict(int)

    logs = request.app.db["session.logs"]
    cursor = logs.find({"user_id": user_id})
    async for doc in cursor:
        joined = doc.get("joined_at") or {}
        seg_start = _parse_iso(joined.get("time"))
        if seg_start is None:
            continue
        seg_end = _parse_iso(doc.get("left_at")) or now
        if seg_end < seg_start:
            seg_end = seg_start

        secs_total = max(0.0, float(joined.get("total") or 0))
        secs_cam = max(0.0, float(joined.get("cam") or 0))
        secs_ss = max(0.0, float(joined.get("ss") or 0))
        secs_noact = max(0.0, float(joined.get("noact") or 0))

        split["cam"] += secs_cam
        split["ss"] += secs_ss
        split["noact"] += secs_noact
        split["total"] += secs_total

        end_date = seg_end.date()
        if end_date >= days[0]:
            bucket = daily.get(end_date.isoformat())
            if bucket is not None:
                bucket["seconds"] += secs_total
                bucket["cam"] += secs_cam
                bucket["ss"] += secs_ss
                bucket["noact"] += secs_noact

        # ── Hourly spread ────────────────────────────────────────────────────
        # Segments can be REUSED within 60s of leaving: `time` is reset to the
        # last rejoin while `total` keeps accumulating across the reuse. The
        # stored span then lies about where the study happened. Reconstruct an
        # effective window that fits the accumulated seconds:
        #   eff_start = end - total   (never earlier than the recorded start)
        eff_start = max(seg_start, seg_end - timedelta(seconds=secs_total))
        span_secs = max(1.0, (seg_end - eff_start).total_seconds())
        bucket = eff_start.replace(minute=0, second=0, microsecond=0)
        while bucket < seg_end:
            overlap = _hour_overlap(eff_start, seg_end, bucket)
            if overlap > 0:
                ratio = overlap / span_secs
                hourly[bucket.hour] += secs_total * ratio
                hourly_seen[bucket.hour] += 1
            bucket += timedelta(hours=1)

    daily_list = list(daily.values())

    # Exclusive activity mix: cam+ss overlap is counted in BOTH fields, so
    # cam+ss+noact can exceed the real total. Recover the overlap so the four
    # slices sum exactly to `total`.
    both = max(0.0, split["cam"] + split["ss"] + split["noact"] - split["total"])
    cam_only = max(0.0, split["cam"] - both)
    ss_only = max(0.0, split["ss"] - both)

    total_recent = sum(d["seconds"] for d in daily_list)
    week_seconds = sum(d["seconds"] for d in daily_list[-7:])
    month_seconds = sum(d["seconds"] for d in daily_list[-30:])
    today_seconds = daily_list[-1]["seconds"]
    best_day = max(daily_list, key=lambda d: d["seconds"])
    days_studied = sum(1 for d in daily_list if d["seconds"] > 0)
    week_days_active = sum(1 for d in daily_list[-7:] if d["seconds"] > 0)
    month_days_active = sum(1 for d in daily_list[-30:] if d["seconds"] > 0)

    # ── Weekly totals (calendar weeks, Monday-start) ────────────────────────
    weekly_map = {
        (today - timedelta(days=today.weekday() + 7 * i)).isoformat(): 0
        for i in range(WEEKS_LOOKBACK)
    }
    for d in daily_list:
        day = datetime.strptime(d["date"], "%Y-%m-%d").date()
        monday = (day - timedelta(days=day.weekday())).isoformat()
        if monday in weekly_map:
            weekly_map[monday] += d["seconds"]
    weekly_list = [{"date": k, "seconds": v} for k, v in sorted(weekly_map.items())]

    # ── Streak from the users document ──────────────────────────────────────
    user_doc = await request.app.db["users"].find_one(
        {"_id": user_id},
        {"streak": 1, "last_study_time": 1, "last_study_date": 1, "servers": 1},
    )
    user_doc = user_doc or {}

    streak = int(user_doc.get("streak") or 0)
    last_study_raw = user_doc.get("last_study_time") or user_doc.get("last_study_date")
    last_study = _parse_iso(last_study_raw)
    last_study_date = last_study.date().isoformat() if last_study else None
    studied_today = last_study_date == today.isoformat()
    studied_yesterday = last_study_date == (today - timedelta(days=1)).isoformat()
    streak_active = streak > 0 and (studied_today or studied_yesterday)

    all_time_seconds = 0
    for guild_data in (user_doc.get("servers") or {}).values():
        if isinstance(guild_data, dict):
            try:
                all_time_seconds += max(0, int(guild_data.get("time") or 0))
            except (TypeError, ValueError):
                pass

    hourly_list = [
        {"hour": h, "seconds": round(hourly.get(h, 0), 1), "segments": hourly_seen.get(h, 0)}
        for h in range(24)
    ]

    return {
        "ok": 1,
        "stats": {
            "streak": {
                "current": streak,
                "active": streak_active,
                "studied_today": studied_today,
                "last_study": last_study.isoformat() if last_study else None,
            },
            "totals": {
                "all_time_seconds": all_time_seconds,
                "today_seconds": today_seconds,
                "week_seconds": week_seconds,
                "month_seconds": month_seconds,
                "days_studied": days_studied,
                "week_days_active": week_days_active,
                "month_days_active": month_days_active,
                "avg_per_day_seconds": round(total_recent / DAILY_LOOKBACK_DAYS, 1),
                "avg_active_day_seconds": round(total_recent / max(1, days_studied), 1),
                "best_day_seconds": best_day["seconds"],
                "best_day_date": best_day["date"],
            },
            "split": {
                "cam": round(cam_only, 1),
                "ss": round(ss_only, 1),
                "both": round(both, 1),
                "noact": round(split["noact"], 1),
                "total": round(split["total"], 1),
            },
            "daily": daily_list,
            "weekly": weekly_list,
            "hourly": hourly_list,
        },
    }
