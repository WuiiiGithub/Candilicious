import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import traceback
from library.logging import CogLogger, CommandLogger, ListenerLogger
from library import db

filename = __name__.title()
cogLog = CogLogger(filename=filename)

serverCollection = db['server']
sessionsCollection = db['sessions']

class Server(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()
        cogLog.log_cog(action="starting", status_code=0, details="Server Cog has been initialized and is ready for guild-specific management.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Server cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.guild_only()
    @app_commands.command(name='attendence', description='Mark your attendence here :)')
    async def attendence(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Attendance Stat", details="Handling request to mark attendance...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the attendance system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()
    
    @app_commands.guild_only()
    @app_commands.command(name='clean', description='Remove all inactive people in server.')
    async def clean(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Cleanup Task", details="Handling request to remove inactive members...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the cleanup system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()
    
    @app_commands.guild_only()
    @app_commands.command(name='invite', description='Get session info for this channel.')
    async def invite(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Session Info", details="Looking up session for this channel...")

            if not inter.channel or not hasattr(inter.channel, 'id'):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="This command can only be used in a voice channel.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=10,
                )
                cmdLog.send()
                return

            session_doc = sessionsCollection.find_one({"channel_id": str(inter.channel.id)})
            if not session_doc:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="No active session in this channel.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=10,
                )
                cmdLog.process(status_code=50, name="No Session", details="No session found for this channel.")
                cmdLog.send()
                return

            sid = session_doc.get("session_id")
            members = session_doc.get("members", {})
            member_count = len(members)
            session_type = session_doc.get("session_type", "*")

            description = f"**Members:** {member_count}\n"
            description += f"**Type:** `{session_type}`\n\n"
            description += f"**Session ID** (copy & share):\n```\n{sid}\n```"

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Session Info",
                    description=description,
                    color=config.msgColor
                ),
                ephemeral=True
            )
            cmdLog.process(status_code=100, name="Done", details=f"Session info for {sid} delivered.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()
    
    @app_commands.guild_only()
    @app_commands.command(name='lookup', description='Find a study buddy.')
    async def lookup(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Lookup Task", details="Handling request for member lookup...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the lookup system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


    @app_commands.guild_only()
    @app_commands.command(
        name="doubt", 
        description="Flag this as a doubt."
    )
    async def doubt(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Doubt Flag", details="Handling request to flag a doubt...")
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"The command is still under construction."
                )
            )
            cmdLog.process(status_code=100, name="Status Sent", details="Member notified that the doubt flagging system is under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Server_cog = Server(bot)
    await bot.add_cog(Server_cog)
