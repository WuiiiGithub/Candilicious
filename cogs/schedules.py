import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os, pymongo, traceback, asyncio
from library import logging

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]
dlog = logging.Logger("Schedules", style="default")

class Schedules(commands.Cog):
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
    @app_commands.command(name='tasks', description='Manage tasks using this command.')
    async def tasks(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )

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
        try:
            total_seconds = secs + (mins * 60) + (hrs * 3600) + (days * 86400)

            if total_seconds <= 0:
                total_seconds = 300

            # Acknowledge the remainder setup
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Remainder Set!",
                    description=f"Your remainder has been set for {days} days, {hrs} hours, {mins} minutes, and {secs} seconds.\nMessage: {text}",
                    color=config.msgColor
                ),
                ephemeral=True
            )

            # Schedule the remainder
            asyncio.create_task(self.remainder_runner(inter.user, total_seconds, text))

        except Exception as e:
            print(f"❌ Error in `remainder` command: {e}")
            traceback.print_exc()
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description="An error occurred while setting the remainder. Please try again later.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )


    async def remainder_runner(self, user: discord.User, time: int, text: str):
        """Send a remainder message to the user after the specified time."""
        try:
            print(f"⏳ Waiting {time} seconds to send a remainder to {user.name}...")
            await asyncio.sleep(time)  # Wait for the specified time
            await user.send(
                embed=discord.Embed(
                    title="⏰ Remainder",
                    description=text,
                    color=config.msgColor,
                    timestamp=datetime.now()
                )
            )
            print(f"✅ Remainder sent to {user.name}.")
        except discord.Forbidden:
            print(f"⚠️ Unable to send DM to {user.name}. DMs might be disabled.")
        except Exception as e:
            print(f"❌ Error in `remainder_runner`: {e}")
            traceback.print_exc()
    

async def setup(bot):
    Schedules_cog = Schedules(bot)
    await bot.add_cog(Schedules_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in Schedules_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))