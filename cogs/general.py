from discord import app_commands, Object
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import os, traceback, discord
from library.logging import CogLogger, CommandLogger, ListenerLogger
from library import is_muted, db
import config

filename = __name__.title()
cogLog = CogLogger(filename=filename)

selfCollection = db["Self"]
userCollection = db["users"]

MUTE_DURATIONS = {
    "1hr": timedelta(hours=1),
    "3hr": timedelta(hours=3),
    "6hr": timedelta(hours=6),
    "12hr": timedelta(hours=12),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1mon": timedelta(days=30),
}

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="General Cog has been initialized and is monitoring for public commands.")

    @app_commands.command(name="ping", description="Tells whats the ping")
    async def ping(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            latency = self.bot.latency
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Pong 🎉",
                    description=f"Latency is `{latency*1000:.2f}`",
                    color=config.msgColor
                ),
                ephemeral=True
            )
            cmdLog.process(
                status_code=100,
                name="Latency Checked",
                details=f"The latency of the bot is {latency}"
            )
        except Exception as e:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the General cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.command(name='site', description='Shows the site of the bot')
    async def site(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        site_url = str(os.getenv('WEBSITE_DOMAIN'))
        try:
            if site_url == '' or site_url == None:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"Bot is not live.",
                        color=config.msgColor
                    ),
                    ephemeral=True
                )   
                cmdLog.process(
                    status_code=-75,
                    name="Site Down",
                    details="The site is not available"
                )

            elif site_url.startswith('http'):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"Bot is live on the [website]({site_url})",
                        color=config.msgColor
                    ),
                    ephemeral=True
                )     
                cmdLog.process(
                    status_code=100,
                    name="Site Up",
                    details="The site is running at " + site_url
                )
        except Exception as e:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="tos", description="Shows terms of service")
    async def tos(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Data Fetch", details="Trying to retrieve Terms of Service from the database...")
            tos = selfCollection.find_one({"_id": "tos"})
            if tos:
                await inter.response.send_message(embed=discord.Embed(
                    title="Terms of Service", 
                    description=tos["content"],
                    timestamp=tos["updated"],
                    color=config.msgColor
                ))
                cmdLog.process(status_code=100, name="TOS Ready", details="Terms of Service successfully delivered to the user.")
            else:
                await inter.response.send_message(embed=discord.Embed(
                    description="An error occured please contact support.",
                    timestamp=datetime.now()
                ))
                cmdLog.process(status_code=-25, name="Data Missing", details="Requested Terms of Service document could not be found.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="privacy", description="Shows privacy policy")
    async def privacy(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Data Fetch", details="Trying to retrieve Privacy Policy from the database...")
            privacy = selfCollection.find_one({"_id": "privacy"})
            if privacy:
                await inter.response.send_message(embed=discord.Embed(
                    title="Privacy Policy", 
                    description=privacy["content"],
                    timestamp=privacy["updated"],
                    color=config.msgColor
                ))
                cmdLog.process(status_code=100, name="Policy Ready", details="Privacy Policy successfully delivered to the user.")
            else:
                await inter.response.send_message(embed=discord.Embed(
                    description="An error occured please contact support.",
                    timestamp=datetime.now()
                ))
                cmdLog.process(status_code=-25, name="Data Missing", details="Requested Privacy Policy document could not be found.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="about", description="Shows details about the bot")
    async def about(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Data Fetch", details="Trying to retrieve bot 'About' information from the database...")
            about = selfCollection.find_one({"_id": "about"})
            if about:
                await inter.response.send_message(embed=discord.Embed(
                    title="About", 
                    description=about["content"],
                    timestamp=about["updated"],
                    color=config.msgColor
                ))
                cmdLog.process(status_code=100, name="About Ready", details="Bot information successfully delivered to the user.")
            else:
                await inter.response.send_message(embed=discord.Embed(
                    description="An error occured please contact support.",
                    timestamp=datetime.now()
                ))
                cmdLog.process(status_code=-25, name="Data Missing", details="Requested 'About' document could not be found.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="new", description="Shows the details of the newest update.")
    async def new(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Data Fetch", details="Trying to retrieve latest update notes from the database...")
            update = selfCollection.find_one({"_id": "updates"})
            if update:
                await inter.response.send_message(embed=discord.Embed(
                    title="What's New?", 
                    description=update["content"],
                    timestamp=update["updated"],
                    color=config.msgColor
                ))
                cmdLog.process(status_code=100, name="Update Ready", details="Latest update notes successfully delivered to the user.")
            else:
                await inter.response.send_message(embed=discord.Embed(
                    description="An error occured please contact support.",
                    timestamp=datetime.now()
                ))
                cmdLog.process(status_code=-25, name="Data Missing", details="Requested update notes could not be found.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="mute", description="Mute bot notifications for yourself")
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 Hour", value="1hr"),
        app_commands.Choice(name="3 Hours", value="3hr"),
        app_commands.Choice(name="6 Hours", value="6hr"),
        app_commands.Choice(name="12 Hours", value="12hr"),
        app_commands.Choice(name="1 Day", value="1d"),
        app_commands.Choice(name="1 Week", value="1w"),
        app_commands.Choice(name="1 Month", value="1mon"),
        app_commands.Choice(name="Forever", value="forever"),
    ])
    async def mute(self, inter: discord.Interaction, duration: app_commands.Choice[str]):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)
            now = datetime.now(timezone.utc)
            muted_doc = {"muted_at": now}

            if duration.value == "forever":
                muted_doc["until"] = None
                label = "forever"
            else:
                delta = MUTE_DURATIONS[duration.value]
                muted_doc["until"] = now + delta
                label = duration.value

            userCollection.update_one(
                {"_id": user_id},
                {"$set": {"muted": muted_doc}},
                upsert=True,
            )

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Notifications Muted",
                    description=f"Bot notifications muted for **{label}**.\nYou won't receive any DMs or pings from the bot during this time.",
                    color=discord.Color.greyple(),
                ),
                ephemeral=True,
            )
            cmdLog.process(status_code=100, name="Mute", details=f"User {user_id} muted for {label}")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="unmute", description="Unmute bot notifications")
    async def unmute(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)
            result = userCollection.update_one(
                {"_id": user_id, "muted": {"$ne": None}},
                {"$unset": {"muted": ""}},
            )

            if result.modified_count:
                await inter.response.send_message(
                    embed=discord.Embed(
                        title="Notifications Unmuted",
                        description="Bot notifications have been restored.",
                        color=config.msgColor,
                    ),
                    ephemeral=True,
                )
                cmdLog.process(status_code=100, name="Unmute", details=f"User {user_id} unmuted")
            else:
                await inter.response.send_message(
                    embed=discord.Embed(
                        title="Not Muted",
                        description="You don't have an active mute.",
                        color=discord.Color.greyple(),
                    ),
                    ephemeral=True,
                )
                cmdLog.process(status_code=50, name="Unmute", details=f"User {user_id} was not muted")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    General_cog = General(bot)
    await bot.add_cog(General_cog)
