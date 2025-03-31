import discord, os, asyncio, pymongo, traceback, json, io, qrcode
from dotenv import load_dotenv
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
from library.templates import *
from library.logging import Logger
from library.session import *

dlog = Logger("Study", style="default")

load_dotenv()

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))["Candilicious[Beta]"]
serverCollection = db["Servers"]
learnerCollection = db["Learners"]
exceptionCollection = db["exception"]
exceptionCollection.create_index("expiresAt", expireAfterSeconds=0)


class Study(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.monitoringUsers = {}
        self.exceptions = tempDataHandler()
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
    @dlog.command()
    async def config(self, inter: discord.Interaction, study: discord.VoiceChannel):
        """Save the study channel in the database."""
        try:
            server_id = str(inter.guild_id)
            study_channel_id = str(study.id)

            print(
                f"⚙️ Configuring Study Channel for Server: {server_id} | Channel: {study_channel_id}"
            )
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"_id": server_id, "channel": study_channel_id}},
                upsert=True,
            )
            await inter.response.send_message(
                embed=discord.Embed(
                    title="Study Configurations",
                    description=f"**Configuration Successful!** :tada:\nNow the study channel is {study.mention}",
                    timestamp=datetime.now(),
                    color=0x3498DB,
                ),
                delete_after=20,
            )
        except Exception as e:
            print("❌ Error in `/config` command:", e)
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
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

            if (
                after.channel
                and str(after.channel.id) == study_channel_id
                and (
                    before.channel is None or str(before.channel.id) != study_channel_id
                )
            ) and not self.exceptions.isInside:
                print(f"👤 {member.name} joined study VC: {after.channel.name}")
                self.learnings.started(id=member_id)

                embed = discord.Embed(
                    title=f"🎉 {member.display_name} is back! 🎉",
                    description=f"Welcome back {member.mention}!\nStudy time resumes!",
                    timestamp=datetime.now(),
                    color=0x3498DB,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(
                    name="Request",
                    value="🔴 Please turn on your **camera or screen share**. Otherwise, you may be removed after 5 minutes!",
                )
                await after.channel.send(embed=embed, delete_after=20)

                print(f"⏳ Starting activity monitor for {member.name}")
                task = asyncio.create_task(
                    self.activityMonitor(member, study_channel_id)
                )
                self.monitoringUsers[member_id] = task

            elif (
                before.channel
                and str(before.channel.id) == study_channel_id
                and (after.channel is None or str(after.channel.id) != study_channel_id)
            ):
                print(f"🚪 {member.name} left study VC: {before.channel.name}")

                if member_id in self.monitoringUsers:
                    print(f"🛑 Stopping activity monitor for {member.name}")
                    self.monitoringUsers[member_id].cancel()
                    del self.monitoringUsers[member_id]

                self.learnings.ended(user_id=member_id, name=member.display_name, server_id=server_id)

                await before.channel.send(
                    embed=discord.Embed(
                        description=f"{member.mention} might be on a break. ☕",
                        color=0x3498DB,
                    ),
                    delete_after=90,
                )

            elif member_id in self.monitoringUsers and (
                (not before.self_stream and after.self_stream)
                or (not before.self_video and after.self_video)
            ):
                await after.channel.send(
                    embed=discord.Embed(
                        title="",
                        description=f"{member.mention}'s Activity Detected! ✅",
                        timestamp=datetime.now(),
                        color=0x3498DB,
                    ),
                    delete_after=20,
                )
                print(
                    f"✅ {member.name} enabled camera or screen share. Stopping timer."
                )
                self.monitoringUsers[member_id].cancel()
                del self.monitoringUsers[member_id]

            elif (
                before.channel
                and str(before.channel.id) == study_channel_id
                and member_id not in self.monitoringUsers
                and (
                    (before.self_stream and not after.self_stream)
                    or (before.self_video and not after.self_video)
                )
            ) and not self.exceptions.isInside:

                print(f"⚠️ {member.name} disabled cam/screen share. Restarting timer.")

                embed = discord.Embed(
                    title="⚠️ Attention Required!",
                    description=f"{member.mention}, you turned off your camera or screen share.\n"
                    "Please turn it back on within **5 minutes**, or you will be removed.",
                    color=discord.Color.orange(),
                )
                await after.channel.send(embed=embed, delete_after=20)

                task = asyncio.create_task(
                    self.activityMonitor(member, study_channel_id)
                )
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
        print(
            f"⏳ Waiting 5 minutes for {member.name} to start camera or screen share..."
        )
        await asyncio.sleep(300)  # Wait for 5 minutes
        # Ensure user is still in the correct voice channel
        if (
            member.voice
            and member.voice.channel
            and str(member.voice.channel.id) == studyId
        ):
            if not member.voice.self_stream and not member.voice.self_video:
                print(
                    f"⏳ {member.name} didn't enable camera/screen share. Disconnecting..."
                )
                try:
                    await member.voice.channel.send(
                        embed=discord.Embed(
                            description=f"{member.mention} Inactivity Detected. 🚨",
                            timestamp=datetime.now(),
                            color=0x3498DB,
                        ),
                        delete_after=20,
                    )
                    await member.move_to(None)

                    try:
                        self.learnings.cancel(str(member.id))
                    except Exception as e:
                        print(f"⚠️ Error canceling learning session: {e}")
                        traceback.print_exc()

                    except discord.Forbidden:
                        print(
                            f"⚠️ Missing permissions to send/delete messages in {member.voice.channel.name}"
                        )
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
    @app_commands.command(name="exception",description="This is to create an exception for you coz you have low network.")
    async def exception(self, inter: discord.Interaction):
        try:
            tokenData = exceptionCollection.find_one_and_update(
                    {"user_id": inter.user.id},
                    {
                        "$setOnInsert": { "user_id": inter.user.id },
                        "$set": {"expiresAt": datetime.now(UTC) + timedelta(minutes=10)}
                    },
                    upsert=True,
                    return_document=True
                )
            token = TokenManager(os.getenv("SECRET_KEY")).genToken({"_id": str(tokenData["_id"])}, 10)
            
            token = str(token)
            link = os.getenv("FLASK_DOMAIN") + "except/" + token
            qr = qrcode.QRCode(box_size=10, border=5)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill="black", back_color="white")
            with io.BytesIO() as image_binary:
                img.save(image_binary, format="PNG")
                image_binary.seek(0)
                await inter.response.send_message(
                    content=f"## [Verify]({link})",
                    file=discord.File(image_binary, "qrcode.png"),
                    ephemeral=True,
                )
            asyncio.tasks.create_task(self.exceptionVerifier(inter))
            
        except Exception as e:
            traceback.print_exc()

    async def exceptionVerifier(self, inter: discord.Interaction):
        try:
            t = datetime.now()
            while (details := self.bot.userNetworkConnection.get(inter.user.id, None)) is None:
                if (datetime.now() - t).total_seconds() >= 90:
                    break
                await asyncio.sleep(1)  
            
            if details is None:
                await inter.followup.send(content="Too late!", ephemeral=True)
                return

            download = details["download"]
            upload = details["upload"]
            ping = details["ping"]

            if download >= 2.5 and upload >= 2.5 and ping <= 50:
                await inter.followup.send(content="You have good internet speed lol!", ephemeral=True)
                self.bot.userNetworkConnection.pop(inter.user.id, None)
            else:
                self.exceptions.add(inter.user.id)
                await inter.followup.send(content="5 Mins access granted!", ephemeral=True)

        except Exception:
            traceback.print_exc()


    @app_commands.guild_only()
    @app_commands.command(
        name="leaderboard", description="Check out your study leaderboard."
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Local Leaderboard", value=1),
            app_commands.Choice(name="Global Leaderboard", value=0),
        ]
    )
    @app_commands.describe(
        scope="It describes if you want to see leaderboard within the server or globally."
    )
    async def leaderboard(self, inter: discord.Interaction, scope: int = 1):
        if scope == 1:
            toppers = learnerCollection.aggregate(
                [
                    {
                        "$project": {
                            "_id": 1,
                            "name": 1,
                            "time": {"$ifNull": [f"$servers.{inter.guild_id}.time", 0]},
                        }
                    },
                    {"$sort": {"time": -1}},
                    {"$limit": 10},
                ]
            )
            await inter.response.send_message(leaderboard_template(toppers=toppers))
        await inter.response.send_message(
            "The Leaderboard command is still under development!", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.command(
        name="delete", description="Delete your or your server configuration."
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Delete your collected data", value=1),
            app_commands.Choice(name="Delete Server Configuration", value=0),
        ]
    )
    @app_commands.describe(scope="This parameter tells about the scope of deletion")
    async def delete(self, inter: discord.Interaction, scope: int = 1):
        file = None

        if scope:
            user_data = learnerCollection.find_one({"_id": str(inter.user.id)})
            if not user_data:
                return await inter.response.send_message(
                    embed=discord.Embed(title="", description="No data found for you."),
                    ephemeral=True,
                )

            learnerCollection.delete_one({"_id": str(inter.user.id)})
            file = discord.File(
                io.BytesIO(json.dumps(user_data, indent=4).encode()),
                f"{inter.user.display_name}.json",
            )

        else:
            if not inter.user.guild_permissions.manage_guild:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        title="Missing Permissions",
                        description="You are not a manager of this server.\nPlease request the manager to perform this operation.",
                        color=0x348DB,
                    ),
                    ephemeral=True,
                )

            server_data = serverCollection.find_one({"_id": str(inter.guild.id)})
            if not server_data:
                return await inter.response.send_message(
                    embed=discord.Embed(title="", description="No server data found."),
                    ephemeral=True,
                )

            serverCollection.delete_one({"_id": str(inter.guild.id)})
            file = discord.File(
                io.BytesIO(json.dumps(server_data, indent=4).encode()),
                f"{inter.guild.name}.json",
            )

        try:
            await inter.user.send(
                content="The data being deleted is attached below.", file=file
            )
            await inter.response.send_message(
                discord.Embed(
                    title="", description="Deletion successful. Check your DMs."
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="DMs Disabled",
                    description="I am not able to DM you. Please enable DMs!",
                    color=0x348DB,
                ),
                ephemeral=True,
            )

    @app_commands.guild_only()
    @app_commands.command(name="census", description="Take a decision over a case by voting.")
    @app_commands.choices(scenario=[
        app_commands.Choice(name="User's behavior is disturbing", value="dtb"),
        app_commands.Choice(name="User is not showing their learning", value="cheat"),
    ])
    @app_commands.describe(
        scenario="Tells about the case you are in a study session", 
        user="The user whom you are referring to in the scenario"
    )
    async def census(inter: discord.Interaction, scenario: str, user: discord.Member):
        await inter.response.defer()  # Defer response to avoid timeout

        if scenario == "dtb":
            title = "Disturbing Behaviour Suspected!"
            description = f"It has come to our attention that {user.mention} is behaving inappropriately in the study channel. Is that right?"
        elif scenario == "cheat":
            title = "Suspected Cheating"
            description = f"It has come to our attention that {user.mention} is not demonstrating their learning in the study channel. Is that right?"
        else:
            await inter.followup.send("Sorry, it's an unknown scenario.", ephemeral=True)
            return

        embed = discord.Embed(
            title=title,
            description=description,
            timestamp=datetime.now(),
            color=discord.Color.red()
        )

        message = await inter.channel.send(embed=embed)

        await message.add_reaction("✅")
        await message.add_reaction("❎")

        await asyncio.sleep(20)  

        message = await inter.channel.fetch_message(message.id) 
        yes_votes = 0
        no_votes = 0

        for reaction in message.reactions:
            if reaction.emoji == "✅":
                yes_votes = reaction.count - 1  
            elif reaction.emoji == "❎":
                no_votes = reaction.count - 1

        if yes_votes > no_votes:
            result_msg = f"The vote is in favor of the scenario: **{yes_votes} ✅ vs {no_votes} ❎**."
        elif no_votes > yes_votes:
            result_msg = f"The vote is against the scenario: **{yes_votes} ✅ vs {no_votes} ❎**."
        else:
            result_msg = f"The vote is tied: **{yes_votes} ✅ vs {no_votes} ❎**."

        await inter.channel.send(result_msg)

        

async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)

    guild_ids = [1354101256662286397, 1218819398974963752]
    for guild_id in guild_ids:
        for command in Study_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))
