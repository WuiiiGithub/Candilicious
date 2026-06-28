import discord, os, asyncio, pymongo, traceback, json, io, qrcode, random, secrets
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

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))["Candilicious"]
serverCollection = db["servers"]
userCollection = db["users"]
boardsCollection = db["boards"]
exceptionCollection = db["exception"]
exceptionCollection.create_index("expiresAt", expireAfterSeconds=0)
dropsCollection = db["drops"]
dropsCollection.create_index("created_at", expireAfterSeconds=86400)

from library import dseshpy
dseshpy.initialize(
    session_collection=db["sessions"],
    user_collection=userCollection,
    drops_collection=db["drops"]
)

class Study(commands.Cog):
    def __init__(self, bot):
        # general vars
        self.bot = bot

        # study vc vars
        self.exceptions = tempDataHandler()
        self.session_manager = dseshpy.session.SessionManager()

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
    @app_commands.describe(category="The category where study VCs will be created")
    @app_commands.describe(create_vc="The channel users join to create a new study VC")
    @app_commands.describe(interval="Time in which 1 drop takes place")
    @app_commands.describe(drop="Quantity of Gold drops")
    async def config(self, inter: discord.Interaction, category: discord.CategoryChannel, create_vc: discord.VoiceChannel, interval: int, drop: int):
        """Save the study configuration in the database."""
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            server_id = str(inter.guild_id)
            category_id = str(category.id)
            create_vc_id = str(create_vc.id)
            cmdLog.process(
                status_code=0,
                name='Waiting',
                details=f"Trying to configure the study category ({category_id}) and create_vc ({create_vc_id})."
            )
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"_id": server_id, "category": category_id, "create_vc": create_vc_id, "drop": drop, "interval": interval}},
                upsert=True,
            )
            
            embed=discord.Embed(
                title="Study Configurations",
                description=f"**Configuration Successful!** :tada:",
                timestamp=datetime.now(),
                color=config.msgColor,
            )
            embed.add_field(
                name="Category", 
                value=category.mention,
                inline=True
            )
            embed.add_field(
                name="Create VC", 
                value=create_vc.mention,
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
            server_id = str(member.guild.id)
            
            # Initial check
            study_data = serverCollection.find_one({"_id": server_id})

            if not study_data or "category" not in study_data or "create_vc" not in study_data:
                # We don't log every voice update for non-configured servers to avoid spam
                return

            category_id = str(study_data["category"])
            create_vc_id = str(study_data["create_vc"])
            
            # If user joins the Create VC channel
            if after.channel and str(after.channel.id) == create_vc_id:
                log.process(status_code=0, message="Create VC", details=f"Creating study VC for {member.name}.")
                category = member.guild.get_channel(int(category_id))
                if not category:
                    category = discord.utils.get(member.guild.categories, id=int(category_id))
                
                if category:
                    try:
                        new_vc = await category.create_voice_channel(name=f"{member.display_name}'s Study Room")
                        await member.move_to(new_vc)
                        log.complete(status_code=50, message="Moved", details=f"Moved {member.name} to new VC.")
                    except discord.Forbidden:
                        log.process(status_code=-100, message="Forbidden", details="Missing permissions to create VC or move member.")
                    except Exception as e:
                        log.process(status_code=-100, message="Error", details=f"Failed to create VC or move user: {e}")
                else:
                    log.process(status_code=-100, message="Error", details="Configured category not found.")
                
                log.send()
                return

            # Use dseshpy to manage
            log.process(status_code=0, message="Processing", details=f"Delegating {member.name}'s state to dseshpy SessionManager.")
            
            org_drop = study_data.get('drop', 10)
            org_interval = study_data.get("interval", 15)
            
            await self.session_manager.process(
                member=member,
                before=before,
                after=after,
                session_category_id=category_id,
                ignore_channel_id=create_vc_id,
                exceptions_handler=self.exceptions,
                routine_drop_amount=org_drop,
                routine_callback_mean_time=org_interval
            )

            # If user left a channel that is in the study category (and not create_vc)
            if before.channel and str(getattr(before.channel, 'category_id', '')) == category_id and str(before.channel.id) != create_vc_id:
                # Delete it if it's empty
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                        self.session_manager.active_sessions.pop(str(before.channel.id), None)
                        db["sessions"].delete_one({"_id": str(before.channel.id)})
                        log.process(status_code=75, message="Delete VC", details="Deleted empty study VC.")
                    except discord.Forbidden:
                        log.process(status_code=-100, message="Forbidden", details="Missing permissions to delete VC.")
                    except Exception as e:
                        log.process(status_code=-100, message="Error", details=f"Failed to delete empty VC: {e}")
            
            log.complete(status_code=100, message="Handled", details="State change handled by SessionManager.")
            log.send()

        except Exception:
            log.error(status_code=-100, message="Error", details=traceback.format_exc())
            log.send()



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

            domain = os.getenv("WEBSITE_DOMAIN")
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
            if cmd.startswith('hehe'):
                await inter.channel.send(cmd[5:])
                await inter.response.send_message('Done', ephemeral=True)
                return
            elif cmd == 'update lb':
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

    @app_commands.command(name="vcset", description="Configure study VC drop settings")
    @app_commands.guild_only()
    @app_commands.describe(
        interval="Minutes between each drop routine",
        drop_amount="Base drop amount for wood rewards",
    )
    async def vcset(self, inter: discord.Interaction, interval: int = None, drop_amount: int = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            server_id = str(inter.guild_id)
            update = {}
            if interval is not None:
                update["interval"] = interval
            if drop_amount is not None:
                update["drop"] = drop_amount

            if not update:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="Provide at least one setting to update.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            serverCollection.update_one(
                {"_id": server_id},
                {"$set": update},
                upsert=True,
            )

            embed = discord.Embed(
                title="VC Settings Updated",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            if interval is not None:
                embed.add_field(name="Interval", value=f"{interval} min", inline=True)
            if drop_amount is not None:
                embed.add_field(name="Drop Amount", value=drop_amount, inline=True)

            await inter.response.send_message(embed=embed, delete_after=20)
            cmdLog.process(status_code=100, name="Executed", details="VC settings updated.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="boostvc", description="Boost the current study VC with XP")
    @app_commands.guild_only()
    async def boostvc(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            server_id = str(inter.guild_id)
            study_data = serverCollection.find_one({"_id": server_id})
            if not study_data or "category" not in study_data:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="No study configuration found for this server.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            category_id = str(study_data["category"])
            if not inter.user.voice or not inter.user.voice.channel:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You need to be in a study VC to boost it.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            channel_id = str(inter.user.voice.channel.id)
            if str(inter.user.voice.channel.category_id) != category_id:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You are not in a study VC.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            session_doc = db["sessions"].find_one({"_id": channel_id})
            if not session_doc:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="No active session found for this VC.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            current_xp = session_doc.get("vc_xp", 0)
            current_level = session_doc.get("vc_level", 1)

            xp_gain = random.randint(5, 15)
            new_xp = current_xp + xp_gain

            level_up = False
            new_level = current_level
            xp_needed = current_level * 50
            if new_xp >= xp_needed:
                new_xp -= xp_needed
                new_level = current_level + 1
                level_up = True

            db["sessions"].update_one(
                {"_id": channel_id},
                {"$set": {"vc_xp": new_xp, "vc_level": new_level}},
            )

            if channel_id in self.session_manager.active_sessions:
                sess = self.session_manager.active_sessions[channel_id]
                sess.vc_xp = new_xp
                sess.vc_level = new_level

            embed = discord.Embed(
                title="🚀 VC Boosted!",
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )
            embed.add_field(name="XP Gained", value=f"+{xp_gain}", inline=True)
            embed.add_field(name="Total XP", value=str(new_xp), inline=True)
            embed.add_field(name="VC Level", value=str(new_level), inline=True)

            if level_up:
                embed.description = "⭐ **LEVEL UP!** The mean of rewards has increased!"
                embed.add_field(name="Effect", value="Reward mean increased — wood drops will be larger on average!", inline=False)

            embed.add_field(
                name="How It Works",
                value="Level → higher **mean** reward  •  XP → tighter **variance** (more consistent drops)",
                inline=False,
            )

            await inter.response.send_message(embed=embed, delete_after=30)
            cmdLog.process(status_code=100, name="Executed", details=f"VC boosted: +{xp_gain} XP (Level {new_level}).")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)
