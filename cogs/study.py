import discord, os, asyncio, pymongo, traceback, json, io
from dotenv import load_dotenv
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands

load_dotenv()

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))["Candilicious[Beta]"]
serverCollection = db["Servers"]
learnerCollection = db["Learners"]
from datetime import datetime

class sessionLearners:
    def __init__(self):
        self.learners = {}

    def started(self, id: str):
        self.learners[id] = datetime.now()
        print(f"📌 Session started for {str(id)} at {self.learners[id]}.")

    def cancel(self, id: str):
        if id in self.learners:
            del self.learners[id]
            print(f"🚫 Session canceled for {id}.")
        else:
            print(f"⚠️ No active session found for {id}, cannot cancel.")

    def ended(self, user_id: str, server_id: str):
        if learnerCollection is None:
            print("❌ Database collection is None! Cannot update session.")
            return

        if user_id not in self.learners:
            print(f"⚠️ No active session found for {user_id}, skipping database update.")
            return  

        elapsed_seconds = (datetime.now() - self.learners[user_id]).total_seconds()
        total_mins = int(elapsed_seconds // 60)
        hours, mins = divmod(total_mins, 60)

        if hours == 0 and mins == 0:
            print(f"⏳ Skipping update for {user_id}, no meaningful time spent.")
            return

        print(f"📢 Ending session for {str(user_id)} on server {str(server_id)}: +{hours} hrs, +{mins} mins.")

        result = learnerCollection.update_one(
            {"_id": user_id},
            {
                "$inc": {
                    f"servers.{server_id}.time.hrs": hours, 
                    f"servers.{server_id}.time.mins": mins
                },
                "$setOnInsert": {"_id": user_id}
            },
            upsert=True
        )

        if result.matched_count > 0:
            print(f"✅ Updated session for {user_id} on server {server_id}: +{hours} hrs, +{mins} mins.")
        elif result.upserted_id:
            print(f"✅ Created new session for {user_id} on server {server_id}: +{hours} hrs, +{mins} mins.")
        else:
            print(f"❌ Database update failed for {user_id} on server {server_id}. No changes were made.")

        del self.learners[user_id]


class Study(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitoringUsers = {}  
        self.learnings = sessionLearners()
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
            server_id = str(inter.guild_id)
            study_channel_id = str(study.id)
            
            print(f"⚙️ Configuring Study Channel for Server: {server_id} | Channel: {study_channel_id}")
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"_id": server_id, "channel": study_channel_id}},
                upsert=True
            )
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Study Configurations",
                    description=f"**Configuration Successful!** :tada:\nNow the study channel is {study.mention}",
                    timestamp=datetime.now(),
                    color=0x3498db
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
            member_id = str(member.id)
            server_id = str(member.guild.id)
            
            print(f"🔎 Checking study channel for Server: {server_id}")
            study_data = serverCollection.find_one({"_id": server_id})

            if not study_data or "channel" not in study_data:
                print("⚠️ No study channel configured for this server.")
                return  

            study_channel_id = str(study_data["channel"])
            print(f"📌 Study Channel ID Found: {study_channel_id}")

            if after.channel and str(after.channel.id) == study_channel_id and (before.channel is None or str(before.channel.id) != study_channel_id):
                print(f"👤 {member.name} joined study VC: {after.channel.name}")
                self.learnings.started(id=member_id)

                embed = discord.Embed(
                    title=f"🎉 {member.display_name} is back! 🎉",
                    description=f"Welcome back {member.mention}!\nStudy time resumes!",
                    timestamp=datetime.now(),
                    color=0x3498db
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(
                    name="Request",
                    value="🔴 Please turn on your **camera or screen share**. Otherwise, you may be removed after 5 minutes!"
                )
                await after.channel.send(embed=embed, delete_after=20)

                print(f"⏳ Starting activity monitor for {member.name}")
                task = asyncio.create_task(self.activityMonitor(member, study_channel_id))
                self.monitoringUsers[member_id] = task

            elif before.channel and str(before.channel.id) == study_channel_id and (after.channel is None or str(after.channel.id) != study_channel_id):
                print(f"🚪 {member.name} left study VC: {before.channel.name}")

                if member_id in self.monitoringUsers:
                    print(f"🛑 Stopping activity monitor for {member.name}")
                    self.monitoringUsers[member_id].cancel()
                    del self.monitoringUsers[member_id]
                
                self.learnings.ended(user_id=member_id, server_id=server_id)

                await before.channel.send(
                    embed=discord.Embed(description=f"{member.mention} might be on a break. ☕", color=0x3498db),
                    delete_after=90                    
                )

            elif member_id in self.monitoringUsers and ((not before.self_stream and after.self_stream) or (not before.self_video and after.self_video)):
                await after.channel.send(embed=discord.Embed(
                    title="",
                    description=f"{member.mention}'s Activity Detected! ✅",
                    timestamp=datetime.now(),
                    color=0x3498db
                ), delete_after=20)
                print(f"✅ {member.name} enabled camera or screen share. Stopping timer.")
                self.monitoringUsers[member_id].cancel()
                del self.monitoringUsers[member_id]

            elif before.channel and str(before.channel.id) == study_channel_id and member_id not in self.monitoringUsers and \
                ((before.self_stream and not after.self_stream) or (before.self_video and not after.self_video)):

                print(f"⚠️ {member.name} disabled cam/screen share. Restarting timer.")

                embed = discord.Embed(
                    title="⚠️ Attention Required!",
                    description=f"{member.mention}, you turned off your camera or screen share.\n"
                                "Please turn it back on within **5 minutes**, or you will be removed.",
                    color=discord.Color.orange()
                )
                await after.channel.send(embed=embed, delete_after=20)

                task = asyncio.create_task(self.activityMonitor(member, study_channel_id))
                try:
                    self.learnings.ended(user_id=member_id, server_id=server_id)
                except:
                    traceback.print_exc()
                self.learnings.started(member_id)
                self.monitoringUsers[member_id] = task

        except Exception as e:
            print("❌ Error in `on_voice_state_update`:", e)
            traceback.print_exc()

    async def activityMonitor(self, member: discord.Member, studyId: str):
        """Wait 5 minutes and disconnect user if they don't enable camera or screen share."""
        print(f"⏳ Waiting 5 minutes for {member.name} to start camera or screen share...")
        await asyncio.sleep(300)  # Wait for 5 minutes
        # Ensure user is still in the correct voice channel
        if member.voice and member.voice.channel and str(member.voice.channel.id) == studyId:
            if not member.voice.self_stream and not member.voice.self_video:
                print(f"⏳ {member.name} didn't enable camera/screen share. Disconnecting...")      
                try:
                    await member.voice.channel.send(embed=discord.Embed(
                        description=f"{member.mention} Inactivity Detected. 🚨", 
                        timestamp=datetime.now(),
                        color=0x3498db,
                    ), delete_after=20)
                    await member.move_to(None)  
                        
                    try:
                        self.learnings.cancel(str(member.id))
                    except Exception as e:
                        print(f"⚠️ Error canceling learning session: {e}")
                        traceback.print_exc()
                            
                    except discord.Forbidden:
                            print(f"⚠️ Missing permissions to send/delete messages in {member.voice.channel.name}")
                    except discord.HTTPException:
                        print("⚠️ Failed to send/delete inactivity message.")
                except asyncio.CancelledError:
                    print(f"🛑 Task was cancelled for {member.name}.")
                except discord.Forbidden:
                    print(f"⚠️ Bot lacks permission to move {member.name}.")
                except Exception as e:
                    print(f"❌ Unexpected error while moving {member.name}: {e}")
                    traceback.print_exc()


    @app_commands.guild_only()
    @app_commands.command(name="census", description="Do census to take decision and act based on it.")
    @app_commands.choices(scenario=[
        app_commands.Choice(name="VC mein Badmoshhh h | Someone is being Naughty", value="badmoshi"),
        app_commands.Choice(name="Award Legendary Learner", value="learner"),
        app_commands.Choice(name="Moj Masti Karni h T-T | I want to have fun", value="fun"),
        app_commands.Choice(name="Learner Not Learning", value="cheat")
    ])
    @app_commands.describe(scenario="Pick the scenario happening in your current VC.")
    @app_commands.describe(user="Used when someone is naughty just select that user")
    async def census(self, inter: discord.Interaction, scenario: str, user: discord.User=None):
        try:
            # Determine the poll question based on the chosen scenario.
            if scenario == "badmoshi": 
                question_text = f"Guys, do you think {user.display_name} is doing badmoshi/Naughtiness?"
            elif scenario == "learner":
                question_text = f"Guys, do you think {user.display_name} is most sincerely learning?"
            elif scenario == "fun":
                question_text = f"Guys, {user.display_name} wants to spend some time having fun. Would you like to join?"
            elif scenario == "cheat":
                question_text = f"Guys, do you think {user.display_name} is actually learning right now?"
            else:
                return  
            msg = await inter.channel.send(embed=discord.Embed(
                title="Census",
                description=question_text,
                timestamp=datetime.now()
            ))

            await msg.add_reaction("✅")
            await msg.add_reaction("❎")

            await asyncio.sleep(30)

            count = 0
            for reaction in msg.reactions:
                if reaction == "✅":
                    count+=1
                if reaction == "❎":
                    count-=1
            print(count)

            if count and scenario=="badmoshi":
                await inter.channel.send(embed=discord.Embed(
                    title="Badmoshiii",
                    description=f"Got you! badmosh {user.mention} :imp_smiling:",
                    timestamp=datetime.now()
                ))
            await inter.user.move_to(None)
            
        except:
            traceback.print_exc()



    @app_commands.guild_only()
    @app_commands.command(name="leaderboard", description="Check out your study leaderboard.")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Local Leaderboard", value=1),
        app_commands.Choice(name="Global Leaderboard", value=0)
    ])
    @app_commands.describe(scope="It describes if you want to see leaderboard within the server or globally.")
    async def leaderboard(self, inter: discord.Interaction, scope: int=1):
        await inter.response.send_message("The Leaderboard command is still under development!", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="delete", description="Delete your or your server configuration.")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Delete your collected data", value=1),
        app_commands.Choice(name="Delete Server Configuration", value=0)
    ])
    @app_commands.describe(scope="This parameter tells about the scope of deletion")
    async def delete(self, inter: discord.Interaction, scope: int = 1):
        file = None

        if scope:
            user_data = learnerCollection.find_one({"_id": str(inter.user.id)})
            if not user_data:
                return await inter.response.send_message(embed=discord.Embed(
                    title="",
                    description="No data found for you."
                ), ephemeral=True)

            learnerCollection.delete_one({"_id": str(inter.user.id)})
            file = discord.File(io.BytesIO(json.dumps(user_data, indent=4).encode()), f"{inter.user.display_name}.json")

        else:
            if not inter.user.guild_permissions.manage_guild:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        title="Missing Permissions",
                        description="You are not a manager of this server.\nPlease request the manager to perform this operation.",
                        color=0x348db
                    ),
                    ephemeral=True
                )

            server_data = serverCollection.find_one({"_id": str(inter.guild.id)})
            if not server_data:
                return await inter.response.send_message(embed=discord.Embed(
                    title="",
                    description="No server data found."
                ), ephemeral=True)

            serverCollection.delete_one({"_id": str(inter.guild.id)})
            file = discord.File(io.BytesIO(json.dumps(server_data, indent=4).encode()), f"{inter.guild.name}.json")

        try:
            await inter.user.send(content="The data being deleted is attached below.", file=file)
            await inter.response.send_message(discord.Embed(
                title="",
                description="Deletion successful. Check your DMs."
            ), ephemeral=True)
        except discord.Forbidden:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="DMs Disabled",
                    description="I am not able to DM you. Please enable DMs!",
                    color=0x348db
                ),
                ephemeral=True
            )

async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)

    guild_ids = [1354101256662286397, 1218819398974963752] 
    for guild_id in guild_ids:
        for command in Study_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))