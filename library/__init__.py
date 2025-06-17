from datetime import datetime, timedelta
from datetime import timezone
UTC = timezone.utc
import pymongo, os, discord
from asyncio import tasks, sleep

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))["Candilicious[Beta]"]

serverCollection = db["Servers"]
learnerCollection = db["Learners"]