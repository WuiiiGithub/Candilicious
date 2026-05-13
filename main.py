import os, sys#, cloud_setup
from pyngrok import ngrok
import discord, asyncio, threading, pymongo, speedtest, bson
from dotenv import load_dotenv
from library.session import TokenManager
from discord.ext import commands
from flask import Flask, render_template, request
from asgiref.wsgi import WsgiToAsgi
from library.logging import SystemLogger, CogLogger
import uvicorn, config, traceback
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, OperationFailure

argLen = len(sys.argv)

# Flags 
## Setup Flags
isVpnSetup = False

# setups
if argLen > 1 and sys.argv[1] == 'vpn':
    isVpnSetup = True
    import setup_vpn

filename = __name__.title()
sysLog = SystemLogger(filename=filename)

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID")

public_url = ngrok.connect(10000).public_url
flask_url = os.getenv('FLASK_DOMAIN')
if flask_url == None or flask_url == '' or '://localhost:' in str(flask_url):
    os.environ['FLASK_DOMAIN'] = public_url
    flask_url = public_url
try:
    sysLog.process(status_code=0, message="Waiting", details="Initiating connection to MongoDB...")
    client = pymongo.MongoClient(host=MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[config.dbName]
    exceptionCollection = db["exception"]
    db.command('ping') 
    sysLog.complete(status_code=100, message="Connected", details=f"Successfully established connection to MongoDB database: {config.dbName}")

except (ServerSelectionTimeoutError, ConnectionFailure, OperationFailure) as e:
    sysLog.error(status_code=-100, message="Error", details=f"Could not connect to MongoDB. Please check connection URI.\nError: {e}")
    sysLog.send("Startup Error")
    sys.exit(1)
except Exception as e:
    sysLog.error(status_code=-100, message="Error", details=f"An unexpected error occurred during database connection:\n{e}")
    sysLog.send("Startup Error")
    sys.exit(1)

intents=discord.Intents.all()
bot=commands.Bot(
    command_prefix=".", 
    intents=intents, 
    help_command=None,
    application_id=APPLICATION_ID
)

@bot.event
async def on_ready():
    log = SystemLogger(filename=filename)
    log.complete(status_code=100, message="Ready", details=f"Discord bot has logged in as {bot.user} ({bot.user.id})")
    
    guild_ids = config.availableIn.get("guilds", [])
    for g_id in guild_ids:
        try:
            guild = discord.Object(id=g_id)
            await bot.tree.sync(guild=guild)
            log.process(status_code=75, message="Synced", details=f"Synced application commands for guild: {g_id}")
        except Exception as e:
            log.error(status_code=-75, message="Sync Fail", details=f"Failed to sync commands for guild {g_id}:\n{e}")
    
    log.complete(status_code=100, message="Executed", details="Successfully synced application commands for all configured guilds.")
    log.send("Bot Events")

# My Vars
bot.userNetworkConnection = {}

app = Flask(__name__, template_folder="public", static_folder="./public/assets")

@app.route('/ping')
def ping():
    try:
        db.command('ping')
        return "OK", 200
    except Exception:
        return "An error occured!", 500
    
@app.route('/')
def home():
    favicons = os.listdir(os.path.join(app.static_folder, "favicon"))
    return render_template("index.html", favicons=favicons)

@app.route('/tos')
def tos_page():
    return render_template("tos.html")

@app.route('/privacy')
def privacy_page():
    return render_template("privacy.html")

@app.route('/about')
def about_page():
    return render_template("about.html")

@app.route("/except/<token>")
def exception(token):
    log = SystemLogger(filename=filename)
    log.process(status_code=50, message="Request", details="Handling study exception request via HTTPS endpoint.")
    
    tm = TokenManager(os.getenv("SECRET_KEY"))
    data = tm.verifyToken(token=token)['data']    
    if len(data["_id"])==24:
        tokenData = exceptionCollection.find_one({"_id": bson.ObjectId(data["_id"])})
        print(tokenData)
    else:
        tokenData = None

    if tokenData:
        try:
            st = speedtest.Speedtest()
            st.get_best_server()
        except Exception as e:
            exceptionCollection.delete_one({"user_id": str(data['user_id'])})
            log.error(status_code=-75, message="Internal Server Error", details="Token verification failed because of internal server error.")


        downloadSpeed = st.download(threads=1) / 10**6
        uploadSpeed = st.upload(threads=1) / 10**6
        ping = st.results.ping
        bot.userNetworkConnection[tokenData["user_id"]] = {
            "download": downloadSpeed,
            "upload": uploadSpeed,
            "ping": ping
        }
        log.complete(status_code=100, message="Verified", details=f"Network connection verified for User ID: {tokenData['user_id']}")
        log.send("Network Test")
        return "Pong!"
    else:
        log.error(status_code=-25, message="Invalid", details="Token verification failed or record not found.")
        log.send("Network Test")
        return "<img src='https://media.tenor.com/x8v1oNUOmg4AAAAM/rickroll-roll.gif' alt='Congrats! You are Rick Rolled!' width='100%' height='100%'>"

app.errorhandler(403)
def forbidden_error(e):
    return render_template('403.html'), 403

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal Server Error at {request.path}: {e}")
    return render_template('500.html'), 500

@app.errorhandler(503)
def service_unavailable_error(e):
    return render_template('503.html'), 503

def run_flask():
    asgi_app = WsgiToAsgi(app)  
    uvicorn.run(asgi_app, host="0.0.0.0", port=config.port)

async def load():
    log = SystemLogger(filename=filename)
    for ext_file in os.listdir('cogs'):
        if ext_file.endswith('.py'):
            try:
                log.loading(status_code=50, message="Extension", details=f"Attempting to load cog extension: {ext_file}")
                await bot.load_extension(f"cogs.{ext_file[:-3]}")
            except Exception as e:
                log.error(status_code=-75, message="Load Fail", details=f"Failed to load extension {ext_file}:\n{e}")
    
    log.complete(status_code=100, message="Executed", details="Extension loading process completed.")
    log.send("Loader")

async def main():
    sysLog.process(status_code=50, message="Frontend", details="Starting Flask frontend in a background thread...")
    frontend = threading.Thread(target=run_flask, daemon=True)
    frontend.start()

    await load()
    sysLog.send("Application Init")
    await bot.start(os.getenv("TOKEN"))

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print('...',"="*50, sep='\n')
    ngrok.kill()
    if isVpnSetup:
        setup_vpn.shut_vpn()
    stopLog = CogLogger(filename=filename)
    stopLog.log_important("Shutdown", status_code=0, details="The application has been stopped by KeyboardInterrupt.")
    print("-"*50, sep='\n')
    print("The application has been stopped.")
    print("="*50)
