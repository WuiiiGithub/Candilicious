from os import getenv as _getenv
from dotenv import load_dotenv as _load
_load()

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

if SECRET_KEY and len(SECRET_KEY) < 32:
    print("\033[93m" + "!" * 50 + "\033[0m")
    print("\033[93mWARNING: SECRET_KEY is shorter than 32 characters!\033[0m")
    print("\033[93mFor security, please use a key with at least 32 bytes (e.g., secrets.token_hex(32)).\033[0m")
    print("\033[93m" + "!" * 50 + "\033[0m")

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
DROP_COLLECTION_TIME = 30
msgColor = 0x3498db

bot = None


