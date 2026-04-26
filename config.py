from os import getenv as _getenv

owner_id = 1490291458119307304

port = int(_getenv('FLASK_APP_PORT'))
host = _getenv('FLASK_DOMAIN')
dbName = _getenv('DB_NAME')
dbURI = _getenv("MONGODB_URI")
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

