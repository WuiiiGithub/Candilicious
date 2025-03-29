from discord import Interaction, Embed, app_commands, Object
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))["Candilicious[Beta]"]
selfCollection = db["Self"]

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tos", description="Shows terms of service")
    async def tos(self, inter: Interaction):
        tos = selfCollection.find_one({"_id": "tos"})
        if tos:
            await inter.response.send_message(embed=Embed(
                title="Terms of Service", 
                description=tos["content"],
                timestamp=tos["updated"],
                color=0x3498db
            ))
        else:
            await inter.response.send_message(embed=Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="privacy", description="Shows privacy policy")
    async def privacy(self, inter: Interaction):
        privacy = selfCollection.find_one({"_id": "privacy"})
        if privacy:
            await inter.response.send_message(embed=Embed(
                title="Privacy Policy", 
                description=privacy["content"],
                timestamp=privacy["updated"],
                color=0x3498db
            ))
        else:
            await inter.response.send_message(embed=Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="about", description="Shows details about the bot")
    async def about(self, inter: Interaction):
        about = selfCollection.find_one({"_id": "about"})
        if about:
            await inter.response.send_message(embed=Embed(
                title="About", 
                description=about["content"],
                timestamp=about["updated"],
                color=0x3498db
            ))
        else:
            await inter.response.send_message(embed=Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))

    @app_commands.command(name="new", description="Shows the details of the newest update.")
    async def new(self, inter: Interaction):
        update = selfCollection.find_one({"_id": "updates"})
        if update:
            await inter.response.send_message(embed=Embed(
                title="What's New?", 
                description=update["content"],
                timestamp=update["updated"],
                color=0x3498db
            ))
        else:
            await inter.response.send_message(embed=Embed(
                description="An error occured please contact support.",
                timestamp=datetime.now()
            ))


async def setup(bot):
    General_cog = General(bot)
    await bot.add_cog(General_cog)

    guild_ids = [1354101256662286397, 1218819398974963752] 
    for guild_id in guild_ids:
        for command in General_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=Object(id=guild_id))