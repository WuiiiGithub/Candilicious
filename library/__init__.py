from datetime import datetime, timedelta, UTC
import pymongo, os, discord
from asyncio import tasks, sleep

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))["Candilicious[Beta]"]

serverCollection = db["Servers"]
learnerCollection = db["Learners"]