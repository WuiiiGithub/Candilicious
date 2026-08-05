from os import getenv as _getenv
from dotenv import load_dotenv as _load
import logging

_load()

logger = logging.getLogger(__name__)

OWNER_ID = 1490291458119307304

PORT = int(_getenv('WEBSITE_APP_PORT'))
HOST = _getenv('WEBSITE_DOMAIN')
DB_NAME = _getenv('DB_NAME')
MONGODB_URI = _getenv("MONGODB_URI")
DISCORD_CLIENT_ID = _getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = _getenv("DISCORD_CLIENT_SECRET")
WEBSITE_DOMAIN = _getenv("WEBSITE_DOMAIN").strip('/')
FRONTEND_DOMAIN=_getenv("FRONTEND_DOMAIN").strip('/')
SECRET_KEY=_getenv("SECRET_KEY")
CLOUDINARY_URL=_getenv("CLOUDINARY_URL")

if SECRET_KEY and len(SECRET_KEY) < 32:
    logger.warning("SECRET_KEY is shorter than 32 characters! Please use a key with at least 32 bytes.")

availableIn = {
    "guilds": [
        1491471841716605062
    ]
}

logging = {
    "style": ""
}

# Study Session
## Inactivity Thresholds
kickDelay = 1

## exception
exceptGrantDelay = 10

# Leaderboard
leaderboardLimit = 10

# Message Params
msgDelAfter=10
msgColor = 0x3498db

# Drops
DROP_MEAN_TIME = 30
DROP_VARIANCE = 0.5
DROP_COLLECTION_TIME = 30

# Resources (drop reward calculation)
RESOURCE_WOOD_BASE_MEAN = 60
RESOURCE_WOOD_BASE_DECAY = 35
RESOURCE_WOOD_DECAY_RATE = 0.1
RESOURCE_WOOD_STD_DEV = 10
RESOURCE_WOOD_MIN = 2
RESOURCE_IRON_BASE_MEAN = 20
RESOURCE_IRON_BASE_DECAY = 12
RESOURCE_IRON_DECAY_RATE = 0.1
RESOURCE_IRON_STD_DEV = 5
RESOURCE_IRON_MIN = 0
RESOURCE_VARIANCE_FACTOR_RATE = 0.001
RESOURCE_VARIANCE_FACTOR_MIN = 0.1

# Activity tiers
ACTIVITY_TIERS = [
    ("No Activity", 1.0, 0.00),
    ("Stream", 1.5, 0.03),
    ("Cam", 2.0, 0.08),
    ("Cam + Stream", 2.5, 0.15),
]

# Premium
PREMIUM_COST = 100
PREMIUM_TTL_DAYS = 7
PREMIUM_UNIT = "iron"

# Level Up
LEVEL_UP_XP_PER_MINUTE = 15
LEVEL_UP_XP_THRESHOLD = 5000
LEVEL_UP_WOOD_BASE = 100

# Streak DMs (daily study calls, streak break notifications)
ENABLE_STREAK_DMS = True if  _getenv('ENABLE_STREAK_DMS') else False

bot = None


