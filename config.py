from os import getenv as _getenv

port = _getenv('FLASK_DOMAIN').split(':')[1]
dbName = _getenv('DB_NAME')
availableIn = {
    "guilds": [1354101256662286397, 1218819398974963752]
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

