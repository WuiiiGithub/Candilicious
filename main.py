import os, sys
import asyncio
import discord
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from discord.ext import commands
import uvicorn, config
from library.logging import SystemLogger, CogLogger
from motor.motor_asyncio import AsyncIOMotorClient
import routes 
from routes import (
    boards,
    drops,
    logs,
    projects,
    servers,
    tasks,
    users,
    auth,
    workspace,
)
from routes import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from pymongo import ASCENDING
from pymongo.errors import (
    ServerSelectionTimeoutError,
    ConnectionFailure,
    OperationFailure,
)

argLen = len(sys.argv)

# Flags
## Setup Flags
isVpnSetup = False
isNgrokSetup = False

# setups
if argLen > 1:
    cmdLineArgs = sys.args[1:]
    if "vpn" in cmdLineArgs:
        isVpnSetup = True
        import setup_vpn
    if "ngrok" in cmdLineArgs:
        isNgrokSetup = True

filename = __name__.title()
sysLog = SystemLogger(filename=filename)

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # start with
    sysLog.process(
        status_code=0, 
        message="Waiting", 
        details="Connecting to MongoDB..."
    )
    try:
        app.mongodb_client = AsyncIOMotorClient(
            MONGODB_URI, 
            serverSelectionTimeoutMS=5000
        )
        app.db = app.mongodb_client[config.DB_NAME]
        app.db.command("ping")
        sysLog.complete(
            status_code=100,
            message="Connected",
            details=f"Successfully established connection to MongoDB database: {config.DB_NAME}",
        )
        if isNgrokSetup:
            from pyngrok import ngrok, conf
            
            NGROK_AUTH_TOKEN = str(os.getenv("NGROK_AUTH_TOKEN"))
            ngrok.set_auth_token(NGROK_AUTH_TOKEN)
            public_url = ngrok.connect(config.port).public_url
            fast_api_url = os.getenv("FASTAPI_DOMAIN")
            if (
                fast_api_url == None 
                or fast_api_url == "" 
                or "://localhost:" in str(fast_api_url)
            ):
                os.environ["FASTAPI_DOMAIN"] = public_url
                fast_api_url = public_url

        await app.db["oauth_pending_states"].create_index(
            [("createdAt", ASCENDING)], 
            expireAfterSeconds=600
        )

        try:
            await app.db["drop.offers"].drop_index("created_at_1")
        except OperationFailure:
            pass
        await app.db["drop.offers"].create_index(
            [("created_at", ASCENDING)],
            expireAfterSeconds=3600
        )

    except (
        ServerSelectionTimeoutError, 
        ConnectionFailure, 
        OperationFailure
    ) as e:
        sysLog.error(
            status_code=-100,
            message="Error",
            details=f"Could not connect to MongoDB. Please check connection URI.\nError: {e}",
        )
        sysLog.send("Startup Error")
        sys.exit(1)
    except Exception as e:
        sysLog.error(
            status_code=-100,
            message="Error",
            details=f"An unexpected error occurred during database connection:\n{e}",
        )
        sysLog.send("Startup Error")
        sys.exit(1)

    yield

    # stop with
    print("...", "=" * 50, sep="\n")
    app.mongodb_client.close()
    if isNgrokSetup:
        ngrok.kill()
    if isVpnSetup:
        setup_vpn.shut_vpn()
    stopLog = CogLogger(filename=filename)
    stopLog.log_important(
        "Shutdown",
        status_code=0,
        details="The application has been stopped.",
    )
    print("=" * 50)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_DOMAIN], 
   allow_credentials=True,
   allow_methods=["*"],  
    allow_headers=["*"],  
)
# Bot Setup
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    application_id=DISCORD_CLIENT_ID,
)

@bot.event
async def on_ready():
    log = SystemLogger(filename=filename)
    log.complete(
        status_code=100,
        message="Ready",
        details=f"Discord bot has logged in as {bot.user} ({bot.user.id})",
    )

    guild_ids = config.availableIn.get("guilds", [])
    for g_id in guild_ids:
        try:
            guild = discord.Object(id=g_id)
            await bot.tree.sync(guild=guild)
            log.process(
                status_code=75,
                message="Synced",
                details=f"Synced application commands for guild: {g_id}",
            )
        except Exception as e:
            log.error(
                status_code=-75,
                message="Sync Fail",
                details=f"Failed to sync commands for guild {g_id}:\n{e}",
            )

    log.complete(
        status_code=100,
        message="Executed",
        details="Successfully synced application commands for all configured guilds.",
    )
    log.send("Bot Events")

app.state.bot = bot
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
bot.userNetworkConnection = {}

@app.get("/ping")
async def ping():
    return {"status": "ok"}

# Include the modular routes
app.include_router(
    router=routes.router,
    prefix="/api"
)
app.include_router(
    router=boards.router,
    prefix="/api/projects/boards",
    tags=["boards"]
)
app.include_router(
    router=tasks.router,
    prefix="/api/projects/boards/tasks",
    tags=["tasks"]
)
app.include_router(
    router=projects.router,
    prefix="/api/projects",
    tags=["projects"]
)
app.include_router(
    router=users.router,
    prefix="/api/users",
    tags=["users"]
)
app.include_router(
    router=servers.router,
    prefix="/api/servers",
    tags=["servers"]
)
app.include_router(
    router=logs.router,
    prefix="/api/logs",
    tags=["logs"]
)
app.include_router(
    router=auth.router,
    prefix="/api/auth",
    tags=["auth"]
)
app.include_router(
    router=drops.router,
    prefix="/api/drops",
    tags=["drops"]
)
app.include_router(
    router=workspace.router,
    prefix="/api/admin/workspace",
    tags=["workspace"]
)

async def load():
    log = SystemLogger(filename=filename)
    for ext_file in os.listdir("cogs"):
        if ext_file.endswith(".py"):
            try:
                log.loading(
                    status_code=50,
                    message="Extension",
                    details=f"Attempting to load cog extension: {ext_file}",
                )
                await bot.load_extension(f"cogs.{ext_file[:-3]}")
            except Exception as e:
                log.error(
                    status_code=-75,
                    message="Load Fail",
                    details=f"Failed to load extension {ext_file}:\n{e}",
                )

    log.complete(
        status_code=100,
        message="Executed",
        details="Extension loading process completed.",
    )
    log.send("Loader")

async def backend():
    config_uv = uvicorn.Config(app, host="0.0.0.0", port=config.PORT)
    await uvicorn.Server(config_uv).serve()

async def main():
    await asyncio.gather(
        load(), 
        bot.start(os.getenv("TOKEN")),
        backend()
    )


if __name__ == "__main__":  
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("...")
        print("=" * 50)