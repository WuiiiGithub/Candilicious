import discord, os, asyncio, pymongo, traceback, json, io, qrcode
import config
from dotenv import load_dotenv
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
from library.templates import *
from library.logging import *
from library.session import *

filename = __name__.title()
cogLog = CogLogger(filename=filename)

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
    async def config(self, inter: discord.Interaction, study: discord.VoiceChannel):
        """Save the study channel in the database."""
        try:
            server_id = str(inter.guild_id)
            study_channel_id = str(study.id)
            cmdLog = CommandLogger(filename=filename, inter=inter)
            cmdLog.process(
                status_code=0,
                name='Waiting',
                details=f"Trying to configure the study channel ({study_channel_id})."
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
            isError = False
        except Exception as e:
            isError = True
            cmdLog.process(
                status_code=100,
                name='Error',
                details=e
            )
        finally:
            if isError == False:
                cmdLog.process(
                    status_code=100,
                    name='Executed',
                    details='The server seems to have configured successfully.'
                )
            cmdLog.send()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Track users joining and activity changes in the study channel."""
        try:
            if member.bot:
                print
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
            ):
                print(f"👤 {member.name} joined study VC: {after.channel.name}")
                self.learnings.started(id=member_id)

                embed = discord.Embed(
                    title=f"🎉 {member.display_name} is back! 🎉",
                    description=f"Welcome back {member.mention}!\nStudy time resumes!",
                    timestamp=datetime.now(),
                    color=0x3498DB,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if not self.exceptions.isInside:
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

                self.learnings.ended(user_id=member_id, server_id=server_id, name=member.display_name)

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
                    self.learnings.ended(user_id=member_id, server_id=server_id, name=member.display_name)
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
    @app_commands.command(
        name="exception",
        description="This is to create an exception for you coz you have low network.",
    )
    async def exception(self, inter: discord.Interaction):
        try:
            cmdLog = CommandLogger(
                filename=filename, 
                inter=inter
            )
            cmdLog.process(
                status_code=0,
                name='Generation',
                details="Initiating token generation process."
            )
            token = exceptionCollection.find_one_and_update(
                    {"user_id": inter.user.id},
                    {
                        "$setOnInsert": { "user_id": inter.user.id },
                        "$set": {"expiresAt": datetime.now(UTC) + timedelta(minutes=10)}
                    },
                    upsert=True,
                    return_document=True
                )["_id"]
            tm = TokenManager(secretKey=os.getenv("SECRET_KEY"))
            token = tm.genToken(
                data={"_id": str(token)},
                expireIn=10
            )
            if token==None or token=='':
                raise ValueError("Invalid token value.")
            
            cmdLog.process(
                status_code=0,
                name='Generated',
                details=f"The token has been generated."
            )

            domain = os.getenv("FLASK_DOMAIN")
            if not domain.endswith('/'):
                domain = domain + "/"
            link = domain + "except/" + token

            cmdLog.process(
                status_code=0,
                name='Generation',
                details=f"Generating a QR Code for exceptions."
            )
            qr = qrcode.QRCode(box_size=10, border=8)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill="black", back_color="white")
            isQRSent = False
            with io.BytesIO() as image_binary:
                img.save(image_binary, format="PNG")
                image_binary.seek(0)
                await inter.response.send_message(
                    content=f"## **[__Verify Now!__](<{link}>)**",
                    file=discord.File(image_binary, "qrcode.png"),
                    ephemeral=True,
                )
                isQRSent = True

            if isQRSent:
                cmdLog.process(
                    status_code=75,
                    name='Sent',
                    details=f"The QR Code to be used as an exception is sent."
                )
            asyncio.tasks.create_task(self.exceptionVerifier(inter, cmdLog))
            
            isError = False
        except Exception as e:
            isError = True
            cmdLog.process(
                status_code=100,
                name='Error',
                details=e
            )
        finally:
            if isError == False:
                cmdLog.process(
                    status_code=100,
                    name='Executed',
                    details='The server seems to have configured successfully.'
                )
            cmdLog.send()

    async def exceptionVerifier(self, inter: discord.Interaction, cmdLog):
        t = datetime.now()
        cmdLog.process(
            status_code=100,
            name='Verification',
            details='The verification process for the study exception has been started.'
        )
        while (details:=self.bot.userNetworkConnection.get(inter.user.id, None))==None and (datetime.now() - t).total_seconds() <= 90:
            continue

        if details==None:
            await inter.followup.send(embed=discord.Embed(
                description="An error occured. Please try again!"
            ))
            return
        
        download = details["download"]
        upload = details["upload"]
        ping = details['ping']

        if (download>=2.5 and upload>=2.5) and ping<=50:
            cmdLog.process(
                status_code=100,
                name='Checked',
                details='Exception Request has been cancelled.'
            )
            await inter.followup.send(content="You have good internet speed lol!")
        else:
            self.exceptions.add(inter.user.id)
            cmdLog.process(
                status_code=100,
                name='Verified',
                details='Exception Request has been accepted.'
            )
            await inter.followup.send(content="10 Mins access granted!")

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
        try:
            cmdLog = CommandLogger(
                filename=filename,
                inter=inter
            )
            if scope == 1:
                cmdLog.process(
                    status_code=0,
                    name='Fetching',
                    details='Fetching the local toppers.'
                )
                toppers = list(learnerCollection.aggregate(
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
                ))
                cmdLog.process(
                    status_code=75,
                    name='Fetched',
                    details='Fetched the local toppers.'
                )
                await inter.response.send_message(embed=discord.Embed(
                        description=leaderboard_template(toppers=toppers),
                        color=config.msgColor
                    ),
                    delete_after=30
                )
            else:
                cmdLog.process(
                    status_code=100,
                    name='Fetching',
                    details='Fetching the local toppers.'
                )
                await inter.response.send_message(
                    "The Leaderboard command is still under development!", ephemeral=True
                )
        except:
            traceback.print_exc()

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
                    embed=discord.Embed(
                        title="", 
                        description="No data found for you.",
                        color=config.msgColor
                    ),
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
                        color=config.msgColor,
                    ),
                    ephemeral=True,
                )

            server_data = serverCollection.find_one({"_id": str(inter.guild.id)})
            if not server_data:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        title="", 
                        description="No server data found.",
                        color=config.msgColor
                    ),
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
                embed=discord.Embed(
                    title="", description="Deletion successful. Check your DMs.",
                    color=config.msgColor
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



async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)

    guild_ids = [1354101256662286397, 1218819398974963752]
    for guild_id in guild_ids:
        for command in Study_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))
