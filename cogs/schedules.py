import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os, pymongo, traceback, asyncio
from library.logging import CogLogger, CommandLogger, ListenerLogger, TaskLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]

class Schedules(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()
        cogLog.log_cog(action="starting", status_code=0, details="Schedules Cog has been initialized and is monitoring for task requests.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Schedules cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.guild_only()
    @app_commands.command(name='tasks', description='Manage tasks using this command.')
    async def tasks(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Task Status", details="Handling request to manage tasks...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the task system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(
        name="remainder",
        description="Set a remainder for yourself."
    )
    @app_commands.describe(
        days="Number of days until the remainder.",
        hrs="Number of hours until the remainder.",
        mins="Number of minutes until the remainder.",
        secs="Number of seconds until the remainder.",
        text="The message for the remainder."
    )
    async def remainder(
        self,
        inter: discord.Interaction,
        days: int = 0,
        hrs: int = 0,
        mins: int = 0,
        secs: int = 0,
        text: str = "Times up! 🔔"
    ):
        """Set a remainder for the user."""
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Input Calc", details="Calculating total wait time for the remainder...")
            total_seconds = secs + (mins * 60) + (hrs * 3600) + (days * 86400)

            if total_seconds <= 0:
                total_seconds = 300

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Remainder Set!",
                    description=f"Your remainder has been set for {days} days, {hrs} hours, {mins} minutes, and {secs} seconds.\nMessage: {text}",
                    color=config.msgColor
                ),
                ephemeral=True
            )

            cmdLog.process(status_code=100, name="Task Set", details=f"Remainder successfully scheduled for {total_seconds} seconds from now.")
            # Schedule the remainder
            asyncio.create_task(self.remainder_runner(inter.user, total_seconds, text))
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


    async def remainder_runner(self, user: discord.User, time: int, text: str):
        """Send a remainder message to the user after the specified time."""
        taskLog = TaskLogger(filename=filename, task_name="remainder_runner")
        try:
            taskLog.before(status_code=50, message="Delaying", details=f"Beginning {time}s wait before delivering remainder to {user.name}")
            taskLog.send()
            await asyncio.sleep(time)  # Wait for the specified time
            
            resLog = TaskLogger(filename=filename, task_name="remainder_runner")
            await user.send(
                embed=discord.Embed(
                    title="⏰ Remainder",
                    description=text,
                    color=config.msgColor,
                    timestamp=datetime.now()
                )
            )
            resLog.after(status_code=100, message="DM Send", details=f"Remainder successfully delivered to {user.name}.")
            resLog.send()
        except discord.Forbidden:
            resLog.after(status_code=-25, message="DM Blocked", details=f"Unable to send remainder DM to {user.name}; they may have DMs disabled.")
            resLog.send()
        except Exception as e:
            resLog.after(status_code=-100, message="Error", details=str(e))
            resLog.send()
    

async def setup(bot):
    Schedules_cog = Schedules(bot)
    await bot.add_cog(Schedules_cog)
