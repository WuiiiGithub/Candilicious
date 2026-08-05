import discord, traceback, os, config
from discord.ext import commands
from discord import app_commands
from library.logging import CogLogger, CommandLogger, ListenerLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

class Resources(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Resources Cog Initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Syncing Tree")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success")
        except Exception:
            log.error(status_code=-100, message="Sync Failed", details=traceback.format_exc())
        finally:
            log.send()

async def setup(bot):
    Resources_cog = Resources(bot)
    await bot.add_cog(Resources_cog)
