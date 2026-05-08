import discord, pymongo, traceback, os, config
from discord.ext import commands
from discord import app_commands
from library.logging import CogLogger, CommandLogger, ListenerLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))[config.dbName]

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

    @app_commands.guild_only()
    @app_commands.command(name='competitive', description='Provides resources for competitive exam.')
    async def competitive(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Processing")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Success")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Resources_cog = Resources(bot)
    await bot.add_cog(Resources_cog)
