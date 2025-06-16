from discord import app_commands, Object
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback, discord
from library import logging
import config

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]
selfCollection = db["Self"]

#dlog = logging.Logger("General", style="default")

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
        except:
            traceback.print_exc()

    @app_commands.command(name="tos", description="Shows terms of service")
    async def tos(self, inter: discord.Interaction):
        tos = selfCollection.find_one({"_id": "tos"})
        if tos:
            await inter.response.send_message(embed=discord.Embed(
                title="Terms of Service", 
                description=tos["content"],
                timestamp=tos["updated"],
                color=config.msgColor
            ))
        else:
            await inter.response.send_message(embed=discord.Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="privacy", description="Shows privacy policy")
    async def privacy(self, inter: discord.Interaction):
        privacy = selfCollection.find_one({"_id": "privacy"})
        if privacy:
            await inter.response.send_message(embed=discord.Embed(
                title="Privacy Policy", 
                description=privacy["content"],
                timestamp=privacy["updated"],
                color=config.msgColor
            ))
        else:
            await inter.response.send_message(embed=discord.Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="about", description="Shows details about the bot")
    async def about(self, inter: discord.Interaction):
        about = selfCollection.find_one({"_id": "about"})
        if about:
            await inter.response.send_message(embed=discord.Embed(
                title="About", 
                description=about["content"],
                timestamp=about["updated"],
                color=config.msgColor
            ))
        else:
            await inter.response.send_message(embed=discord.Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="new", description="Shows the details of the newest update.")
    async def new(self, inter: discord.Interaction):
        update = selfCollection.find_one({"_id": "updates"})
        if update:
            await inter.response.send_message(embed=discord.Embed(
                title="What's New?", 
                description=update["content"],
                timestamp=update["updated"],
                color=config.msgColor
            ))
        else:
            await inter.response.send_message(embed=discord.Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="vote", description="Vote for the bot.")
    async def vote(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )


async def setup(bot):
    General_cog = General(bot)
    await bot.add_cog(General_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in General_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=Object(id=guild_id))