from datetime import datetime, timezone


def apply(amount: int, degraded_at, daily_rate: float) -> tuple[int, datetime]:
    now = datetime.now(timezone.utc)
    if amount <= 0 or not degraded_at:
        return amount, now
    if not isinstance(degraded_at, datetime):
        return amount, now
    if degraded_at.tzinfo is None:
        degraded_at = degraded_at.replace(tzinfo=timezone.utc)
    delta = (now - degraded_at).total_seconds()
    if delta <= 0:
        return amount, now
    days = delta / 86400.0
    remaining = amount * (1 - daily_rate) ** days
    new_amount = max(0, round(remaining))
    return new_amount, now
