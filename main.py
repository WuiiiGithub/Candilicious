import os#, cloud_setup
import discord, asyncio, threading, pymongo, speedtest, bson
from dotenv import load_dotenv
from library.session import TokenManager
from discord.ext import commands
from flask import Flask, render_template
from asgiref.wsgi import WsgiToAsgi
import uvicorn, config

load_dotenv()

exceptionCollection = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))[config.dbName]["exception"]

intents=discord.Intents.all()
bot=commands.Bot(
    command_prefix=".", 
    intents=intents, 
    help_command=None,
)

# My Vars
bot.userNetworkConnection = {}

app = Flask(__name__, template_folder="public", static_folder="./public/assets")

@app.route('/')
def home():
    favicons = os.listdir(os.path.join(app.static_folder, "favicon"))
    return render_template("index.html", favicons=favicons)

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

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

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
    print("="*50)
    print("The application has been stopped.")
    print("="*50)