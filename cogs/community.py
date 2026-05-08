import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback
from library.logging import CogLogger, CommandLogger, ListenerLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]

class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()
        cogLog.log_cog(action="starting", status_code=0, details="Community Cog has been initialized and is ready for member interactions.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Community cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()
    
    @app_commands.guild_only()
    @app_commands.command(name='find', description='Find a study buddy.')
    async def find(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Buddy Search", details="Handling user request to find a study buddy...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the buddy system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Community_cog = Community(bot)
    await bot.add_cog(Community_cog)
