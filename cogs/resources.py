import discord, pymongo, traceback, os, config
from discord.ext import commands
from discord import app_commands
from library.logging import *

#dlog = Logger("Study", style="default")
db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))[config.dbName]

class Resources(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
        except:
            traceback.print_exc()

    @app_commands.guild_only()
    @app_commands.command(name='competitive', description='Provides resources for competitive exam.')
    async def competitive(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )

async def setup(bot):
    Resources_cog = Resources(bot)
    await bot.add_cog(Resources_cog)