import os, sys#, cloud_setup
import discord, asyncio, threading, pymongo, speedtest, bson
from dotenv import load_dotenv
from library.session import TokenManager
from discord.ext import commands
from flask import Flask, render_template, request
from asgiref.wsgi import WsgiToAsgi
import uvicorn, config
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, OperationFailure

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")

try:
    client = pymongo.MongoClient(host=MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[config.dbName]
    exceptionCollection = db["exception"]
    db.command('ping') 
    print(f"Connected to MongoDB database: {config.dbName}")

except (ServerSelectionTimeoutError, ConnectionFailure, OperationFailure) as e:
    print(f"ERROR: Could not connect to MongoDB. \nPlease check MONGODB_URI and ensure your MongoDB server is running and accessible from the container. \nError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred during MongoDB connection: {e}")
    sys.exit(1)

intents=discord.Intents.all()
bot=commands.Bot(
    command_prefix=".", 
    intents=intents, 
    help_command=None,
)

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
    print("Entered the exception https")
    tm = TokenManager(os.getenv("SECRET_KEY"))
    data = tm.verifyToken(token=token)['data']    
    if len(data["_id"])==24:
        tokenData = exceptionCollection.find_one({"_id": bson.ObjectId(data["_id"])})
    else:
        tokenData = None

    if tokenData:
        st = speedtest.Speedtest()
        st.get_best_server()

        downloadSpeed = st.download(threads=1) / 10**6
        uploadSpeed = st.upload(threads=1) / 10**6
        ping = st.results.ping
        bot.userNetworkConnection[tokenData["user_id"]] = {
            "download": downloadSpeed,
            "upload": uploadSpeed,
            "ping": ping
        }
        return "Pong!"
    else:
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
    for filename in os.listdir('cogs'):
        if filename.endswith('.py'):
            print(f"Loading {filename}")
            await bot.load_extension(f"cogs.{filename[:-3]}")

async def main():
    frontend = threading.Thread(target=run_flask, daemon=True)
    frontend.start()

    await load()
    await bot.start(os.getenv("TOKEN"))

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print('...',"="*50, sep='\n')
    print("The application has been stopped.")
    print("="*50)