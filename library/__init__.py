from datetime import datetime, timedelta
from datetime import timezone
UTC = timezone.utc
import pymongo, os, discord
from asyncio import tasks, sleep
import config

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.DB_NAME]

serverCollection = db["servers"]
userCollection = db["users"]
boardsCollection = db["boards"]
exceptionCollection = db['exception']
recoveryCollection = db["recovery.log"]
recoverySnapshotsCollection = db["recovery.snapshots"]


def is_on_holiday(user_id: str) -> bool:
    doc = userCollection.find_one({"_id": user_id}, {"holiday_until": 1})
    if not doc:
        return False
    until = doc.get("holiday_until")
    if until is None:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return datetime.now(UTC) < until


def is_muted(user_id: str) -> bool:
    doc = userCollection.find_one({"_id": user_id}, {"muted": 1})
    if not doc:
        return False
    muted = doc.get("muted")
    if not muted:
        return False
    until = muted.get("until")
    if until is None:
        return True
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return datetime.now(UTC) < until