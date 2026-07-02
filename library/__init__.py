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