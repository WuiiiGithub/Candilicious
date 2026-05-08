import discord, os, asyncio, pymongo, traceback, json, io, qrcode, random
import config
from dotenv import load_dotenv
from datetime import (
    datetime, 
    timedelta, 
    timezone
)
from discord.ext import commands
from discord import app_commands
from library.templates import *
from library.logging import *
from library.session import *
from library.leaderboard import *

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))["Candilicious[Beta]"]
serverCollection = db["servers"]
userCollection = db["users"]
exceptionCollection = db["exception"]
exceptionCollection.create_index("expiresAt", expireAfterSeconds=0)

class Study(commands.Cog):
    def __init__(self, bot):
        # general vars
        self.bot = bot

        # study vc vars
        self.monitoringUsers = {}
        self.exceptions = tempDataHandler()
        self.learnings = sessionLearners()
        self.droppings = {}
        self.monitoringChannels = {}
        self.dropChannelLocks = {}

        # dropper vars
        self.dropConfigsCache = {}
        cogLog.log_cog(action="starting", status_code=0, details="Study Cog has been initialized and is ready for use.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Syncing", details="Trying to sync with Bot Tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Success", details="Bot Tree has been successfully synced.")
        except Exception:
            log.error(status_code=-100, message="Error", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.command(name="config", description="Configure your study channel")
    @app_commands.guild_only()
    @app_commands.describe(study="Please enter your study channel")
    @app_commands.describe(interval="Time in which 1 drop takes place")
    @app_commands.describe(drop="Quantity of Gold drops")
    async def config(self, inter: discord.Interaction, study: discord.VoiceChannel, interval: int, drop: int):
        """Save the study channel in the database."""
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            server_id = str(inter.guild_id)
            study_channel_id = str(study.id)
            cmdLog.process(
                status_code=0,
                name='Waiting',
                details=f"Trying to configure the study channel ({study_channel_id})."
            )
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"_id": server_id, "channel": study_channel_id, "drop": drop, "interval": interval}},
                upsert=True,
            )
            embed=discord.Embed(
                title="Study Configurations",
                description=f"**Configuration Successful!** :tada:",
                timestamp=datetime.now(),
                color=config.msgColor,
            )
            embed.add_field(
                name="Channel", 
                value=study.mention,
                inline=True
            )
            embed.add_field(
                name="Interval", 
                value=interval, 
                inline=True
            )
            embed.add_field(
                name="Drops",
                value=drop,
                inline=False
            )
            await inter.response.send_message(
                embed = embed,
                delete_after=20,
            )
            cmdLog.process(
                status_code=100,
                name='Executed',
                details='The server seems to have configured successfully.'
            )
        except Exception as e:
            cmdLog.process(
                status_code=-100,
                name='Error',
                details=traceback.format_exc()
            )
        finally:
            cmdLog.send()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Track users joining and activity changes in the study channel."""
        log = ListenerLogger(filename=filename, event_name="on_voice_state_update")
        try:
            if member.bot:
                return
            member_id = str(member.id)
            server_id = str(member.guild.id)
            
            # Initial check
            study_data = serverCollection.find_one({"_id": server_id})

            if not study_data or "channel" not in study_data:
                # We don't log every voice update for non-configured servers to avoid spam
                return

            study_channel_id = str(study_data["channel"])
            print(self.exceptions.data)

            # Case of joining
            if (
                # if he joined later channel
                after.channel
                # And if that channel is a study channel
                and str(after.channel.id) == study_channel_id
                # He came from non study channel or no place to study channel
                and (
                    # Either no channel before
                    before.channel is None 
                    # Or either it was not study channel
                    or str(before.channel.id) != study_channel_id
                )
            ):
                log.process(status_code=0, message="Join", details=f"Handling {member.name} entering the study zone: {after.channel.name}")
                self.learnings.started(id=member_id)

                embed = discord.Embed(
                    title=f"🎉 {member.display_name} is back! 🎉",
                    description=f"Welcome back {member.mention}!\nStudy time resumes!",
                    timestamp=datetime.now(),
                    color=0x3498DB,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if self.exceptions.isNotInside(str(member_id)):
                    embed.add_field(
                        name="Request",
                        value="🔴 Please turn on your **camera or screen share**. Otherwise, you may be removed after 5 minutes!",
                    )
                await after.channel.send(content=member.mention, embed=embed, delete_after=20)

                task = asyncio.create_task(
                    self.activityMonitor(member, study_channel_id)
                )
                self.monitoringUsers[member_id] = task
                log.complete(status_code=100, message="Handled", details=f"Started activity monitor for {member.name}.")
                log.send()

            # Case of leaving
            if (
                # If they were in some channel before
                before.channel
                # And channel was a study channel
                and str(before.channel.id) == study_channel_id
                # And later they left study channel
                and (
                    # Either they left
                    after.channel is None 
                    # Or either they went to non study channel
                    or str(after.channel.id) != study_channel_id
                )
            ):
                log.process(status_code=0, message="Leave", details=f"{member.name} is leaving the study zone: {before.channel.name}")

                if member_id in self.monitoringUsers:
                    log.process(status_code=75, message="Stopping", details=f"Stopping the activity monitor for {member.name} as they left.")
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
                log.complete(status_code=100, message="Handled")
                log.send()
            
            # Case: Activity for already joined & not left
            #       i.e. within vc activity
            # --------------------------------------------
            # This Case: Monitored user started activity
            if (
                # If user is among monitered users
                member_id in self.monitoringUsers 
                # and started activity
                and (
                    # Started screen share
                    (
                        not before.self_stream 
                        and after.self_stream
                    )
                    # Or started video
                    or (
                        not before.self_video 
                        and after.self_video
                    )
                )
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
                log.process(status_code=75, message="Media Init", details=f"{member.name} enabled camera or screen share. Removing them from the kick timer.")
                self.monitoringUsers[member_id].cancel()
                del self.monitoringUsers[member_id]
                
                # Dropping tasks
                # Here, we know someone came up
                # and there is someone learning
                # We start rewarding

                channel_id = after.channel.id
                self.monitoringChannels[channel_id] = self.monitoringChannels.get(channel_id, 0) + 1

                if self.monitoringChannels[channel_id] == 1:
                    # only first active user starts dropper
                    org_drop = study_data.get('drop', 10)
                    org_interval = study_data.get("interval", 15)

                    self.droppings[channel_id] = asyncio.create_task(
                        self.dropper_routine(
                            channel=after.channel,
                            org_interval=org_interval,
                            org_drop=org_drop
                        )
                    )
                log.complete(status_code=100, message="Handled")
                log.send()

            # Case: Non monitored/learning user stopped activity
            if (
                # if they were in some channel before
                before.channel
                # And if that channel is study channel
                and str(before.channel.id) == study_channel_id
                # This user is not being monitored yet
                and member_id not in self.monitoringUsers
                # Stopped Activity
                and (
                    # Stopped Streaming
                    (
                        before.self_stream 
                        and not after.self_stream
                    )
                    # Or stopped Video
                    or (
                        before.self_video 
                        and not after.self_video
                    )
                )
                # While still being in study channel
                and (
                    # They didn't leave vc
                    after.channel
                    # And, they are in study vc
                    and str(after.channel.id) == study_channel_id
                )
            # And not among exceptions
            ) and self.exceptions.isNotInside(str(member_id)):
                log.process(status_code=-75, message="Media Stop", details=f"{member.name} disabled camera or screen share. Re-initiating the watch timer.")

                channel_id = before.channel.id

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
                    pass # Silently handle if ending session fails
                self.learnings.started(member_id)
                self.monitoringUsers[member_id] = task
                
                # dropping tasks
                channel_id = before.channel.id
                if channel_id in self.monitoringChannels:
                    self.monitoringChannels[channel_id] -= 1

                    if self.monitoringChannels[channel_id] <= 0:
                        self.monitoringChannels.pop(channel_id, None)

                        task = self.droppings.get(channel_id)
                        if task:
                            task.cancel()
                            self.droppings.pop(channel_id, None)
                log.complete(status_code=100, message="Handled")
                log.send()

        except Exception:
            log.error(status_code=-100, message="Error", details=traceback.format_exc())
            log.send()

    async def activityMonitor(self, member: discord.Member, studyId: str):
        """
        Wait 5 minutes and disconnect user if they don't enable camera or screen share.
        """
        taskLog = TaskLogger(filename=filename, task_name="activity_monitor")
        taskLog.before(status_code=0, message="Watching", details=f"Starting the 5-minute inactivity watch for {member.name}...")
        taskLog.send()
        
        await asyncio.sleep(300)  # Wait for 5 minutes
        
        resLog = TaskLogger(filename=filename, task_name="activity_monitor")
        # Ensure user is still in the correct voice channel
        if (
            member.voice
            and member.voice.channel
            and str(member.voice.channel.id) == studyId
        ):
            if not member.voice.self_stream and not member.voice.self_video:
                resLog.process(status_code=-75, message="Inactive", details=f"{member.name} failed to enable media within time. Disconnecting them...")
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
                        resLog.step(status_code=-100, message="Session Error", details=f"Failed to cancel the learning session for {member.name}: {e}")

                    resLog.after(status_code=100, message="Success", details=f"Successfully handled the removal of {member.name} for inactivity.")
                except asyncio.CancelledError:
                    resLog.after(status_code=0, message="Cancelled", details=f"The monitoring task for {member.name} was cancelled.")
                except discord.Forbidden:
                    resLog.after(status_code=-100, message="Forbidden", details=f"I don't have the permissions to move {member.name} or send the notification.")
                except Exception as e:
                    resLog.after(status_code=-100, message="Error", details=f"An unexpected error occurred while moving {member.name}: {e}")
                finally:
                    resLog.send()

    @app_commands.guild_only()
    @app_commands.command(
        name="exception",
        description="This is to create an exception for you coz you have low network.",
    )
    async def exception(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(
                status_code=0,
                name='Waiting',
                details="Initiating the secure token generation process for a study exception..."
            )
            token = exceptionCollection.find_one_and_update(
                    {"user_id": str(inter.user.id)},
                    {
                        "$setOnInsert": { "user_id": str(inter.user.id) },
                        "$set": {"expiresAt": datetime.now(timezone.utc) + timedelta(minutes=10)}
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
                status_code=50,
                name='Ready',
                details="The verification token has been successfully generated."
            )

            domain = os.getenv("FLASK_DOMAIN")
            if not domain.endswith('/'):
                domain = domain + "/"
            link = domain + "except/" + token

            cmdLog.process(
                status_code=75,
                name='QR Code',
                details="Generating the verification QR code for the user..."
            )
            qr = qrcode.QRCode(box_size=10, border=8)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill="black", back_color="white")
            
            with io.BytesIO() as image_binary:
                img.save(image_binary, format="PNG")
                image_binary.seek(0)
                await inter.response.send_message(
                    content=f"## **[__Verify Now!__](<{link}>)**",
                    file=discord.File(image_binary, "qrcode.png"),
                    ephemeral=True,
                )

            asyncio.tasks.create_task(self.exceptionVerifier(inter, cmdLog))
            cmdLog.process(status_code=100, name="Promoted", details="Verification prompt has been delivered to the user.")
        except Exception:
            cmdLog.process(status_code=-100, name='Error', details=traceback.format_exc())
        finally:
            cmdLog.send()

    async def exceptionVerifier(self, inter: discord.Interaction, cmdLog):
        t = datetime.now()
        cmdLog.process(
            status_code=0,
            name='Waiting',
            details="Starting the background verification process for the study exception..."
        )
        while (details:=self.bot.userNetworkConnection.get(str(inter.user.id), None))==None and (datetime.now() - t).total_seconds() <= 90:
            await asyncio.sleep(1)

        if details==None:
            await inter.followup.send(
                embed=discord.Embed(
                    title='Timeout',
                    description="Verification polling timed out after 90 seconds.",
                    color=config.msgColor
                ), 
                ephemeral=True
            )
            cmdLog.process(status_code=-50, name="Timeout", details="Verification polling timed out after 90 seconds.")
            return
        
        download = details["download"]
        upload = details["upload"]
        ping = details['ping']

        if (download>=2.5 and upload>=2.5) and ping<=50:
            cmdLog.process(
                status_code=100,
                name='Rejected',
                details="Network speed is sufficient; the user's exception request was denied."
            )
            exceptionCollection.delete_one({"user_id": str(inter.user.id)})
            await inter.followup.send(content="You have good internet speed lol!", ephemeral=True)
            return 
        else:
            self.exceptions.add(str(inter.user.id))
            cmdLog.process(
                status_code=100,
                name='Verified',
                details="Poor network connection confirmed; exception granted for 10 minutes."
            )
            await inter.followup.send(content="10 Mins access granted!", ephemeral=True)
            return 

    async def dropper_routine(self, channel: discord.VoiceChannel, org_drop: int, org_interval: int):
        taskLog = TaskLogger(filename=filename, task_name="dropper_routine")
        try:
            taskLog.before(status_code=0, message="Waiting", details=f"Initiating the gold dropper routine in {channel.name}...")
            taskLog.send()
            while True:
                interval = random.randint(0, int(2 * org_interval))
                await asyncio.sleep(interval * 60)

                drop = random.randint(int(0.25 * org_drop), int(1.75 * org_drop))
                await channel.send(
                    embed=discord.Embed(
                        description=f"You got {drop} :coin: gold coins",
                        color=discord.Color.gold()
                    ),
                    delete_after=20
                )
        except Exception as e:
            taskLog.after(status_code=-100, message="Error", details=f"Gold dropper routine encountered an issue: {e}")
            taskLog.send()

    @app_commands.guild_only()
    @app_commands.command(
        name="leaderboard", description="Check out your study leaderboard."
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Local Leaderboard", value=1),
            app_commands.Choice(name="Global Leaderboard", value=0),
        ],
        view=[
            app_commands.Choice(name='View by Username', value='name'),
            app_commands.Choice(name='View by Display Name', value='display_name')
        ]
    )
    @app_commands.describe(
        scope="It describes if you want to see leaderboard within the server or globally.",
        view="It defines based on what choice you view your leaderboard",
    )
    async def leaderboard(self, inter: discord.Interaction, view: str="display_name", scope: int = 1):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name='Waiting', details="Trying to fetch the local study toppers from the database...")
            if scope == 1:
                toppers = list(userCollection.aggregate(
                    [
                        {
                            "$project": {
                                "_id": 1,
                                "name": 1,
                                "display_name": 1,
                                "time": {"$ifNull": [f"$servers.{inter.guild_id}.time", 0]},
                            }
                        },
                        {"$sort": {"time": -1}},
                        {"$limit": 10},
                    ]
                ))
                cmdLog.process(status_code=75, name='Ready', details="Successfully fetched the local toppers; preparing response...")
                await inter.response.send_message(embed=discord.Embed(
                        description=leaderboard_template(toppers=toppers, view=view),
                        color=config.msgColor
                    ),
                    delete_after=30
                )
                cmdLog.process(status_code=100, name="Executed", details="Local leaderboard successfully delivered.")
            else:
                await inter.response.send_message(
                    "The Leaderboard command is still under development!", ephemeral=True
                )
                cmdLog.process(status_code=50, name="Pending", details="Global leaderboard requested but is still under construction.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

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
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Waiting", details="Initiating the deletion request processing...")
            file = None

            if scope:
                user_data = userCollection.find_one({"_id": str(inter.user.id)})
                if not user_data:
                    cmdLog.process(status_code=-25, name="Missing", details="No user data was found to delete.")
                    return await inter.response.send_message(
                        embed=discord.Embed(
                            title="", 
                            description="No data found for you.",
                            color=config.msgColor
                        ),
                        ephemeral=True,
                    )

                userCollection.delete_one({"_id": str(inter.user.id)})
                cmdLog.process(status_code=75, name="Removed", details="User record has been successfully purged from the database.")
                file = discord.File(
                    io.BytesIO(json.dumps(user_data, indent=4).encode()),
                    f"{inter.user.display_name}.json",
                )

            else:
                if not inter.user.guild_permissions.manage_guild:
                    cmdLog.process(status_code=-100, name="Denied", details="User lacks manage_guild permissions; deletion aborted.")
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
                    cmdLog.process(status_code=-25, name="Missing", details="No server configuration found to delete.")
                    return await inter.response.send_message(
                        embed=discord.Embed(
                            title="", 
                            description="No server data found.",
                            color=config.msgColor
                        ),
                        ephemeral=True,
                    )

                serverCollection.delete_one({"_id": str(inter.guild.id)})
                cmdLog.process(status_code=75, name="Removed", details="Server configuration purged from the database.")
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
                cmdLog.process(status_code=100, name="Executed", details="Deletion complete; backup file sent to user DMs.")
            except discord.Forbidden:
                cmdLog.process(status_code=-25, name="Blocked", details="Data was deleted but the backup file could not be DM'd.")
                await inter.response.send_message(
                    embed=discord.Embed(
                        title="DMs Disabled",
                        description="I am not able to DM you. Please enable DMs!",
                        color=0x348DB,
                    ),
                    ephemeral=True,
                )
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name='plb', description='placeholder command for leaderboard')
    async def plb(self, inter: discord.Interaction, style: Literal['gold', 'silver', 'bronze', 'wood']):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Waiting", details="Trying to generate the placeholder leaderboard image...")
            LEADERBOARD_DATA = {
                "podium": [
                    {"rank": 1, "name": "Yuvi", "time": "76 hours", "avatar_url": "https://picsum.photos/seed/yuvi/200"},
                    {"rank": 2, "name": "Patrick Jane", "time": "21 hours", "avatar_url": "https://picsum.photos/seed/patrick/200"},
                    {"rank": 3, "name": "Mai", "time": "21 hours", "avatar_url": "https://picsum.photos/seed/mai/200"}
                ],
                "rows": [
                    {"rank": 4, "name": "Tanmay", "time": "21:15", "avatar_url": "https://picsum.photos/seed/tanmay/200"},
                    {"rank": 5, "name": "Kitty", "time": "1977:34", "avatar_url": "https://picsum.photos/seed/kitty/200"},
                    {"rank": 6, "name": "philia", "time": "18:22", "avatar_url": "https://picsum.photos/seed/philia/200"},
                    {"rank": 7, "name": "maysem^_^", "time": "15:18", "avatar_url": "https://picsum.photos/seed/maysem/200"},
                    {"rank": 8, "name": "Jawa", "time": "15:01", "avatar_url": "https://picsum.photos/seed/jawa/200"},
                    {"rank": 9, "name": "Cyrus", "time": "08:46", "avatar_url": "https://picsum.photos/seed/cyrus/200"},
                    {"rank": 10, "name": "Hades", "time": "08:18", "avatar_url": "https://picsum.photos/seed/hades/200"}
                ]
            }

            # Defer since image processing takes a moment
            await inter.response.defer()

            image_data = await getNovaLeaderboard(LEADERBOARD_DATA, style)
            
            if image_data:
                file = discord.File(fp=image_data, filename="leaderboard.webp")
                await inter.followup.send(file=file)
                cmdLog.process(status_code=100, name="Executed", details="Leaderboard image generated and delivered.")
            else:
                await inter.followup.send("Failed to generate the leaderboard image.")
                cmdLog.process(status_code=-100, name="Failed", details="Image generation failed to return valid data.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name='shell', description='execute special commands')
    async def shell(self, inter: discord.Interaction, cmd: str):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Waiting", details=f"Initiating shell command execution: {cmd}")
            if cmd == 'update lb':
                await inter.response.send_message("Scanning database for users with missing names...", ephemeral=True)
                
                cursor = userCollection.find(
                    {
                        "$or": [
                            {"name": None},
                            {"display_name": None},
                            {"pfp": None}
                        ]
                    },
                    {"_id": 1}
                )
                users_to_fix = list(cursor)

                if not users_to_fix:
                    await inter.followup.send("No users found with missing names. Database is up to date!", ephemeral=True)
                    cmdLog.process(status_code=100, name="Executed", details="DB scan complete; no users required fixing.")
                    return

                cmdLog.process(status_code=50, name="Ready", details=f"Database scan finished; {len(users_to_fix)} users need recovery.")
                bulk_ops = []
                count = 0
                failed = 0

                for doc in users_to_fix:
                    user_id = doc['_id']

                    try:
                        # Attempt to fetch the user from Discord
                        # We convert to int because Discord IDs are integers, but stored as strings in your DB
                        user = await inter.client.fetch_user(int(user_id))
                        name = user.name
                        display_name = user.display_name
                        mention = user.mention
                        avatar = user.display_avatar.url                        
                        
                        # Prepare the update
                        bulk_ops.append(pymongo.UpdateOne(
                            {
                                "_id": user_id,
                                "$or": [
                                    {"name": None},
                                    {"display_name": None},
                                    {"pfp": None}
                                ]
                            },
                            {
                                "$set": {
                                    "name": name,
                                    "display_name": display_name,
                                    "pfp": avatar
                                }
                            }
                        ))
                        count += 1
                    except Exception:
                        failed += 1
                        continue

                    # Batch sleep to prevent Discord rate limits (100 requests per minute is the typical limit)
                    if count % 10 == 0:
                        await asyncio.sleep(1)

                if bulk_ops:
                    result = userCollection.bulk_write(bulk_ops)
                    await inter.followup.send(
                        f"Process complete!\n- Names recovered: {result.modified_count}\n- Failed/Not Found: {failed}", 
                        ephemeral=True
                    )
                    cmdLog.process(status_code=100, name="Executed", details=f"Recovery complete: {result.modified_count} users updated, {failed} failed.")
                else:
                    await inter.followup.send(f"Found {len(users_to_fix)} users, but could not fetch names for any of them.", ephemeral=True)
                    cmdLog.process(status_code=-25, name="Failed", details="Recovery attempted but zero users could be fetched from Discord.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name='balance', description='Check the balance of your account')
    async def balance(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Waiting", details="Fetching the user's account balance...")
            await inter.response.send_message(discord.Embed(
                title='',
                description="Command under construction",
                color=config.msgColor
            ))
            cmdLog.process(status_code=100, name="Executed", details="Balance delivered successfully.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)
