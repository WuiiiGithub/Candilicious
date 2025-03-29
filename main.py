import os

import discord, asyncio, threading
from dotenv import load_dotenv
from discord.ext import commands
from flask import Flask, render_template

load_dotenv()

intents=discord.Intents.all()
bot=commands.Bot(
    command_prefix=".", 
    intents=intents, 
    help_command=None,
)

app = Flask(__name__, template_folder="public", static_folder="./public/assets")

@app.route('/')
def home():
    favicons = os.listdir(os.path.join(app.static_folder, "favicon"))
    return render_template("index.html", favicons=favicons)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

async def load():
    for filename in os.listdir('cogs'):
        if filename.endswith('.py'):
            print(f"Loading {filename}")
            await bot.load_extension(f"cogs.{filename[:-3]}")

def run_flask():
    app.run(host="0.0.0.0", port=10000)

async def main():
    frontend = threading.Thread(target=run_flask, daemon=True)
    frontend.start()

    await load() 
    await bot.start(os.getenv("TOKEN"))

asyncio.run(main())