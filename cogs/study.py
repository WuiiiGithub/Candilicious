import discord, os, asyncio, pymongo, traceback, json, io, qrcode, random, secrets
import config
from dotenv import load_dotenv
from datetime import (
    datetime, 
    timedelta, 
    timezone
)
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, Union
from library.templates import *
from library.logging import *
from library.session import *
from library.leaderboard import *

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))[config.DB_NAME]
serverCollection = db["servers"]
userCollection = db["users"]
boardsCollection = db["boards"]
exceptionCollection = db["exception"]
exceptionCollection.create_index("expiresAt", expireAfterSeconds=0)
dropsCollection = db["drop.offers"]
try:
    dropsCollection.drop_index("created_at_1")
except pymongo.errors.OperationFailure:
    pass
try:
    dropsCollection.drop_index("expire_at_1")
except pymongo.errors.OperationFailure:
    pass
dropsCollection.create_index("expire_at", expireAfterSeconds=0)
activitySessionCollection = db["session.logs"]

from library import dseshpy
from library.recovery import RecoveryManager
dseshpy.initialize(
    session_collection=db["sessions"],
    user_collection=userCollection,
    drops_collection=db["drop.offers"],
    activity_session_collection=activitySessionCollection,
    config_collection=db["config"]
)

# ===================== CONFIG UI =====================

def build_config_embed(server_data: dict, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="\u2699\ufe0f Server Configuration",
        description="Select a section below to configure.",
        color=config.msgColor,
        timestamp=datetime.now(),
    )

    category_id = server_data.get("category")
    create_vc_id = server_data.get("create_vc")

    study_ch = "\u2705" if category_id and create_vc_id else "\u274c"
    category_val = f"<#{category_id}>" if category_id else "Not set"
    create_vc_val = f"<#{create_vc_id}>" if create_vc_id else "Not set"

    embed.add_field(
        name=f"{study_ch} Study Channel Setup",
        value=f"**Category:** {category_val}\n**Create VC:** {create_vc_val}",
        inline=False,
    )

    reminders = server_data.get("reminders", {}) or {}
    rem_ch = "\u2705" if reminders.get("channel") else "\u274c"
    rem_channel_val = f"<#{reminders['channel']}>" if reminders.get("channel") else "Not set"
    rem_time_val = f"{reminders.get('time')} min" if reminders.get("time") else "Not set"
    rem_text_val = reminders.get("text", "Not set") or "Not set"

    embed.add_field(
        name=f"{rem_ch} Reminder Setup",
        value=f"**Channel:** {rem_channel_val}\n**Time:** {rem_time_val}\n**Text:** {rem_text_val}",
        inline=False,
    )

    return embed


class ConfigModal(ui.Modal, title="Reminder Settings"):
    def __init__(self, current: dict):
        super().__init__()
        current = current or {}
        self.add_item(ui.TextInput(
            label="Reminder Interval (minutes)",
            placeholder="e.g. 60",
            default=str(current.get("time", "")) if current.get("time") else "",
            required=True,
            max_length=4,
        ))
        self.add_item(ui.TextInput(
            label="Footer Text",
            placeholder="e.g. Keep studying!",
            default=current.get("text", ""),
            required=False,
            max_length=100,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        server_id = str(interaction.guild_id)
        time_val = int(self.children[0].value)
        text_val = self.children[1].value or ""
        serverCollection.update_one(
            {"_id": server_id},
            {"$set": {"reminders.time": time_val, "reminders.text": text_val}},
        )
        rem_cog = interaction.client.get_cog("Reminders")
        if rem_cog:
            await rem_cog.refresh_reminders_cache()

        server_data = serverCollection.find_one({"_id": server_id}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class DegradationModal(ui.Modal, title="Degradation Rates"):
    def __init__(self):
        super().__init__()
        rates = db["config"].find_one({"_id": "degradation_rates"}) or {}
        self.add_item(ui.TextInput(
            label="Wood Degradation (% per day)",
            placeholder="e.g. 5",
            default=str(round(rates.get("wood", 0.05) * 100, 1)) if rates.get("wood") else "5",
            required=True,
            max_length=4,
        ))
        self.add_item(ui.TextInput(
            label="Iron Degradation (% per day)",
            placeholder="e.g. 3",
            default=str(round(rates.get("iron", 0.03) * 100, 1)) if rates.get("iron") else "3",
            required=True,
            max_length=4,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        wood_rate = float(self.children[0].value) / 100.0
        iron_rate = float(self.children[1].value) / 100.0
        db["config"].update_one(
            {"_id": "degradation_rates"},
            {"$set": {"wood": wood_rate, "iron": iron_rate}},
            upsert=True,
        )
        embed = discord.Embed(
            title="\U0001f4c9 Degradation Rates Updated",
            description=f"\U0001fab5 Wood: {round(wood_rate * 100, 1)}%/day\n\U0001f529 Iron: {round(iron_rate * 100, 1)}%/day",
            color=config.msgColor,
        )
        await interaction.response.edit_message(embed=embed, view=None)


class ChannelSelectMenu(ui.ChannelSelect):
    def __init__(self, channel_types: list, target: str):
        self.target = target
        super().__init__(
            placeholder="Select a channel...",
            channel_types=channel_types,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        server_id = str(interaction.guild_id)

        if self.target == "category":
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"category": str(selected.id)}},
                upsert=True,
            )
        elif self.target == "create_vc":
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"create_vc": str(selected.id)}},
                upsert=True,
            )
        elif self.target == "reminder_channel":
            server_data = serverCollection.find_one({"_id": server_id}) or {}
            reminders = server_data.get("reminders", {}) or {}
            reminders["channel"] = str(selected.id)
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"reminders": reminders}},
            )
            rem_cog = interaction.client.get_cog("Reminders")
            if rem_cog:
                await rem_cog.refresh_reminders_cache()

        server_data = serverCollection.find_one({"_id": server_id}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class ChannelPickView(ui.View):
    def __init__(self, server_data: dict, guild: discord.Guild, bot, target: str):
        super().__init__(timeout=120)
        self.server_data = server_data
        self.guild = guild
        self.bot = bot
        self.target = target
        channel_types = [discord.ChannelType.category] if target == "category" else [discord.ChannelType.voice]
        self.add_item(ChannelSelectMenu(channel_types, target))

    @ui.button(label="\u2190 Back", style=discord.ButtonStyle.grey, row=1)
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class CreateVCSelect(ui.Select):
    def __init__(self, vcs: list):
        opts = [discord.SelectOption(label=ch.name, value=str(ch.id), description=f"ID: {ch.id}") for ch in vcs]
        super().__init__(placeholder="Choose a voice channel...", options=opts, row=0)

    async def callback(self, interaction: discord.Interaction):
        server_id = str(interaction.guild_id)
        serverCollection.update_one(
            {"_id": server_id},
            {"$set": {"create_vc": self.values[0]}},
            upsert=True,
        )
        server_data = serverCollection.find_one({"_id": server_id}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class CreateVCSelectView(ui.View):
    def __init__(self, vcs: list, server_data: dict, guild: discord.Guild, bot):
        super().__init__(timeout=120)
        self.add_item(CreateVCSelect(vcs))

    @ui.button(label="\u2190 Back", style=discord.ButtonStyle.grey, row=1)
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class ConfigSelect(ui.Select):
    def __init__(self, server_data: dict):
        options = [
            discord.SelectOption(
                label="Study Channel Setup",
                value="study",
                emoji="\U0001f4c1",
                description="Configure VC category, drops, interval",
            ),
            discord.SelectOption(
                label="Reminder Setup",
                value="reminder",
                emoji="\u23f0",
                description="Configure study reminders",
            ),
            discord.SelectOption(
                label="Delete Configuration",
                value="delete",
                emoji="\u274c",
                description="Delete server or user data",
            ),
            discord.SelectOption(
                label="Degradation Rates",
                value="degradation",
                emoji="\U0001f4c9",
                description="Set resource degradation rates",
            ),
        ]
        super().__init__(placeholder="Select a section to configure...", options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        server_id = str(interaction.guild_id)
        server_data = serverCollection.find_one({"_id": server_id}) or {}
        view = self.view

        if value == "study":
            embed = discord.Embed(
                title="\U0001f4c1 Study Channel Setup",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            study_embed = build_config_embed(server_data, interaction.guild)
            category_f = study_embed.fields[0].value if study_embed.fields else ""
            embed.description = f"**Current Settings:**\n{category_f}"
            edit_view = ActionView("study", server_data, interaction.guild, interaction.client)
            await interaction.response.edit_message(embed=embed, view=edit_view)

        elif value == "reminder":
            embed = discord.Embed(
                title="\u23f0 Reminder Setup",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            study_embed = build_config_embed(server_data, interaction.guild)
            rem_f = study_embed.fields[1].value if len(study_embed.fields) > 1 else ""
            embed.description = f"**Current Settings:**\n{rem_f}"
            edit_view = ActionView("reminder", server_data, interaction.guild, interaction.client)
            await interaction.response.edit_message(embed=embed, view=edit_view)

        elif value == "degradation":
            rates_doc = db["config"].find_one({"_id": "degradation_rates"}) or {}
            wood_rate = rates_doc.get("wood", 0.05)
            iron_rate = rates_doc.get("iron", 0.03)
            embed = discord.Embed(
                title="\U0001f4c9 Degradation Rates",
                description=f"Resources degrade over time when not being earned.\n\n"
                f"\U0001fab5 **Wood:** {round(wood_rate * 100, 1)}%/day\n"
                f"\U0001f529 **Iron:** {round(iron_rate * 100, 1)}%/day",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            edit_view = ActionView("degradation", server_data, interaction.guild, interaction.client)
            await interaction.response.edit_message(embed=embed, view=edit_view)

        elif value == "delete":
            embed = discord.Embed(
                title="\u274c Delete Configuration",
                description="Choose an option below:",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            edit_view = ActionView("delete", server_data, interaction.guild, interaction.client)
            await interaction.response.edit_message(embed=embed, view=edit_view)


class ConfigView(ui.View):
    def __init__(self, server_data: dict, guild: discord.Guild, bot):
        super().__init__(timeout=180)
        self.server_data = server_data
        self.guild = guild
        self.bot = bot
        self.add_item(ConfigSelect(server_data))

    @ui.button(label="Exit", style=discord.ButtonStyle.red, row=1)
    async def exit(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=None)


class SubActionSelect(ui.Select):
    def __init__(self, section: str):
        if section == "study":
            opts = [
                discord.SelectOption(label="Set Category", value="category", emoji="\U0001f4c2", description="Choose the category for study VCs"),
                discord.SelectOption(label="Set Create VC", value="create_vc", emoji="\U0001f50a", description="Choose the join-to-study voice channel"),
            ]
        elif section == "reminder":
            opts = [
                discord.SelectOption(label="Set Channel", value="channel", emoji="#\uFE0F\u20E3", description="Choose the reminder channel"),
                discord.SelectOption(label="Set Time & Text", value="time_text", emoji="\u270f\ufe0f", description="Edit reminder interval and footer text"),
            ]
        elif section == "degradation":
            opts = [
                discord.SelectOption(label="Edit Degradation Rates", value="edit_rates", emoji="\U0001f4c8", description="Change wood and iron degradation rates"),
            ]
        elif section == "delete":
            opts = [
                discord.SelectOption(label="Delete Study Config", value="delete_study", emoji="\U0001f4c2", description="Remove study category and create VC"),
                discord.SelectOption(label="Delete Reminder Config", value="delete_reminder", emoji="\u23f0", description="Remove reminder channel, interval, and text"),
                discord.SelectOption(label="Delete All Config", value="delete_all", emoji="\U0001f5d1\ufe0f", description="Remove all server settings"),
            ]
        else:
            opts = []
        super().__init__(placeholder="Choose an action...", options=opts, row=0)
        self.section = section

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        server_id = str(interaction.guild_id)
        server_data = serverCollection.find_one({"_id": server_id}) or {}

        if self.section == "study":
            if value == "category":
                view = ChannelPickView(server_data, interaction.guild, interaction.client, target="category")
                embed = discord.Embed(title="Select Category", description="Choose the category where study VCs will be created.", color=config.msgColor)
                await interaction.response.edit_message(embed=embed, view=view)
            elif value == "create_vc":
                category_id = server_data.get("category")
                if not category_id:
                    embed = discord.Embed(title="No Category Set", description="Please configure a study category first before selecting a Create VC.", color=config.msgColor)
                    await interaction.response.edit_message(embed=embed, view=ActionView("study", server_data, interaction.guild, interaction.client))
                    return
                category = interaction.guild.get_channel(int(category_id))
                vcs = category.voice_channels if category else []
                if not vcs:
                    embed = discord.Embed(title="No Voice Channels", description=f"There are no voice channels in {category.mention if category else 'the study category'}. Please create one first.", color=config.msgColor)
                    await interaction.response.edit_message(embed=embed, view=ActionView("study", server_data, interaction.guild, interaction.client))
                    return
                view = CreateVCSelectView(vcs, server_data, interaction.guild, interaction.client)
                embed = discord.Embed(title="Select Create VC", description=f"Choose a voice channel from {category.mention}:", color=config.msgColor)
                await interaction.response.edit_message(embed=embed, view=view)

        elif self.section == "reminder":
            if value == "channel":
                view = ChannelPickView(server_data, interaction.guild, interaction.client, target="reminder_channel")
                embed = discord.Embed(title="Select Reminder Channel", description="Choose the channel for study reminders.", color=config.msgColor)
                await interaction.response.edit_message(embed=embed, view=view)
            elif value == "time_text":
                reminders = server_data.get("reminders", {}) or {}
                modal = ConfigModal(reminders)
                await interaction.response.send_modal(modal)

        elif self.section == "degradation":
            if value == "edit_rates":
                modal = DegradationModal()
                await interaction.response.send_modal(modal)

        elif self.section == "delete":
            if not interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message("You need **Manage Server** permission.", ephemeral=True)

            await interaction.response.defer()

            if value == "delete_study":
                data = {k: server_data.get(k) for k in ("category", "create_vc") if k in server_data}
                serverCollection.update_one({"_id": server_id}, {"$unset": {"category": "", "create_vc": ""}})
                title = "\u2705 Study Config Deleted"
            elif value == "delete_reminder":
                data = {"reminders": server_data.get("reminders", {})}
                serverCollection.update_one({"_id": server_id}, {"$unset": {"reminders": ""}})
                title = "\u2705 Reminder Config Deleted"
            elif value == "delete_all":
                data = server_data
                serverCollection.delete_one({"_id": server_id})
                title = "\u2705 All Config Deleted"
            else:
                return

            file = discord.File(io.BytesIO(json.dumps(data, indent=4).encode()), "backup.json")
            await interaction.followup.send("Here is your data backup:", file=file, ephemeral=True)
            embed = discord.Embed(title=title, color=config.msgColor)
            await interaction.edit_original_response(embed=embed, view=None)


class ActionView(ui.View):
    def __init__(self, section: str, server_data: dict, guild: discord.Guild, bot):
        super().__init__(timeout=180)
        self.add_item(SubActionSelect(section))

    @ui.button(label="\u2190 Back", style=discord.ButtonStyle.grey, row=1)
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)

    @ui.button(label="Exit", style=discord.ButtonStyle.red, row=1)
    async def exit(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=None)


class Study(commands.Cog):
    def __init__(self, bot):
        # general vars
        self.bot = bot

        # study vc vars
        self.exceptions = tempDataHandler()
        event_bus = getattr(bot, 'event_bus', None)
        self.session_manager = dseshpy.session.SessionManager(event_bus=event_bus)
        bot.session_manager = self.session_manager

        # recovery
        self.recovery = RecoveryManager(
            db=db,
            session_manager=self.session_manager,
            event_bus=event_bus,
            bot=bot,
        )
        bot.recovery = self.recovery

        cogLog.log_cog(action="starting", status_code=0, details="Study Cog has been initialized and is ready for use.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        print("[Study] on_ready fired", flush=True)
        try:
            log.process(status_code=0, message="Syncing", details="Trying to sync with Bot Tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Success", details="Bot Tree has been successfully synced.")
        except Exception:
            log.error(status_code=-100, message="Error", details=traceback.format_exc())
        finally:
            log.send()

        try:
            print("[Study] Waiting 3s for guilds to populate...", flush=True)
            # Wait for guild voice states to populate before recovery
            await asyncio.sleep(3)
            await self.recovery.recover()
            self.recovery.start_snapshot_task(interval_minutes=5)
        except Exception:
            import traceback as _tb
            print(f"[Recovery] FATAL recovery error: {_tb.format_exc()}", flush=True)

    @app_commands.command(name="config", description="Configure server settings")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def config(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name='Waiting', details="Fetching server configuration...")
            server_data = serverCollection.find_one({"_id": str(inter.guild_id)}) or {}
            embed = build_config_embed(server_data, inter.guild)
            view = ConfigView(server_data, inter.guild, self.bot)
            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name='Executed', details="Config panel displayed.")
        except Exception as e:
            cmdLog.process(status_code=-100, name='Error', details=traceback.format_exc())
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
                routine_callback_mean_time=org_interval,
            )

            # If user left a channel that is in the study category (and not create_vc)
            if before.channel and str(getattr(before.channel, 'category_id', '')) == category_id and str(before.channel.id) != create_vc_id:
                # Delete it if it's empty
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                        old_ch_id = str(before.channel.id)
                        sid = self.session_manager.channel_sessions.get(old_ch_id)
                        if sid:
                            sess = self.session_manager.active_sessions.get(sid)
                            if sess and len(sess.members) > 0:
                                sess.channel_id = f"w{sess.owner_id}"
                                sess.guild_id = "web"
                                self.session_manager.sync(sess)
                                if old_ch_id in self.session_manager.channel_sessions:
                                    del self.session_manager.channel_sessions[old_ch_id]
                                self.session_manager.channel_sessions[sess.channel_id] = sid
                            elif sess:
                                self.session_manager._cleanup_session(sess)
                            else:
                                sess_data = db["sessions"].find_one({"session_id": sid})
                                if sess_data:
                                    u_col = db["users"]
                                    for uid in sess_data.get("members", {}):
                                        u_col.update_one(
                                            {"_id": uid, "current_session": sid},
                                            {"$unset": {"current_session": ""}}
                                        )
                                db["sessions"].delete_one({"session_id": sid})
                                for uid, usid in list(self.session_manager.user_sessions.items()):
                                    if usid == sid:
                                        del self.session_manager.user_sessions[uid]
                                if old_ch_id in self.session_manager.channel_sessions:
                                    del self.session_manager.channel_sessions[old_ch_id]
                        log.process(status_code=75, message="Delete VC", details="Deleted empty study VC.")
                    except discord.Forbidden:
                        log.error(status_code=-100, message="Forbidden", details="Missing permissions to delete VC.")
                    except Exception as e:
                        log.error(status_code=-100, message="Error", details=f"Failed to delete empty VC: {e}")
            
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
            cmdLog.process(status_code=0, name='Waiting', details="Fetching leaderboard data...")

            if scope == 0:
                await inter.response.send_message("The Leaderboard command is still under development!", ephemeral=True)
                cmdLog.process(status_code=50, name="Pending")
                return

            guild_id = str(inter.guild_id)
            user_id = str(inter.user.id)

            total_count = userCollection.count_documents({f"servers.{guild_id}.time": {"$gt": 0}})

            if total_count < 3:
                await inter.response.send_message(
                    embed=discord.Embed(description="Not enough users to rank. Need at least 3.", color=config.msgColor),
                    delete_after=30
                )
                cmdLog.process(status_code=100, name="Not enough users")
                return

            pipeline = [
                {"$match": {f"servers.{guild_id}.time": {"$gt": 0}}},
                {"$project": {
                    "_id": 1,
                    "name": {"$ifNull": ["$name", "$_id"]},
                    "display_name": {"$ifNull": ["$display_name", "$name", "$_id"]},
                    "pfp": {"$ifNull": ["$pfp", ""]},
                    "time": {"$ifNull": [f"$servers.{guild_id}.time", 0]},
                }},
                {"$sort": {"time": -1}},
            ]
            all_users = list(userCollection.aggregate(pipeline))

            for i, u in enumerate(all_users):
                u["_rank"] = i + 1

            user_rank = None
            for u in all_users:
                if u["_id"] == user_id:
                    user_rank = u["_rank"]
                    break

            top3 = all_users[:3]

            if total_count <= 10 or user_rank is None or user_rank <= 10:
                rows = all_users[3:10]
            else:
                start = max(3, user_rank - 7)
                end = min(len(all_users), start + 7)
                rows = all_users[start:end]

            user_data = userCollection.find_one({"_id": user_id}, {"premium.type": 1})
            is_premium = user_data.get("premium", {}).get("type") == "pro" if user_data else False

            if is_premium:
                await inter.response.defer()

                def fmt_time(seconds):
                    m = seconds // 60
                    h = seconds // 3600
                    m = m % 60
                    return f"{int(h)}h {int(m)}m"

                podium_data = []
                for u in top3:
                    podium_data.append({
                        "rank": u["_rank"],
                        "name": u.get(view, "Unknown"),
                        "time": fmt_time(u["time"]),
                        "avatar_url": u.get("pfp", ""),
                    })

                rows_data = []
                for u in rows:
                    rows_data.append({
                        "rank": u["_rank"],
                        "name": u.get(view, "Unknown"),
                        "time": fmt_time(u["time"]),
                        "avatar_url": u.get("pfp", ""),
                    })

                lb_data = {"podium": podium_data, "rows": rows_data}
                image_data = await getNovaLeaderboard(lb_data, "gold")

                if image_data:
                    file = discord.File(fp=image_data, filename="leaderboard.webp")
                    await inter.followup.send(file=file)
                    cmdLog.process(status_code=100, name="Executed", details="Image leaderboard delivered.")
                else:
                    await inter.followup.send("Failed to generate leaderboard image.")
                    cmdLog.process(status_code=-100, name="Failed", details="Image generation failed.")
            else:
                toppers = top3 + rows
                await inter.response.send_message(
                    embed=discord.Embed(
                        description=leaderboard_template(toppers=toppers, view=view),
                        color=config.msgColor
                    ),
                    delete_after=30
                )
                cmdLog.process(status_code=100, name="Executed", details="Text leaderboard delivered.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.guild_only()
    @app_commands.command(
        name="delete", description="Request deletion of your data"
    )
    async def delete(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="\U0001f4ac Data Deletion Request",
            description="To delete your personal data, please join the **Candilicious** support server and open a ticket.\n\n**[Join Candilicious Server](https://discord.gg/candilicious)**",
            color=config.msgColor,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

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

            elif cmd == 'sync':
                await inter.response.send_message("Syncing all users with Discord...", ephemeral=True)

                all_users = list(userCollection.find({}, {"_id": 1}))
                cmdLog.process(status_code=50, name="Ready", details=f"Found {len(all_users)} total users to sync.")

                bulk_ops = []
                count = 0
                failed = 0

                for doc in all_users:
                    user_id = doc['_id']
                    try:
                        user = await inter.client.fetch_user(int(user_id))
                        bulk_ops.append(pymongo.UpdateOne(
                            {"_id": user_id},
                            {"$set": {
                                "name": user.name,
                                "display_name": user.display_name,
                                "pfp": user.display_avatar.url,
                            }},
                            upsert=True
                        ))
                        count += 1
                    except Exception:
                        failed += 1
                        continue

                    if count % 10 == 0:
                        await asyncio.sleep(1)

                if bulk_ops:
                    result = userCollection.bulk_write(bulk_ops)
                    await inter.followup.send(
                        f"Sync complete!\n- Users updated: {result.modified_count}\n- Users upserted: {result.upserted_count}\n- Failed: {failed}",
                        ephemeral=True
                    )
                    cmdLog.process(status_code=100, name="Executed", details=f"Sync complete: {result.modified_count} updated, {failed} failed.")
                else:
                    await inter.followup.send("No users to sync.", ephemeral=True)
                    cmdLog.process(status_code=-25, name="Failed", details="No users synced.")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name='balance', description='Check your resource balance')
    async def balance(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name="Waiting", details="Fetching user balance...")
            user_id = str(inter.user.id)
            user_data = userCollection.find_one({"_id": user_id})
            if not user_data:
                return await inter.response.send_message(
                    embed=discord.Embed(description="No balance data yet.\nJoin a study VC and collect drops to start earning!", color=config.msgColor),
                    ephemeral=True,
                )

            resources = user_data.get("economy", {}).get("resources", {})
            wood_data = resources.get("wood", {})
            iron_data = resources.get("iron", {})

            rates_doc = db["config"].find_one({"_id": "degradation_rates"}) or {}
            wood_rate = rates_doc.get("wood", 0.05)
            iron_rate = rates_doc.get("iron", 0.03)

            from library import degrade
            wood_amount, wood_dt = degrade.apply(wood_data.get("amount", 0), wood_data.get("degraded_at"), wood_rate)
            iron_amount, iron_dt = degrade.apply(iron_data.get("amount", 0), iron_data.get("degraded_at"), iron_rate)

            userCollection.update_one(
                {"_id": user_id},
                {"$set": {
                    "economy.resources.wood.amount": wood_amount,
                    "economy.resources.wood.degraded_at": wood_dt,
                    "economy.resources.iron.amount": iron_amount,
                    "economy.resources.iron.degraded_at": iron_dt,
                }}
            )

            wood_pct = round(wood_rate * 100, 1)
            iron_pct = round(iron_rate * 100, 1)

            embed = discord.Embed(
                title=f"\U0001f4b0 {inter.user.display_name}'s Balance",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            embed.add_field(
                name="Raw Resources",
                value=f"\U0001fab5 Wood: `{wood_amount:,}`\n\U0001f529 Iron: `{iron_amount:,}`",
                inline=False
            )
            embed.add_field(name="Degradation" , value=f"Wood: `{wood_pct}%/day`\nIron: `{iron_pct}%/day`", inline=False)

            await inter.response.send_message(embed=embed)
            cmdLog.process(status_code=100, name="Executed", details="Balance displayed.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="vcset", description="Configure study VC settings")
    @app_commands.guild_only()
    @app_commands.describe(
        name="Rename the study voice channel",
        status="Set the channel status message (small text under VC name)",
        session_type="Restrict which activity types are allowed in the VC",
    )
    @app_commands.choices(session_type=[
        app_commands.Choice(name="All Types Allowed", value="*"),
        app_commands.Choice(name="CAM Only", value="cam"),
        app_commands.Choice(name="Screen Share Only", value="ss"),
        app_commands.Choice(name="CAM or Screen Share Allowed", value="cam+ss"),
        app_commands.Choice(name="CAM & Screen Share Allowed", value="cam&ss"),
        app_commands.Choice(name="CAM or No Activity Allowed", value="cam+noact"),
        app_commands.Choice(name="Screen Share or No Activity Allowed", value="ss+noact"),
    ])
    async def vcset(self, inter: discord.Interaction, name: str = None, status: str = None, session_type: str = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            server_id = str(inter.guild_id)

            def _find_session_by_channel(ch_id: str):
                sid = self.session_manager.channel_sessions.get(ch_id)
                if sid:
                    return self.session_manager.active_sessions.get(sid)
                for sess in self.session_manager.active_sessions.values():
                    if sess.channel_id == ch_id:
                        return sess
                return None

            if name is None and status is None and session_type is None:
                if inter.user.voice:
                    session = _find_session_by_channel(str(inter.user.voice.channel.id))
                    if session:
                        channel = inter.user.voice.channel
                        type_names = {
                            "*": "All Types Allowed",
                            "cam": "CAM Only",
                            "ss": "Screen Share Only",
                            "cam+ss": "CAM or Screen Share Allowed",
                            "cam&ss": "CAM & Screen Share Allowed",
                            "cam+noact": "CAM or No Activity Allowed",
                            "ss+noact": "Screen Share or No Activity Allowed",
                        }
                        embed = discord.Embed(
                            title="Current VC Configuration",
                            color=config.msgColor,
                            timestamp=datetime.now(),
                        )
                        embed.add_field(name="Name", value=channel.name, inline=True)
                        embed.add_field(name="Status", value=channel.status or "\u200b", inline=True)
                        embed.add_field(name="Session Type", value=type_names.get(session.session_type, session.session_type), inline=False)
                        await inter.response.send_message(embed=embed, ephemeral=True, delete_after=30)
                        return

                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You are not in a study VC.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            if inter.user.voice:
                session = _find_session_by_channel(str(inter.user.voice.channel.id))
                if session:
                    if str(inter.user.id) != session.owner_id:
                        await inter.response.send_message(
                            embed=discord.Embed(
                                description="You are not the session owner.",
                                color=config.msgColor,
                            ),
                            ephemeral=True, delete_after=10,
                        )
                        return

            embed = discord.Embed(
                title="VC Settings Updated",
                color=config.msgColor,
                timestamp=datetime.now(),
            )

            if session_type is not None and inter.user.voice:
                session = _find_session_by_channel(str(inter.user.voice.channel.id))
                if session:
                    session.update_settings(session_type=session_type)
                    self.session_manager.sync(session)

                    channel = inter.user.voice.channel
                    category_id = str(channel.category_id) if channel.category_id else None
                    non_compliant = []
                    for vc_member in channel.members:
                        if vc_member.bot:
                            continue
                        act_type = dseshpy.session._get_activity_type(vc_member.voice)
                        if not session._is_allowed(act_type):
                            non_compliant.append(vc_member)
                            if str(vc_member.id) not in session.monitor_tasks:
                                task = asyncio.create_task(
                                    session.activity_monitor(
                                        vc_member, self.exceptions,
                                        category_id, None
                                    )
                                )
                                session.monitor_tasks[str(vc_member.id)] = task

                    if non_compliant:
                        mentions = " ".join(m.mention for m in non_compliant)
                        await channel.send(
                            content=mentions,
                            embed=discord.Embed(
                                description=f"\u26a0\ufe0f This VC now requires **{session._type_description()}**. "
                                f"Turn on the required devices within 5 minutes or you'll be removed.",
                                color=0x3498DB,
                            ),
                            delete_after=30,
                        )

                    type_names = {
                        "*": "All Types Allowed",
                        "cam": "CAM Only",
                        "ss": "Screen Share Only",
                        "cam+ss": "CAM or Screen Share Allowed",
                        "cam&ss": "CAM & Screen Share Allowed",
                        "cam+noact": "CAM or No Activity Allowed",
                        "ss+noact": "Screen Share or No Activity Allowed",
                    }
                    embed.add_field(name="Session Type", value=type_names.get(session_type, session_type), inline=True)

            if inter.user.voice:
                channel = inter.user.voice.channel
                if name is not None:
                    await channel.edit(name=name)
                    embed.add_field(name="Name", value=name, inline=True)
                if status is not None:
                    await channel.edit(status=status)
                    embed.add_field(name="Status", value=status, inline=True)

            await inter.response.send_message(embed=embed, delete_after=20)
            cmdLog.process(status_code=100, name="Executed", details="VC settings updated successfully.")
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

            sid = self.session_manager.channel_sessions.get(channel_id)
            session_doc = None
            if sid:
                session_doc = db["sessions"].find_one({"session_id": sid})
            if not session_doc:
                session_doc = db["sessions"].find_one({"channel_id": channel_id})
            if not session_doc:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="No active session found for this VC.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            session_id = session_doc.get("session_id")
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
                {"session_id": session_id},
                {"$set": {"vc_xp": new_xp, "vc_level": new_level}},
            )

            if session_id in self.session_manager.active_sessions:
                sess = self.session_manager.active_sessions[session_id]
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

    @app_commands.command(name='join', description='Join a study session by session ID.')
    @app_commands.describe(session_id='The 16-char session ID to join')
    async def join_session_cmd(self, inter: discord.Interaction, session_id: str):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name='Waiting', details=f"Looking up session {session_id}...")

            session_doc = db["sessions"].find_one({"session_id": session_id})
            if not session_doc:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="Session not found. Double-check the session ID and try again.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=15,
                )
                cmdLog.process(status_code=-100, name="Not Found", details="Session ID not found in DB.")
                cmdLog.send()
                return

            channel_id = session_doc.get("channel_id", "")
            guild_id = session_doc.get("guild_id", "")

            if channel_id.startswith("w"):
                domain = os.getenv("WEBSITE_DOMAIN", "")
                if domain and not domain.endswith("/"):
                    domain += "/"
                desc = "This is a **web-only session** — there is no Discord voice channel to join."
                if domain:
                    desc += f"\n\nJoin via the web app: [**Open Session**]({domain})"
                await inter.response.send_message(
                    embed=discord.Embed(
                        description=desc,
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True, delete_after=30,
                )
                cmdLog.process(status_code=50, name="Web Only", details="Session is web-only, directed user to web.")
                cmdLog.send()
                return

            if not inter.user.voice or not inter.user.voice.channel:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You need to be in a voice channel first. Join any voice channel, then use this command again.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=15,
                )
                cmdLog.process(status_code=-100, name="No Voice", details="User is not in a voice channel.")
                cmdLog.send()
                return

            vc = inter.guild.get_channel(int(channel_id)) if guild_id and guild_id != "web" else None
            if not vc:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="The voice channel for this session no longer exists.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=15,
                )
                cmdLog.process(status_code=-100, name="VC Gone", details=f"Channel {channel_id} not found in guild.")
                cmdLog.send()
                return

            if inter.user.voice.channel.id == int(channel_id):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You're already in this session!",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True, delete_after=10,
                )
                cmdLog.process(status_code=50, name="Already In", details="User is already in the session VC.")
                cmdLog.send()
                return

            try:
                await inter.user.move_to(vc)
            except discord.Forbidden:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="I don't have permission to move you to that channel.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True, delete_after=15,
                )
                cmdLog.process(status_code=-100, name="Forbidden", details="Missing permissions to move user.")
                cmdLog.send()
                return

            members = session_doc.get("members", {})
            member_count = len(members)
            session_type = session_doc.get("session_type", "*")

            desc = f"Welcome to the session!\n\n"
            desc += f"**Members:** {member_count}\n"
            desc += f"**Type:** `{session_type}`"

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Joined Session!",
                    description=desc,
                    color=discord.Color.green(),
                ),
                ephemeral=True, delete_after=15,
            )
            cmdLog.process(status_code=100, name="Joined", details=f"Moved {inter.user.name} to session {session_id}.")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


    @app_commands.command(name='sync', description='Sync config values from database into the running bot')
    async def sync_config(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            await inter.response.defer(ephemeral=True)
            synced = []

            drops_doc = db["config"].find_one({"_id": "drops"})
            if drops_doc:
                for k, v in drops_doc.items():
                    if k != "_id" and hasattr(config, k.upper()):
                        setattr(config, k.upper(), v)
                synced.append("drops")
            else:
                db["config"].update_one(
                    {"_id": "drops"},
                    {"$set": {
                        "collection_time": config.DROP_COLLECTION_TIME,
                        "mean_time": config.DROP_MEAN_TIME,
                        "variance": config.DROP_VARIANCE,
                    }},
                    upsert=True
                )
                synced.append("drops (created)")

            resources_doc = db["config"].find_one({"_id": "resources"})
            resource_defaults = {
                "wood_base_mean": config.RESOURCE_WOOD_BASE_MEAN,
                "wood_base_decay": config.RESOURCE_WOOD_BASE_DECAY,
                "wood_decay_rate": config.RESOURCE_WOOD_DECAY_RATE,
                "wood_std_dev": config.RESOURCE_WOOD_STD_DEV,
                "wood_min": config.RESOURCE_WOOD_MIN,
                "iron_base_mean": config.RESOURCE_IRON_BASE_MEAN,
                "iron_base_decay": config.RESOURCE_IRON_BASE_DECAY,
                "iron_decay_rate": config.RESOURCE_IRON_DECAY_RATE,
                "iron_std_dev": config.RESOURCE_IRON_STD_DEV,
                "iron_min": config.RESOURCE_IRON_MIN,
                "variance_factor_rate": config.RESOURCE_VARIANCE_FACTOR_RATE,
                "variance_factor_min": config.RESOURCE_VARIANCE_FACTOR_MIN,
            }
            if resources_doc:
                cfg_key_map = {
                    "wood_base_mean": "RESOURCE_WOOD_BASE_MEAN",
                    "wood_base_decay": "RESOURCE_WOOD_BASE_DECAY",
                    "wood_decay_rate": "RESOURCE_WOOD_DECAY_RATE",
                    "wood_std_dev": "RESOURCE_WOOD_STD_DEV",
                    "wood_min": "RESOURCE_WOOD_MIN",
                    "iron_base_mean": "RESOURCE_IRON_BASE_MEAN",
                    "iron_base_decay": "RESOURCE_IRON_BASE_DECAY",
                    "iron_decay_rate": "RESOURCE_IRON_DECAY_RATE",
                    "iron_std_dev": "RESOURCE_IRON_STD_DEV",
                    "iron_min": "RESOURCE_IRON_MIN",
                    "variance_factor_rate": "RESOURCE_VARIANCE_FACTOR_RATE",
                    "variance_factor_min": "RESOURCE_VARIANCE_FACTOR_MIN",
                }
                for db_key, cfg_key in cfg_key_map.items():
                    if db_key in resources_doc and hasattr(config, cfg_key):
                        setattr(config, cfg_key, resources_doc[db_key])
                synced.append("resources")
            else:
                db["config"].update_one(
                    {"_id": "resources"},
                    {"$set": resource_defaults},
                    upsert=True
                )
                synced.append("resources (created)")

            auto_cut_doc = db["config"].find_one({"_id": "auto_cut"})
            auto_cut_defaults = {
                "cost": config.PREMIUM_COST,
                "duration_days": config.PREMIUM_TTL_DAYS,
                "unit": config.PREMIUM_UNIT,
            }
            if auto_cut_doc:
                if "cost" in auto_cut_doc:
                    config.PREMIUM_COST = auto_cut_doc["cost"]
                if "duration_days" in auto_cut_doc:
                    config.PREMIUM_TTL_DAYS = auto_cut_doc["duration_days"]
                if "unit" in auto_cut_doc:
                    config.PREMIUM_UNIT = auto_cut_doc["unit"]
                synced.append("auto_cut")
            else:
                db["config"].update_one(
                    {"_id": "auto_cut"},
                    {"$set": auto_cut_defaults},
                    upsert=True
                )
                synced.append("auto_cut (created)")

            await inter.followup.send(f"Synced: {', '.join(synced)}", ephemeral=True)
            cmdLog.process(status_code=100, name="Sync Done", details=f"Synced: {', '.join(synced)}")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
            if not inter.response.is_done():
                await inter.response.send_message("Something went wrong.", ephemeral=True)
        finally:
            cmdLog.send()


async def setup(bot):
    Study_cog = Study(bot)
    await bot.add_cog(Study_cog)
