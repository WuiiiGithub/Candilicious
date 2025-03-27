import discord, os, asyncio, pymongo, traceback
from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands
from discord import app_commands

load_dotenv()

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))["Candilicious"]
serverCollection = db["Servers"]

class Study(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitoringUsers = {}  # { member_id: asyncio.Task }
        print("✅ Entered Study Cogs")

    @commands.Cog.listener()
    async def on_ready(self):
        print("🔄 Syncing with Bot Tree...")
        await self.bot.tree.sync()
        print("✅ Bot Tree has been Synced.")

    @app_commands.command(name="config", description="Configure your study channel")
    @app_commands.guild_only()
    @app_commands.describe(study="Please enter your study channel")
    async def config(self, inter: discord.Interaction, study: discord.VoiceChannel):
        """Save the study channel in the database."""
        try:
            print(f"⚙️ Configuring Study Channel for Server: {inter.guild_id} | Channel: {study.id}")
            serverCollection.update_one(
                {"server": inter.guild_id},
                {"$set": {"server": inter.guild_id, "channel": study.id}},
                upsert=True
            )
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Study Configurations",
                    description=f"**Configuration Successful!** :tada:\nNow the study channel is {study.mention}",
                    timestamp=datetime.now()
                ),
                delete_after=20
            )
        except Exception as e:
            print("❌ Error in `/config` command:", e)
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Track users joining and activity changes in the study channel."""
        try:
            # Fetch Study Channel from Database
            print(f"🔎 Checking study channel for Server: {member.guild.id}")
            study_data = serverCollection.find_one({"server": member.guild.id})

            if not study_data or "channel" not in study_data:
                print("⚠️ No study channel configured for this server.")
                return  

            study_channel_id = study_data["channel"]
            print(f"📌 Study Channel ID Found: {study_channel_id}")

            # User Joins Study VC
            if after.channel and after.channel.id == study_channel_id and before.channel != after.channel:
                print(f"👤 {member.name} joined study VC: {after.channel.name}")

                embed = discord.Embed(
                    title=f"{member.display_name} is back!",
                    description=f"🎉 Welcome back {member.mention}! Study time resumes!",
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(
                    name="Request",
                    value="🔴 Please turn on your **camera or screen share**. Otherwise, you may be removed after 1 minute 30 seconds!"
                )

                await after.channel.send(embed=embed, delete_after=20)

                # Start monitoring the user
                print(f"⏳ Starting activity monitor for {member.name}")
                task = asyncio.create_task(self.activityMonitor(member, study_channel_id))
                self.monitoringUsers[member.id] = task

            # User Leaves Study VC
            elif before.channel and before.channel.id == study_channel_id and (after.channel is None or after.channel.id != study_channel_id):
                print(f"🚪 {member.name} left study VC: {before.channel.name}")

                if member.id in self.monitoringUsers:
                    print(f"🛑 Stopping activity monitor for {member.name}")
                    self.monitoringUsers[member.id].cancel()
                    del self.monitoringUsers[member.id]

                await before.channel.send(
                    embed=discord.Embed(description=f"{member.mention} might be on a break. ☕"),
                    delete_after=60                    
                )

            # User Turns ON Camera/Screen Share
            elif member.id in self.monitoringUsers and ((not before.self_stream and after.self_stream) or (not before.self_video and after.self_video)):
                print(f"✅ {member.name} enabled camera or screen share. Stopping timer.")
                self.monitoringUsers[member.id].cancel()
                del self.monitoringUsers[member.id]

            # User Turns OFF Camera/Screen Share AFTER Passing
            elif before.channel and before.channel.id == study_channel_id and member.id not in self.monitoringUsers and \
                ((before.self_stream and not after.self_stream) or (before.self_video and not after.self_video)):

                print(f"⚠️ {member.name} disabled cam/screen share. Restarting timer.")

                embed = discord.Embed(
                    title="⚠️ Attention Required!",
                    description=f"{member.mention}, you turned off your camera or screen share.\n"
                                "Please turn it back on within **1 minute 30 seconds**, or you will be removed.",
                    color=discord.Color.orange()
                )
                await after.channel.send(embed=embed, delete_after=20)

                # Restart monitoring
                task = asyncio.create_task(self.activityMonitor(member, study_channel_id))
                self.monitoringUsers[member.id] = task

        except Exception as e:
            print("❌ Error in `on_voice_state_update`:", e)
            traceback.print_exc()

    async def activityMonitor(self, member: discord.Member, studyId: int):
        """Wait 1 minute 30 seconds and disconnect user if they don't enable camera or screen share."""
        try:
            print(f"⏳ Waiting 1 minute 30 seconds for {member.name} to start camera or screen share...")
            await asyncio.sleep(90) 

            # Check if user is still in voice and hasn't enabled cam/stream
            if member.voice and member.voice.channel and member.voice.channel.id == studyId:
                if not member.voice.self_stream and not member.voice.self_video:
                    print(f"⏳ {member.name} didn't enable camera/screen share. Disconnecting...")
                    await member.move_to(None)
                    system_channel = member.guild.system_channel
                    if system_channel and system_channel.permissions_for(member.guild.me).send_messages:
                        await system_channel.send(f"🚨 {member.mention} was removed due to inactivity.", delete_after=20)
                    else:
                        print(f"⚠️ Cannot send message in system channel. Missing permissions or channel is None.")

        except asyncio.CancelledError:
            print(f"🛑 Activity check canceled for {member.name} (User turned on cam/stream).")
        except Exception as e:
            print("❌ Error in `activityMonitor`:", e)
            traceback.print_exc()

async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)

    guild_ids = [1354101256662286397, 1218819398974963752] 
    for guild_id in guild_ids:
        for command in Study_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))