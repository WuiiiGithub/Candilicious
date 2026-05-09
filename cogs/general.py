from discord import app_commands, Object
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback, discord
from library.logging import CogLogger, CommandLogger, ListenerLogger
import config

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]
selfCollection = db["Self"]

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="General Cog has been initialized and is monitoring for public commands.")

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
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"Bot is live on the [website]({os.getenv('FLASK_DOMAIN')})",
                color=config.msgColor
            ),
            ephemeral=True
        )        

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

    @app_commands.command(name="vote", description="Vote for the bot.")
    async def vote(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Vote Link", details="Handling request for voting information...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the voting system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    General_cog = General(bot)
    await bot.add_cog(General_cog)
