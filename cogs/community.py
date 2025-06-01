import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback
from library import logging

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]
dlog = logging.Logger("Community", style="default")

class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
        except:
            traceback.print_exc()
    
    @app_commands.guild_only()
    @app_commands.command(name='find', description='Find a study buddy.')
    async def find(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )

async def setup(bot):
    Community_cog = Community(bot)
    await bot.add_cog(Community_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in Community_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))