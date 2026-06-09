import os, sys, datetime, json # , cloud_setup
import discord, asyncio, threading, pymongo, speedtest, bson
from dotenv import load_dotenv
from library.session import TokenManager
from discord.ext import commands
from flask import Flask, render_template, request, jsonify
from asgiref.wsgi import WsgiToAsgi
from library.logging import SystemLogger, CogLogger
import uvicorn, config
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
APPLICATION_ID = os.getenv("APPLICATION_ID")

if isNgrokSetup:
    from pyngrok import ngrok, conf
    
    NGROK_AUTH_TOKEN = str(os.getenv("NGROK_AUTH_TOKEN"))
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    public_url = ngrok.connect(config.port).public_url
    flask_url = os.getenv("FLASK_DOMAIN")
    if flask_url == None or flask_url == "" or "://localhost:" in str(flask_url):
        os.environ["FLASK_DOMAIN"] = public_url
        flask_url = public_url

try:
    sysLog.process(
        status_code=0, message="Waiting", details="Initiating connection to MongoDB..."
    )
    client = pymongo.MongoClient(host=MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[config.dbName]
    userCollection = db["users"]
    boardsCollection = db["boards"]
    exceptionCollection = db["exception"]
    boardsLogCollection = db["boards.log"]
    db.command("ping")
    sysLog.complete(
        status_code=100,
        message="Connected",
        details=f"Successfully established connection to MongoDB database: {config.dbName}",
    )

except (ServerSelectionTimeoutError, ConnectionFailure, OperationFailure) as e:
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

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None,
    application_id=APPLICATION_ID,
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


# My Vars
bot.userNetworkConnection = {}
log_lock = threading.Lock()

app = Flask(__name__, template_folder="public", static_folder="./public/assets")


@app.route("/ping")
def ping():
    try:
        db.command("ping")
        return "OK", 200
    except Exception:
        return "An error occured!", 500


@app.route("/")
def home():
    favicons = os.listdir(os.path.join(app.static_folder, "favicon"))
    return render_template("index.html", favicons=favicons)

@app.route("/servers")
def servers():
    guilds_list = bot.guilds
    return render_template("servers.html", guilds=guilds_list)

@app.route("/projects/<token>")
def projects(token):
    user_data = userCollection.find_one({"webToken": token})
    if not user_data:
        return render_template("403.html"), 403
    
    title = f"{user_data.get('display_name', 'User')}'s Projects"
    projects_list = user_data.get("projects", [])
    
    # Calculate progress for each board in projects
    for project in projects_list:
        for board in project.get("boards", []):
            board_doc = boardsCollection.find_one({"_id": board["id"]})
            if board_doc:
                tasks = board_doc.get("tasks", [])
                progress = {
                    "todo": len([t for t in tasks if t["status"] == "todo"]),
                    "cooking": len([t for t in tasks if t["status"] == "cooking"]),
                    "done": len([t for t in tasks if t["status"] == "done"])
                }
                board["progress"] = progress
            else:
                board["progress"] = {"todo": 0, "cooking": 0, "done": 0}

    return render_template("projects.html", projects=projects_list, title=title, token=token)


@app.route("/boards/<token>/<board_id>")
def boards(token, board_id):
    user_data = userCollection.find_one({"webToken": token})
    if not user_data:
        return render_template("403.html"), 403
    
    board_doc = boardsCollection.find_one({"_id": board_id})
    if not board_doc:
        # Create empty board if it doesn't exist
        board_doc = {"_id": board_id, "user_id": user_data["_id"], "tasks": []}
        boardsCollection.insert_one(board_doc)
    
    # Find board name from user projects
    title = "Candilicious Board"
    for p in user_data.get("projects", []):
        for b in p.get("boards", []):
            if b["id"] == board_id:
                title = b["name"]
                break

    return render_template("boards.html", data=board_doc.get("tasks", []), title=title, token=token, board_id=board_id)


@app.route("/api/save/projects/<token>", methods=["POST"])
def save_projects(token):
    user_data = userCollection.find_one({"webToken": token})
    if not user_data:
        return jsonify({"error": "Unauthorized"}), 403
    
    new_projects = request.json.get("projects")
    if new_projects is None:
        return jsonify({"error": "Invalid data"}), 400
    
    userCollection.update_one(
        {"_id": user_data["_id"]},
        {"$set": {"projects": new_projects}}
    )
    return jsonify({"status": "success"})


@app.route("/api/save/board/<token>/<board_id>", methods=["POST"])
def save_board(token, board_id):
    user_data = userCollection.find_one({"webToken": token})
    if not user_data:
        return jsonify({"error": "Unauthorized"}), 403
    
    new_tasks = request.json.get("tasks")
    if new_tasks is None:
        return jsonify({"error": "Invalid data"}), 400
    
    boardsCollection.update_one(
        {"_id": board_id},
        {"$set": {"tasks": new_tasks, "user_id": user_data["_id"]}},
        upsert=True
    )
    return jsonify({"status": "success"})

@app.route("/api/log/board/<token>/<board_id>", methods=["POST"])
def log_board_activity(token, board_id):
    user_data = userCollection.find_one({"webToken": token})
    if not user_data:
        print(f"[ActivityLog] Auth failed. Token not found in 'users' collection: {token}")
        return jsonify({"error": "Unauthorized"}), 403

    # Handle both application/json and text/plain (common with sendBeacon)
    if request.is_json:
        logs = request.json.get("logs")
    else:
        try:
            data = json.loads(request.data.decode('utf-8'))
            logs = data.get("logs")
        except Exception:
            return jsonify({"error": "Invalid payload format"}), 400

    if not logs or not isinstance(logs, list):
        return jsonify({"error": "Invalid data"}), 400

    LOG_FILE = "logs/boards.log"
    BATCH_SIZE = 5 # Lowered for more frequent feedback

    # Enrich logs
    force_sync = False
    for log_entry in logs:
        log_entry["user_id"] = user_data["_id"]
        log_entry["board_id"] = board_id
        log_entry["ip"] = request.remote_addr
        log_entry["mac_id"] = None 
        log_entry["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if log_entry.get("action_type") == "page_close":
            force_sync = True

    with log_lock:
        try:
            # 1. Append to local buffer file immediately
            with open(LOG_FILE, "a") as f:
                for entry in logs:
                    f.write(json.dumps(entry) + "\n")

            # 2. Read all lines to check BATCH_SIZE
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
            
            print(f"[ActivityLog] Buffered {len(logs)} new logs. Local buffer now at {len(lines)}/{BATCH_SIZE} lines.")

            if len(lines) >= BATCH_SIZE or force_sync:
                if force_sync:
                    print(f"[ActivityLog] 'page_close' detected. Forcing immediate sync...")
                else:
                    print(f"[ActivityLog] Batch threshold reached. Attempting sync to MongoDB...")
                
                all_logs = []
                for line in lines:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            # Convert ISO string back to datetime for MongoDB
                            entry["created_at"] = datetime.datetime.fromisoformat(entry["created_at"])
                            all_logs.append(entry)
                        except Exception as e:
                            print(f"[ActivityLog] Skipping malformed line: {e}")
                            continue
                
                if all_logs:
                    # 3. Synchronous DB sync
                    result = boardsLogCollection.insert_many(all_logs)
                    print(f"[ActivityLog] Successfully synced {len(result.inserted_ids)} logs to MongoDB.")
                
                    # 4. Success! Clear the file.
                    with open(LOG_FILE, "w") as f:
                        pass 
                    print(f"[ActivityLog] Local buffer cleared.")
                else:
                    print(f"[ActivityLog] No valid logs to sync.")

        except Exception as e:
            # If any step fails (especially DB sync), we don't clear the file
            # The next request will retry syncing everything.
            print(f"[ActivityLog] CRITICAL ERROR during sync: {e}")
            import traceback
            traceback.print_exc()

    return jsonify({"status": "success"})


@app.route("/tos")
def tos_page():
    return render_template("tos.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/about")
def about_page():
    return render_template("about.html")


@app.route("/except/<token>")
def exception(token):
    log = SystemLogger(filename=filename)
    log.process(
        status_code=50,
        message="Request",
        details="Handling study exception request via HTTPS endpoint.",
    )

    tm = TokenManager(os.getenv("SECRET_KEY"))
    data = tm.verifyToken(token=token)["data"]
    if len(data["_id"]) == 24:
        tokenData = exceptionCollection.find_one({"_id": bson.ObjectId(data["_id"])})
    else:
        tokenData = None

    if tokenData:
        try:
            st = speedtest.Speedtest()
            st.get_best_server()
        except Exception as e:
            exceptionCollection.delete_one({"user_id": str(data["user_id"])})
            log.error(
                status_code=-75,
                message="Internal Server Error",
                details="Token verification failed because of internal server error.",
            )

        downloadSpeed = st.download(threads=1) / 10**6
        uploadSpeed = st.upload(threads=1) / 10**6
        ping = st.results.ping
        bot.userNetworkConnection[tokenData["user_id"]] = {
            "download": downloadSpeed,
            "upload": uploadSpeed,
            "ping": ping,
        }
        log.complete(
            status_code=100,
            message="Verified",
            details=f"Network connection verified for User ID: {tokenData['user_id']}",
        )
        log.send("Network Test")
        return "Pong!"
    else:
        log.error(
            status_code=-25,
            message="Invalid",
            details="Token verification failed or record not found.",
        )
        log.send("Network Test")
        return "<img src='https://media.tenor.com/x8v1oNUOmg4AAAAM/rickroll-roll.gif' alt='Congrats! You are Rick Rolled!' width='100%' height='100%'>"


app.errorhandler(403)


def forbidden_error(e):
    return render_template("403.html"), 403


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal Server Error at {request.path}: {e}")
    return render_template("500.html"), 500


@app.errorhandler(503)
def service_unavailable_error(e):
    return render_template("503.html"), 503


def run_flask():
    asgi_app = WsgiToAsgi(app)
    uvicorn.run(asgi_app, host="0.0.0.0", port=config.port)


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


async def main():
    sysLog.process(
        status_code=50,
        message="Frontend",
        details="Starting Flask frontend in a background thread...",
    )
    frontend = threading.Thread(target=run_flask, daemon=True)
    frontend.start()

    await load()
    sysLog.send("Application Init")
    await bot.start(os.getenv("TOKEN"))


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("...", "=" * 50, sep="\n")
    ngrok.kill()
    if isVpnSetup:
        setup_vpn.shut_vpn()
    stopLog = CogLogger(filename=filename)
    stopLog.log_important(
        "Shutdown",
        status_code=0,
        details="The application has been stopped by KeyboardInterrupt.",
    )
    print("-" * 50, sep="\n")
    print("The application has been stopped.")
    print("=" * 50)
