import discord, os, config
from discord.ext import commands
from discord import app_commands
from library.logging import CogLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

class Resources(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Resources Cog Initialized")

async def setup(bot):
    Resources_cog = Resources(bot)
    await bot.add_cog(Resources_cog)
