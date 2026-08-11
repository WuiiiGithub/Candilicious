import os, sys
import asyncio
import logging
import discord
import discord.app_commands as app_commands
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from discord.ext import commands
import uvicorn, config
from library.logging import SystemLogger, CogLogger
logger = logging.getLogger(__name__)
from motor.motor_asyncio import AsyncIOMotorClient
import routes 
from routes import (
    boards,
    bulk,
    drops,
    insights,
    logs,
    notes,
    projects,
    reports,
    servers,
    social,
    stats,
    tasks,
    uploads,
    users,
    auth,
    workspace,
    sessions,
)
from routes.event_bus import EventBus
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
    cmdLineArgs = sys.argv[1:]
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
        try:
            await app.db["drop.offers"].drop_index("expire_at_1")
        except OperationFailure:
            pass
        await app.db["drop.offers"].create_index(
            [("expire_at", ASCENDING)],
            expireAfterSeconds=0
        )

        await app.db["admin_otp"].create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0
        )
        await app.db["admin_sessions"].create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0
        )

        from routes.workspace import load_variables_from_db
        await load_variables_from_db(app.db)

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
    logger.info("Shutting down...")
    try:
        recovery = getattr(bot, 'recovery', None)
        if recovery:
            await recovery.take_snapshot()
            recovery.stop_snapshot_task()
    except Exception:
        pass
    try:
        await bot.close()
    except Exception:
        pass
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
    logger.info("Shutdown complete")

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_DOMAIN], 
   allow_credentials=True,
   allow_methods=["*"],  
    allow_headers=["*"],  
)


class SecurityHeadersMiddleware:
    """Apply basic hardening headers to every response.

    A strict CSP is only attached to /api responses (which are JSON/SSE only);
    FastAPI's own /docs UI is left untouched so it keeps working.
    """

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=()",
        "Cache-Control": "no-store",
    }

    API_CSP = "default-src 'none'; frame-ancestors 'none'"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        api_csp = path.startswith("/api")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                header_map = {k.lower().decode("latin-1"): v for k, v in headers}
                for key, value in self.HEADERS.items():
                    if key.lower() not in header_map:
                        headers.append(
                            (key.encode("latin-1"), value.encode("latin-1"))
                        )
                if api_csp and "content-security-policy" not in header_map:
                    headers.append(
                        (b"content-security-policy", self.API_CSP.encode("latin-1"))
                    )
                message = dict(message, headers=headers)
            return await send(message)

        return await self.app(scope, receive, send_wrapper)


class _BodyTooLarge(Exception):
    pass


class RequestBodySizeMiddleware:
    """Reject request bodies larger than MAX_BYTES.

    Guards against memory exhaustion from huge JSON payloads. Checked against
    the Content-Length header when present, and also while streaming the body,
    so chunked/unguessed bodies are capped too."""

    MAX_BYTES = 5 * 1024 * 1024  # 5 MB

    def __init__(self, app):
        self.app = app

    async def _too_large(self, send):
        body = b'{"detail":"Request body too large"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        for key, value in scope.get("headers") or []:
            if key == b"content-length":
                try:
                    if int(value) > self.MAX_BYTES:
                        return await self._too_large(send)
                except ValueError:
                    pass
                break

        seen = 0

        async def wrapped_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b"")) or 0
                if seen > self.MAX_BYTES:
                    raise _BodyTooLarge()
            return message

        wrapped_scope = dict(scope)
        wrapped_scope["receive"] = wrapped_receive
        try:
            await self.app(wrapped_scope, receive, send)
        except _BodyTooLarge:
            await self._too_large(send)


app.add_middleware(RequestBodySizeMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Bot Setup
intents = discord.Intents.all()

class EntryPointAwareTree(app_commands.CommandTree):
    """Command tree that skips Entry Point command interactions (type 4).

    Entry Point commands are registered via the REST API only and are not part
    of the tree, so the tree would otherwise raise AppCommandType(4) -> ValueError.
    They are handled separately in the on_interaction listener below.
    """

    def _from_interaction(self, interaction: discord.Interaction) -> None:
        data = getattr(interaction, "data", None)
        if data and data.get("type") == 4:
            return
        super()._from_interaction(interaction)

    async def sync(self, *, guild: discord.abc.Snowflake | None = None):
        """Sync the tree, preserving the app's Entry Point command.

        Discord rejects a global bulk update that omits the app's Entry Point
        command (error 50240), so the existing Entry Point command is fetched
        and included in the global sync payload.
        """
        if guild is not None:
            return await super().sync(guild=guild)

        if self.client.application_id is None:
            raise app_commands.MissingApplicationID

        commands = self._get_all_commands(guild=None)
        if self.translator:
            payload = [await c.get_translated_payload(self, self.translator) for c in commands]
        else:
            payload = [c.to_dict(self) for c in commands]

        try:
            existing = await self._http.get_global_commands(self.client.application_id)
        except discord.HTTPException:
            existing = []
        keep_fields = {
            "id", "name", "name_localizations", "description", "description_localizations",
            "type", "handler", "contexts", "integration_types",
            "default_member_permissions", "dm_permission", "nsfw",
        }
        for command in existing:
            if command.get("type") == 4:
                payload.append({k: v for k, v in command.items() if k in keep_fields})

        try:
            data = await self._http.bulk_upsert_global_commands(self.client.application_id, payload=payload)
        except discord.HTTPException as e:
            if e.status == 400 and e.code == 50035:
                raise app_commands.CommandSyncFailure(e, commands) from None
            raise

        return [app_commands.AppCommand(data=d, state=self._state) for d in data]

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    application_id=DISCORD_CLIENT_ID,
    tree_cls=EntryPointAwareTree,
)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type is not discord.InteractionType.application_command:
        return
    data = getattr(interaction, "data", None)
    if not data or data.get("type") != 4:
        return
    log = SystemLogger(filename=filename)
    try:
        await interaction.response.launch_activity()
        log.complete(
            status_code=100,
            message="Activity Launched",
            details=f"Entry Point command invoked by {interaction.user}",
        )
    except discord.InteractionResponded:
        pass
    except discord.HTTPException as e:
        log.error(
            status_code=-50,
            message="Launch Fail",
            details=f"Failed to launch activity from Entry Point command: {e}",
        )

@bot.event
async def on_ready():
    log = SystemLogger(filename=filename)
    log.complete(
        status_code=100,
        message="Ready",
        details=f"Discord bot has logged in as {bot.user} ({bot.user.id})",
    )

    try:
        bot_config = await app.db["config"].find_one({"_id": "bot"}, projection={"status": 1})
        if bot_config and bot_config.get("status"):
            status_str = bot_config["status"].lower()
            status_map = {
                "online": discord.Status.online,
                "idle": discord.Status.idle,
                "dnd": discord.Status.dnd,
                "offline": discord.Status.offline,
                "invisible": discord.Status.invisible,
            }
            desired = status_map.get(status_str)
            if desired:
                await bot.change_presence(status=desired)
                log.complete(
                    status_code=100,
                    message="Status Synced",
                    details=f"Bot status set to {status_str} from MongoDB config",
                )
    except Exception as e:
        log.error(
            status_code=-50,
            message="Status Sync Fail",
            details=f"Failed to sync bot status from MongoDB: {e}",
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

event_bus = EventBus()
app.state.event_bus = event_bus
bot.event_bus = event_bus

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
    router=social.router,
    prefix="/api/social",
    tags=["social"]
)
app.include_router(
    router=workspace.router,
    prefix="/api/admin/workspace",
    tags=["workspace"]
)
app.include_router(
    router=sessions.router,
    prefix="/api/sessions",
    tags=["sessions"]
)
app.include_router(
    router=reports.router,
    prefix="/api/reports",
    tags=["reports"]
)
app.include_router(
    router=bulk.router,
    prefix="/api/bulk",
    tags=["bulk"]
)
app.include_router(
    router=uploads.router,
    prefix="/api/uploads",
    tags=["uploads"]
)
app.include_router(
    router=notes.router,
    prefix="/api/notes",
    tags=["notes"]
)
app.include_router(
    router=stats.router,
    prefix="/api/stats",
    tags=["stats"]
)
app.include_router(
    router=insights.router,
    prefix="/api/stats",
    tags=["stats"]
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
    await bot.login(os.getenv("TOKEN"))
    await asyncio.gather(
        load(),
        bot.connect(),
        backend()
    )


if __name__ == "__main__":  
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")