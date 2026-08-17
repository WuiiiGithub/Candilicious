import discord, os, asyncio, traceback, json, io, qrcode, random, secrets, logging, time
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
from library import is_muted, is_on_holiday, degrade, db
from library.usersync import sync_member_from_discord
import pymongo

filename = __name__.title()
cogLog = CogLogger(filename=filename)
logger = logging.getLogger(__name__)

load_dotenv()

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

# Leaderboard user data is cached briefly so repeated lookups don't pay a
# (possibly slow) MongoDB round-trip every single time.
_lb_users_cache = {}
_LB_USERS_TTL = 30
_LB_USERS_CACHE_MAX = 64

def _get_cached_lb_users(guild_id: str, criterion: str):
    entry = _lb_users_cache.get((guild_id, criterion))
    if entry and time.monotonic() - entry[0] < _LB_USERS_TTL:
        return entry[1]
    return None

def _cache_lb_users(guild_id: str, criterion: str, users: dict):
    if len(_lb_users_cache) >= _LB_USERS_CACHE_MAX:
        _lb_users_cache.clear()
    _lb_users_cache[(guild_id, criterion)] = (time.monotonic(), users)

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

    holiday = server_data.get("holiday") or {}
    role_id = holiday.get("role_id")
    channel_id = holiday.get("channel_id")
    h_ch = "\u2705" if role_id and channel_id else "\u274c"
    role_val = f"<@&{role_id}>" if role_id else "Not set"
    ch_val = f"<#{channel_id}>" if channel_id else "Not set"
    embed.add_field(
        name=f"{h_ch} Holiday Setup",
        value=f"**Role:** {role_val}\n**Channel:** {ch_val}",
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

        elif self.target == "holiday_channel":
            serverCollection.update_one(
                {"_id": server_id},
                {"$set": {"holiday.channel_id": str(selected.id)}},
                upsert=True,
            )
            hcfg = _holiday_config(server_id)
            role_id = hcfg.get("role_id")
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    await apply_holiday_overwrites(interaction.guild, role, selected)

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
        if target == "category":
            channel_types = [discord.ChannelType.category]
        elif target in ("reminder_channel", "holiday_channel"):
            channel_types = [discord.ChannelType.text, discord.ChannelType.news]
        else:
            channel_types = [discord.ChannelType.voice]
        self.add_item(ChannelSelectMenu(channel_types, target))

    @ui.button(label="\u2190 Back", style=discord.ButtonStyle.grey, row=1)
    async def back(self, interaction: discord.Interaction, button: ui.Button):
        server_data = serverCollection.find_one({"_id": str(interaction.guild_id)}) or {}
        embed = build_config_embed(server_data, interaction.guild)
        view = ConfigView(server_data, interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class HolidayRoleSelect(ui.Select):
    def __init__(self, guild: discord.Guild, current_role_id: str | None):
        opts = [
            discord.SelectOption(
                label="\u2795 Create New Role",
                value="create",
                description="Create '🌴 On Holiday' with gold color",
            ),
        ]
        for role in guild.roles:
            if role.is_default() or role >= guild.me.top_role:
                continue
            opts.append(
                discord.SelectOption(
                    label=role.name,
                    value=str(role.id),
                    description=f"ID: {role.id}",
                    default=(str(role.id) == current_role_id),
                )
            )
        super().__init__(placeholder="Choose a role...", options=opts[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        server_id = str(interaction.guild_id)
        guild = interaction.guild

        if value == "create":
            role = await setup_holiday_role(guild)
        else:
            role = guild.get_role(int(value))
            if not role:
                return await interaction.response.send_message("Role not found.", ephemeral=True)

        serverCollection.update_one(
            {"_id": server_id},
            {"$set": {"holiday.role_id": str(role.id)}},
            upsert=True,
        )

        hcfg = _holiday_config(server_id)
        channel_id = hcfg.get("channel_id")
        if channel_id:
            ch = guild.get_channel(int(channel_id))
            if ch:
                await apply_holiday_overwrites(guild, role, ch)

        server_data = serverCollection.find_one({"_id": server_id}) or {}
        embed = build_config_embed(server_data, guild)
        view = ConfigView(server_data, guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class HolidayRoleSelectView(ui.View):
    def __init__(self, server_data: dict, guild: discord.Guild, bot):
        super().__init__(timeout=120)
        holiday = server_data.get("holiday") or {}
        self.add_item(HolidayRoleSelect(guild, holiday.get("role_id")))

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
                label="Holiday Setup",
                value="holiday",
                emoji="\U0001f334",
                description="Configure holiday role and channel",
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

        elif value == "holiday":
            embed = discord.Embed(
                title="\U0001f334 Holiday Setup",
                color=config.msgColor,
                timestamp=datetime.now(),
            )
            holiday_f = study_embed.fields[2].value if len(study_embed.fields) > 2 else ""
            embed.description = f"**Current Settings:**\n{holiday_f}"
            edit_view = ActionView("holiday", server_data, interaction.guild, interaction.client)
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
        elif section == "holiday":
            opts = [
                discord.SelectOption(label="Set Role", value="role", emoji="\U0001f3f4\ufe0f", description="Create or link a holiday role"),
                discord.SelectOption(label="Set Channel", value="channel", emoji="#\uFE0F\u20E3", description="Choose the holiday channel"),
                discord.SelectOption(label="Send Panel", value="panel", emoji="\U0001f4e3", description="Send the holiday panel to the channel"),
                discord.SelectOption(label="Remove Holiday Config", value="delete_holiday", emoji="\u274c", description="Remove holiday role, channel, and panel"),
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

        elif self.section == "holiday":
            perm_err = _require_perms(interaction.guild)
            if perm_err:
                return await interaction.response.send_message(perm_err, ephemeral=True)

            if value == "role":
                view = HolidayRoleSelectView(server_data, interaction.guild, interaction.client)
                embed = discord.Embed(
                    title="\U0001f3f4\ufe0f Holiday Role",
                    description="Choose an existing role or create a new one.",
                    color=config.msgColor,
                )
                await interaction.response.edit_message(embed=embed, view=view)

            elif value == "channel":
                view = ChannelPickView(server_data, interaction.guild, interaction.client, target="holiday_channel")
                embed = discord.Embed(
                    title="#\uFE0F\u20E3 Holiday Channel",
                    description="Choose the text channel for the holiday panel.",
                    color=config.msgColor,
                )
                await interaction.response.edit_message(embed=embed, view=view)

            elif value == "panel":
                hcfg = _holiday_config(interaction.guild_id)
                channel_id = hcfg.get("channel_id")
                if not channel_id:
                    return await interaction.response.send_message(
                        "Set a holiday channel first.", ephemeral=True
                    )
                ch = interaction.guild.get_channel(int(channel_id))
                if not ch:
                    return await interaction.response.send_message(
                        f"Channel <#{channel_id}> not found.", ephemeral=True
                    )
                await interaction.response.defer(ephemeral=True)
                panel_msg_id = await send_holiday_panel(ch)
                if panel_msg_id:
                    serverCollection.update_one(
                        {"_id": server_id},
                        {"$set": {"holiday.panel_message_id": panel_msg_id}},
                    )
                await interaction.followup.send(
                    f"\u2705 Panel sent to {ch.mention}.", ephemeral=True
                )

            elif value == "delete_holiday":
                hcfg = _holiday_config(interaction.guild_id)
                role_id = hcfg.get("role_id")
                if role_id:
                    role = interaction.guild.get_role(int(role_id))
                    if role:
                        try:
                            await role.delete(reason="Holiday config removed")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                serverCollection.update_one(
                    {"_id": server_id}, {"$unset": {"holiday": ""}}
                )
                server_data = serverCollection.find_one({"_id": server_id}) or {}
                embed = build_config_embed(server_data, interaction.guild)
                view = ConfigView(server_data, interaction.guild, interaction.client)
                await interaction.response.edit_message(
                    embed=embed, view=view
                )

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


class EchoModal(ui.Modal, title="Echo"):
    def __init__(self, mode: str, target=None):
        super().__init__()
        self.mode = mode
        self.target = target
        self.add_item(ui.TextInput(
            label="Text",
            placeholder="Enter the text to send...",
            required=True,
            max_length=2000,
            style=discord.TextStyle.paragraph,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        text = self.children[0].value
        await interaction.response.defer(ephemeral=True)
        try:
            if self.mode == "say":
                await interaction.channel.send(text)
                await interaction.followup.send("Done", ephemeral=True)
            elif self.mode == "announce":
                await self.target.send(text)
                await interaction.followup.send(
                    f"Announced in {self.target.mention}.", ephemeral=True
                )
            elif self.mode == "dm":
                await self.target.send(text)
                await interaction.followup.send(
                    f"Message sent to {self.target.name}.", ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"Failed to send: {e}", ephemeral=True)


class EchoChannelSelect(ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select a channel...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        modal = EchoModal(mode="announce", target=self.values[0])
        await interaction.response.send_modal(modal)


class EchoChannelPickView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(EchoChannelSelect())


class EchoUserSelect(ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select a user...",
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        modal = EchoModal(mode="dm", target=self.values[0])
        await interaction.response.send_modal(modal)


class EchoUserPickView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(EchoUserSelect())


class EchoView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label="\U0001f4e3 Announce", style=discord.ButtonStyle.green)
    async def announce(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="\U0001f4e3 Announce",
            description="Select the channel to announce in.",
            color=config.msgColor,
        )
        await interaction.response.edit_message(embed=embed, view=EchoChannelPickView())

    @ui.button(label="\U0001f4ac Say", style=discord.ButtonStyle.grey)
    async def say(self, interaction: discord.Interaction, button: ui.Button):
        modal = EchoModal(mode="say")
        await interaction.response.send_modal(modal)

    @ui.button(label="\U0001f5e8\ufe0f DM", style=discord.ButtonStyle.blurple)
    async def dm(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title="\U0001f5e8\ufe0f DM",
            description="Select the user to message.",
            color=config.msgColor,
        )
        await interaction.response.edit_message(embed=embed, view=EchoUserPickView())


# ===================== VC SETTINGS UI =====================

TYPE_NAMES = {
    "*": "All Types Allowed",
    "cam": "CAM Only",
    "ss": "Screen Share Only",
    "cam+ss": "CAM or Screen Share Allowed",
    "cam&ss": "CAM & Screen Share Allowed",
    "cam+noact": "CAM or No Activity Allowed",
    "ss+noact": "Screen Share or No Activity Allowed",
}


def find_session_for_interaction(inter: discord.Interaction, session_manager):
    """Resolve the session the user is currently in, along with its VC."""
    if not inter.user.voice or not inter.user.voice.channel:
        return None, None
    channel = inter.user.voice.channel
    ch_id = str(channel.id)
    sid = session_manager.channel_sessions.get(ch_id)
    session = session_manager.active_sessions.get(sid) if sid else None
    if session is None:
        for sess in session_manager.active_sessions.values():
            if sess.channel_id == ch_id:
                session = sess
                break
    return session, channel


async def _channel_status(channel: discord.VoiceChannel):
    """Read the current VC status. discord.py doesn't expose it on the object,
    so fetch the raw channel payload from the API."""
    try:
        return getattr(channel, "status", None)
    except Exception:
        pass
    try:
        raw = await channel._state.http.get_channel(channel.id)
        if isinstance(raw, dict):
            return raw.get("status") or None
    except Exception:
        pass
    return None


async def build_vcset_embed(session, channel: discord.VoiceChannel) -> discord.Embed:
    embed = discord.Embed(
        title="\U0001f39b\ufe0f Session Control Panel",
        description="Manage your study VC right from Discord.",
        color=config.msgColor,
        timestamp=datetime.now(),
    )

    owner = f"<@{session.owner_id}>" if session.owner_id else "\u2014"
    embed.add_field(name="\U0001f451 Owner", value=owner, inline=False)
    embed.add_field(
        name="\U0001f3af Session Type",
        value=TYPE_NAMES.get(session.session_type, session.session_type or "\u2014"),
        inline=False,
    )
    embed.add_field(
        name="\U0001f4cb Session ID",
        value=f"```\n{session.session_id}\n```",
        inline=False,
    )
    embed.add_field(name="\U0001f4db VC Name", value=channel.name, inline=False)
    vc_status = await _channel_status(channel)
    embed.add_field(name="\U0001f4ac Status", value=vc_status or "\u2014", inline=False)

    if session.pomodoro_enabled and session.pomodoro_running:
        if session.pomodoro_state == "focus":
            pomo_val = "\U0001f534 Focus"
        elif session.pomodoro_state == "break":
            pomo_val = "\U0001f7e2 Break"
        else:
            pomo_val = "\u23f8\ufe0f Idle"
    elif session.pomodoro_enabled:
        pomo_val = "\u23f8\ufe0f Idle"
    else:
        pomo_val = "\u274c Off"
    embed.add_field(name="\U0001f345 Pomodoro", value=pomo_val, inline=False)
    embed.add_field(name="\U0001f465 Members", value=str(len(session.members or {})), inline=False)

    embed.set_footer(text="Use the controls below to adjust this session.")
    return embed


async def apply_session_type(session, channel: discord.VoiceChannel, interaction: discord.Interaction):
    """Apply a new session type and warn + monitor non-compliant members."""
    study_cog = interaction.client.get_cog("Study")
    exceptions = study_cog.exceptions if study_cog else None
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
                    session.activity_monitor(vc_member, exceptions, category_id, None)
                )
                session.monitor_tasks[str(vc_member.id)] = task

    if non_compliant:
        mentions = " ".join(m.mention for m in non_compliant if not is_muted(str(m.id)))
        await channel.send(
            content=mentions,
            embed=discord.Embed(
                description=f"\u26a0\ufe0f This VC now requires **{session._type_description()}**. "
                f"Turn on the required devices within 5 minutes or you'll be removed.",
                color=0x3498DB,
            ),
            delete_after=30,
        )


class SessionTypeSelect(ui.Select):
    def __init__(self, session, channel: discord.VoiceChannel):
        options = [
            discord.SelectOption(label="All Types Allowed", value="*", description="No restrictions"),
            discord.SelectOption(label="CAM Only", value="cam", description="Camera must be on"),
            discord.SelectOption(label="Screen Share Only", value="ss", description="Screen must be shared"),
            discord.SelectOption(label="CAM or Screen Share", value="cam+ss", description="Either one required"),
            discord.SelectOption(label="CAM & Screen Share", value="cam&ss", description="Both required"),
            discord.SelectOption(label="CAM or No Activity", value="cam+noact", description="Camera on or no activity"),
            discord.SelectOption(label="Screen Share or No Activity", value="ss+noact", description="Screen share or no activity"),
        ]
        super().__init__(placeholder="Set Session Type...", options=options, row=0)
        self.session = session
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.session.owner_id:
            return await interaction.response.send_message(
                "Only the session owner can change this.", ephemeral=True
            )
        value = self.values[0]
        self.session.update_settings(session_type=value)
        sm = getattr(interaction.client, "session_manager", None)
        if sm:
            sm.sync(self.session)
        await apply_session_type(self.session, self.channel, interaction)

        embed = await build_vcset_embed(self.session, self.channel)
        view = VCSetView(self.session, self.channel, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class VCSetModal(ui.Modal, title="Edit Study VC"):
    def __init__(self, session, channel: discord.VoiceChannel, current_status=None):
        super().__init__()
        self.session = session
        self.channel = channel
        self.add_item(ui.TextInput(
            label="VC Name",
            default=channel.name,
            required=False,
            max_length=100,
        ))
        self.add_item(ui.TextInput(
            label="Status",
            default=current_status or "",
            required=False,
            max_length=500,
            style=discord.TextStyle.short,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.session.owner_id:
            return await interaction.response.send_message(
                "Only the session owner can edit this.", ephemeral=True
            )
        try:
            name = self.children[0].value.strip()
        except Exception:
            name = None
        try:
            status = self.children[1].value.strip()
        except Exception:
            status = None
        kwargs = {}
        if name:
            kwargs["name"] = name
        if status:
            kwargs["status"] = status
        try:
            await self.channel.edit(**kwargs)
        except Exception as e:
            return await interaction.response.send_message(f"Failed to update: {e}", ephemeral=True)

        embed = await build_vcset_embed(self.session, self.channel)
        view = VCSetView(self.session, self.channel, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class PomodoroTimesModal(ui.Modal, title="Pomodoro Timing"):
    def __init__(self, session, channel: discord.VoiceChannel):
        super().__init__()
        self.session = session
        self.channel = channel
        self.add_item(ui.TextInput(
            label="Focus (minutes)",
            default=str(session.pomodoro_focus_min),
            required=True,
            max_length=3,
            min_length=1,
            style=discord.TextStyle.short,
        ))
        self.add_item(ui.TextInput(
            label="Break (minutes)",
            default=str(session.pomodoro_break_min),
            required=True,
            max_length=3,
            min_length=1,
            style=discord.TextStyle.short,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.session.owner_id:
            return await interaction.response.send_message(
                "Only the session owner can edit this.", ephemeral=True
            )
        try:
            focus = int(self.children[0].value.strip())
            brk = int(self.children[1].value.strip())
            if focus < 1 or focus > 180 or brk < 1 or brk > 60:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "Use whole minutes (focus 1\u2013180, break 1\u201360).", ephemeral=True
            )

        await self.session.set_pomodoro_times(self.channel, focus, brk)
        embed = await build_vcset_embed(self.session, self.channel)
        view = VCSetView(self.session, self.channel, interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class VCSetView(ui.View):
    def __init__(self, session, channel: discord.VoiceChannel, bot):
        super().__init__(timeout=180)
        self.session = session
        self.channel = channel
        self.bot = bot
        self.add_item(SessionTypeSelect(session, channel))

        pomo_label = "\U0001f345 Pomodoro: ON" if session.pomodoro_enabled else "\U0001f345 Pomodoro: OFF"
        pomo_style = discord.ButtonStyle.green if session.pomodoro_enabled else discord.ButtonStyle.secondary
        toggle = ui.Button(label=pomo_label, style=pomo_style, row=1)
        toggle.callback = self.pomodoro_toggle
        self.add_item(toggle)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.session.owner_id:
            await interaction.response.send_message(
                "Only the session owner can control this panel.", ephemeral=True
            )
            return False
        return True

    async def pomodoro_toggle(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        if self.session.pomodoro_enabled:
            await self.session.disable_pomodoro(self.channel)
        else:
            await self.session.enable_pomodoro(self.channel)

        embed = await build_vcset_embed(self.session, self.channel)
        view = VCSetView(self.session, self.channel, interaction.client)
        await interaction.edit_original_response(embed=embed, view=view)

    @ui.button(label="\u270f\ufe0f Edit", style=discord.ButtonStyle.blurple, row=1)
    async def edit(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._guard(interaction):
            return
        current_status = await _channel_status(self.channel)
        await interaction.response.send_modal(VCSetModal(self.session, self.channel, current_status))

    @ui.button(label="\U0001f345 Times", style=discord.ButtonStyle.blurple, row=1)
    async def pomo_times(self, interaction: discord.Interaction, button: ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(PomodoroTimesModal(self.session, self.channel))

    @ui.button(label="Exit", style=discord.ButtonStyle.red, row=2)
    async def exit(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(content="Panel closed.", embed=None, view=None)


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
        logger.info("Study cog on_ready fired")
        try:
            log.process(status_code=0, message="Syncing", details="Trying to sync with Bot Tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Success", details="Bot Tree has been successfully synced.")
        except Exception:
            log.error(status_code=-100, message="Error", details=traceback.format_exc())
        finally:
            log.send()

        try:
            # Wait for guild voice states to populate before recovery
            await asyncio.sleep(3)
            await self.recovery.recover()
            self.recovery.start_snapshot_task(interval_minutes=5)
        except Exception:
            logger.exception("Recovery failed")

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

            sync_member_from_discord(userCollection, str(member.id), member.guild)

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
        while (details:=self.bot.userNetworkConnection.pop(str(inter.user.id), None))==None and (datetime.now() - t).total_seconds() <= 90:
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
        ],
        criterion=[
            app_commands.Choice(name="\u23f1\ufe0f Time Studied", value="time"),
            app_commands.Choice(name="\U0001fab5 Wood", value="wood"),
            app_commands.Choice(name="\U0001f529 Iron", value="iron"),
        ],
        style=[
            app_commands.Choice(name="Embed", value="embed"),
            app_commands.Choice(name="Image", value="image"),
        ],
        border=[
            app_commands.Choice(name="\U0001f947 Gold", value="gold"),
            app_commands.Choice(name="\U0001f948 Silver", value="silver"),
            app_commands.Choice(name="\U0001f949 Bronze", value="bronze"),
            app_commands.Choice(name="\U0001fab5 Wood", value="wood"),
        ],
    )
    @app_commands.describe(
        scope="It describes if you want to see leaderboard within the server or globally.",
        view="It defines based on what choice you view your leaderboard",
        criterion="The criterion you want to rank everyone by",
        style="How the leaderboard should be displayed (default: Embed)",
        border="Image border style (only applies to the Image style)",
    )
    async def leaderboard(self, inter: discord.Interaction, view: str = "display_name", scope: int = 1, criterion: str = "time", style: str = "embed", border: str = "gold"):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=0, name='Waiting', details=f"Fetching {criterion} leaderboard data...")

            if scope == 0:
                await inter.response.send_message("The Leaderboard command is still under development!", ephemeral=True)
                cmdLog.process(status_code=50, name="Pending")
                return

            await inter.response.defer()

            user_id = str(inter.user.id)
            guild_id = str(inter.guild_id)

            def score_of(u):
                if criterion == "time":
                    guild_time = (u.get("servers") or {}).get(guild_id) or {}
                    if isinstance(guild_time, dict):
                        return int(guild_time.get("time") or 0)
                    return 0
                resources = (u.get("economy") or {}).get("resources") or {}
                return int((resources.get(criterion) or {}).get("amount") or 0)

            def avatar_url(u):
                pfp = u.get("pfp") or ""
                if pfp.startswith("http"):
                    return pfp
                if pfp:
                    return f"https://cdn.discordapp.com/avatars/{u['_id']}/{pfp}.png"
                return f"https://cdn.discordapp.com/embed/avatars/{int(u['_id']) % 5}.png"

            def fmt_score(amount):
                if criterion == "time":
                    return format_duration(amount)
                return f"{int(amount):,}"

            members = list(inter.guild.members) if inter.guild else []
            if not members and inter.guild:
                members = [m async for m in inter.guild.fetch_members() if not m.bot]
            members = [m for m in members if not m.bot]
            member_ids = [str(m.id) for m in members]

            # Only fetch the fields we actually need (smaller transfer, faster query).
            if criterion == "time":
                projection = {f"servers.{guild_id}.time": 1}
            else:
                projection = {f"economy.resources.{criterion}.amount": 1}
            projection.update({"name": 1, "display_name": 1, "pfp": 1})

            def _fetch_users(ids):
                return {
                    u["_id"]: u
                    for u in userCollection.find({"_id": {"$in": ids}}, projection)
                }

            # Sync pymongo blocks the event loop, so run it in a worker thread.
            t_db = time.perf_counter()
            users = _get_cached_lb_users(guild_id, criterion)
            if users is not None:
                cmdLog.process(
                    status_code=50,
                    name="DB",
                    details=f"Served {len(users)} users from cache in {(time.perf_counter() - t_db) * 1000:.0f}ms",
                )
            else:
                users = await asyncio.to_thread(_fetch_users, member_ids)
                _cache_lb_users(guild_id, criterion, users)
                cmdLog.process(
                    status_code=50,
                    name="DB",
                    details=f"Loaded {len(users)} users in {(time.perf_counter() - t_db) * 1000:.0f}ms",
                )

            entries = []
            for m in members:
                mid = str(m.id)
                u = users.get(mid) or {}
                entries.append({
                    "_id": mid,
                    "name": u.get("name") or m.name,
                    "display_name": u.get("display_name") or m.display_name or m.name,
                    "pfp": u.get("pfp", ""),
                    "amount": score_of(u),
                })

            entries.sort(key=lambda e: e["amount"], reverse=True)

            ranked = [e for e in entries if e["amount"] > 0]
            padding = [e for e in entries if e["amount"] <= 0]
            if len(ranked) < config.leaderboardLimit:
                ranked += padding[: config.leaderboardLimit - len(ranked)]

            board = ranked
            total_count = len(board)

            if total_count < 3:
                msg = await inter.followup.send(
                    embed=discord.Embed(description="Not enough users to rank. Need at least 3.", color=config.msgColor),
                    wait=True
                )
                await msg.delete(delay=30)
                cmdLog.process(status_code=100, name="Not enough users")
                return

            for i, u in enumerate(board):
                u["_rank"] = i + 1

            user_rank = None
            for u in board:
                if u["_id"] == user_id:
                    user_rank = u["_rank"]
                    break

            top3 = board[:3]

            if total_count <= 10 or user_rank is None or user_rank <= 10:
                rows = board[3:10]
            else:
                start = max(3, user_rank - 7)
                end = min(len(board), start + 7)
                rows = board[start:end]

            if style == "image":
                podium_data = [
                    {
                        "rank": u["_rank"],
                        "name": u.get(view, "Unknown"),
                        "value": fmt_score(u["amount"]),
                        "avatar_url": avatar_url(u),
                    }
                    for u in top3
                ]

                rows_data = [
                    {
                        "rank": u["_rank"],
                        "name": u.get(view, "Unknown"),
                        "value": fmt_score(u["amount"]),
                        "avatar_url": avatar_url(u),
                    }
                    for u in rows
                ]

                lb_data = {"podium": podium_data, "rows": rows_data}
                t_render = time.perf_counter()
                image_data = await getNovaLeaderboard(lb_data, border)
                cmdLog.process(
                    status_code=50,
                    name="Image",
                    details=f"Rendered in {(time.perf_counter() - t_render) * 1000:.0f}ms",
                )

                if image_data:
                    file = discord.File(fp=image_data, filename="leaderboard.webp")
                    await inter.followup.send(file=file)
                    cmdLog.process(status_code=100, name="Executed", details="Image leaderboard delivered.")
                else:
                    await inter.followup.send("Failed to generate leaderboard image.")
                    cmdLog.process(status_code=-100, name="Failed", details="Image generation failed.")
            else:
                toppers = top3 + rows
                msg = await inter.followup.send(
                    embed=discord.Embed(
                        description=leaderboard_template(toppers=toppers, view=view, criterion=criterion),
                        color=config.msgColor
                    ),
                    wait=True
                )
                await msg.delete(delay=30)
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

    @app_commands.command(name='shell', description='execute special commands')
    async def shell(self, inter: discord.Interaction, cmd: str):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if inter.user.id != config.OWNER_ID:
                await inter.response.send_message('You are not authorized to use this command.', ephemeral=True)
                return

            cmdLog.process(status_code=0, name="Waiting", details=f"Initiating shell command execution: {cmd}")

            if cmd == 'echo':
                embed = discord.Embed(
                    title="\U0001f4ac Echo",
                    description="Choose what you want to do.",
                    color=config.msgColor,
                )
                await inter.response.send_message(embed=embed, view=EchoView(), ephemeral=True)
                cmdLog.process(status_code=100, name="Executed", details="Echo menu opened.")
                return

            elif cmd.startswith('decho '):
                parts = cmd[6:].strip().split(' ', 1)
                if len(parts) < 2:
                    await inter.response.send_message('Usage: decho <user_id> <text>', ephemeral=True)
                    return
                target_id, text = parts
                try:
                    target_user = await inter.client.fetch_user(int(target_id))
                    await target_user.send(text)
                    await inter.response.send_message(f'Message sent to {target_user.name}', ephemeral=True)
                except Exception as e:
                    await inter.response.send_message(f'Failed to DM user: {e}', ephemeral=True)
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

            elif cmd == 'fix gifs':
                await inter.response.send_message("Scanning stored reminder GIFs for broken URLs...", ephemeral=True)
                from library.gifs import repair_reminder_gifs
                try:
                    result = await repair_reminder_gifs(db["config"])
                    await inter.followup.send(
                        f"**GIF repair complete!**\n- Scanned: {result['total']}\n- Repaired: {result['repaired']}\n- Active: {len(result['gifs'])}",
                        ephemeral=True
                    )
                    cmdLog.process(status_code=100, name="Executed", details=f"GIF repair: {result['repaired']} of {result['total']} fixed.")
                except Exception as e:
                    await inter.followup.send(f"Failed to repair GIFs: {e}", ephemeral=True)
                    cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())

            else:
                await inter.response.send_message(
                    f"Unknown command: `{cmd}`\nAvailable commands: `echo`, `decho`, `update lb`, `sync`, `fix gifs`.",
                    ephemeral=True,
                )
                cmdLog.process(status_code=-25, name="Rejected", details=f"Unknown shell command: {cmd}")

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
    async def vcset(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            session, channel = find_session_for_interaction(inter, self.session_manager)

            if session is None or channel is None:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You are not in a study VC.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                cmdLog.process(status_code=-25, name="No VC", details="User is not in a study VC.")
                return

            embed = await build_vcset_embed(session, channel)
            view = VCSetView(session, channel, inter.client)
            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Executed", details="VC settings panel opened.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="boostxp", description="Boost the current study session with XP")
    @app_commands.guild_only()
    async def boostxp(self, inter: discord.Interaction):
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
            user_id = str(inter.user.id)

            if user_id not in (session_doc.get("members") or {}):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="You are not a member of this session.",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            if session_doc.get("pending_level_up"):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description="A level-up is pending — pay wood first!",
                        color=config.msgColor,
                    ),
                    ephemeral=True, delete_after=10,
                )
                return

            now = datetime.now(timezone.utc)
            last_boost = session_doc.get("last_boost_at")
            if last_boost:
                last_ts = datetime.fromisoformat(last_boost) if isinstance(last_boost, str) else last_boost
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
            else:
                started = session_doc.get("started_at")
                if started:
                    last_ts = datetime.fromisoformat(started) if isinstance(started, str) else started
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                else:
                    last_ts = now

            elapsed_min = (now - last_ts).total_seconds() / 60.0
            xp_gain = max(1, int(elapsed_min * config.LEVEL_UP_XP_PER_MINUTE))

            current_xp = session_doc.get("vc_xp", 0)
            current_level = session_doc.get("vc_level", 1)
            new_xp = current_xp + xp_gain

            level_up = False
            new_level = current_level
            pending_level_up_data = None

            if new_xp >= config.LEVEL_UP_XP_THRESHOLD:
                new_level = current_level + 1
                wood_cost = config.LEVEL_UP_WOOD_BASE * new_level
                pending_level_up_data = {
                    "new_level": new_level,
                    "wood_cost": wood_cost,
                }
                level_up = True

            update_fields = {
                "vc_xp": new_xp,
                "vc_level": new_level,
                "last_boost_at": now.isoformat(),
            }
            if pending_level_up_data:
                update_fields["pending_level_up"] = pending_level_up_data

            db["sessions"].update_one(
                {"session_id": session_id},
                {"$set": update_fields},
            )

            if session_id in self.session_manager.active_sessions:
                sess = self.session_manager.active_sessions[session_id]
                sess.vc_xp = new_xp
                sess.vc_level = new_level
                sess.last_boost_at = now.isoformat()
                if pending_level_up_data:
                    sess.pending_level_up = pending_level_up_data

            if session_id in self.session_manager.active_sessions:
                sess = self.session_manager.active_sessions[session_id]
                await sess._emit_event("boostxp", {
                    "user_id": user_id,
                    "xp_gained": xp_gain,
                    "new_xp": new_xp,
                    "vc_level": new_level,
                    "level_up": level_up,
                })

            if level_up and pending_level_up_data:
                if session_id in self.session_manager.active_sessions:
                    sess = self.session_manager.active_sessions[session_id]
                    await sess._emit_event("level_up", {
                        "new_level": new_level,
                        "wood_cost": pending_level_up_data["wood_cost"],
                    })

                try:
                    domain = os.getenv("FRONTEND_DOMAIN", "")
                    if not domain.endswith("/"):
                        domain += "/"
                    link = f"{domain}projects?level_up={session_id}"
                    channel = inter.user.voice.channel
                    level_embed = discord.Embed(
                        title="\u2b06\ufe0f Level Up Available!",
                        description=f"Level **{current_level}** \u2192 **{new_level}**\nCost: **{pending_level_up_data['wood_cost']}** \U0001fab5 Wood",
                        color=discord.Color.green(),
                    )
                    pay_view = discord.ui.View()
                    pay_view.add_item(discord.ui.Button(
                        label=f"Pay {pending_level_up_data['wood_cost']} Wood",
                        style=discord.ButtonStyle.link,
                        url=link,
                        emoji="\U0001fab5",
                    ))
                    msg = await channel.send(embed=level_embed, view=pay_view)
                    db["sessions"].update_one(
                        {"session_id": session_id},
                        {"$set": {"level_up_message_id": str(msg.id)}},
                    )
                    if session_id in self.session_manager.active_sessions:
                        self.session_manager.active_sessions[session_id].level_up_message_id = str(msg.id)
                except Exception:
                    pass

            embed = discord.Embed(
                title="🚀 Session Boosted!",
                color=discord.Color.gold(),
                timestamp=now,
            )
            embed.add_field(name="XP Gained", value=f"+{xp_gain}", inline=True)
            embed.add_field(name="Total XP", value=f"{new_xp}/5000", inline=True)
            embed.add_field(name="VC Level", value=str(new_level), inline=True)

            if level_up and pending_level_up_data:
                embed.description = "⬆️ **LEVEL UP AVAILABLE!** Pay wood to level up."
                embed.add_field(name="Wood Cost", value=f"{pending_level_up_data['wood_cost']}", inline=False)

            embed.add_field(
                name="How It Works",
                value="Boost to accumulate XP → 5000 XP triggers level-up → any member pays wood to proceed",
                inline=False,
            )

            await inter.response.send_message(embed=embed, delete_after=30)
            cmdLog.process(status_code=100, name="Executed", details=f"Session boosted: +{xp_gain} XP (Level {new_level}).")
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


# ===================== HOLIDAY =====================

HOLIDAY_COST_PER_DAY = 150

HOLIDAY_PANEL_CUSTOM_ID = "holiday_panel_view"
HOLIDAY_BTN_CUSTOM_ID = "holiday_panel_take"
HOLIDAY_BACK_CUSTOM_ID = "holiday_panel_back"

# ===================== HOLIDAY HELPERS =====================


def _holiday_config(guild_id) -> dict:
    """Return the holiday section of a server's config, or empty dict."""
    server_data = serverCollection.find_one({"_id": str(guild_id)}) or {}
    return server_data.get("holiday") or {}


def _require_perms(guild: discord.Guild) -> str | None:
    """Return an error string if the bot is missing required permissions, else None."""
    me = guild.me
    needed = []
    if not me.guild_permissions.manage_roles:
        needed.append("Manage Roles (to create/assign the holiday role)")
    if not me.guild_permissions.manage_channels:
        needed.append("Manage Channels (to set channel overwrites)")
    if needed:
        return "I need the following permissions:\n" + "\n".join(f"• **{p}**" for p in needed)
    return None


async def setup_holiday_role(guild: discord.Guild, existing_role_id: int | None = None) -> discord.Role:
    """Return the holiday role, creating one if needed."""
    if existing_role_id:
        role = guild.get_role(existing_role_id)
        if role:
            return role
    return await guild.create_role(
        name="\U0001f334 On Holiday",
        color=discord.Color.gold(),
        reason="Holiday system — auto-created",
    )


async def apply_holiday_overwrites(guild: discord.Guild, role: discord.Role, holiday_channel: discord.TextChannel):
    """Lock the holiday role out of every channel except the holiday channel."""
    for ch in guild.channels:
        try:
            if ch.id == holiday_channel.id:
                await ch.set_permissions(
                    role,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        embed_links=True,
                        attach_files=True,
                    ),
                    reason="Holiday system — allow holiday channel",
                )
            else:
                await ch.set_permissions(
                    role,
                    overwrite=discord.PermissionOverwrite(view_channel=False),
                    reason="Holiday system — deny non-holiday channels",
                )
        except discord.Forbidden:
            continue
        except discord.HTTPException:
            continue
    # Hide the holiday channel from @everyone
    try:
        await holiday_channel.set_permissions(
            guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
            reason="Holiday system — hide from @everyone",
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


async def assign_holiday_role(member: discord.Member) -> bool:
    """Assign the holiday role to a member. Returns True on success."""
    hcfg = _holiday_config(member.guild.id)
    role_id = hcfg.get("role_id")
    if not role_id:
        return False
    role = member.guild.get_role(int(role_id))
    if not role:
        return False
    if role in member.roles:
        return True
    try:
        await member.add_roles(role, reason="Holiday system")
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def remove_holiday_role(member: discord.Member) -> bool:
    """Remove the holiday role from a member. Returns True if removed."""
    hcfg = _holiday_config(member.guild.id)
    role_id = hcfg.get("role_id")
    if not role_id:
        return False
    role = member.guild.get_role(int(role_id))
    if not role or role not in member.roles:
        return False
    try:
        await member.remove_roles(role, reason="Holiday ended")
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def send_holiday_panel(channel: discord.TextChannel) -> str | None:
    """Send the persistent holiday panel embed and return the message ID."""
    embed = discord.Embed(
        title="\U0001f334 Holiday Channel",
        description=(
            "Take a break without losing your streak.\n\n"
            "\U0001f334 **Holiday** — Pay with Wood to freeze your streak for 1-7 days.\n"
            "\U0001f7e2 **I'm Back** — Done resting? Click to restore full server access.\n\n"
            "_Streak protection continues until your holiday timer expires._"
        ),
        color=discord.Color.gold(),
    )
    view = HolidayPanelView()
    msg = await channel.send(embed=embed, view=view)
    return str(msg.id)


class HolidayPanelView(discord.ui.View):
    """Persistent panel in the holiday channel. Re-attached on bot restart."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Holiday",
        style=discord.ButtonStyle.green,
        emoji="\U0001f334",
        custom_id=HOLIDAY_BTN_CUSTOM_ID,
    )
    async def take_holiday(self, inter: discord.Interaction, button: discord.ui.Button):
        user_id = str(inter.user.id)
        user_data = userCollection.find_one({"_id": user_id})
        if not user_data:
            return await inter.response.send_message(
                embed=discord.Embed(description="No account found. Visit the website first.", color=discord.Color.red()),
                ephemeral=True,
            )

        holiday_until = user_data.get("holiday_until")
        if holiday_until:
            if holiday_until.tzinfo is None:
                holiday_until = holiday_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < holiday_until:
                remaining = holiday_until - datetime.now(timezone.utc)
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                return await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"\U0001f3d6\ufe0f You're already on holiday! **{hours}h {mins}m** remaining.",
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True,
                )

        await inter.response.send_message(
            embed=discord.Embed(
                title="\U0001f334 How many days?",
                description=f"Cost: **{HOLIDAY_COST_PER_DAY} \U0001fab5** per paid day. Free days are used first.",
                color=discord.Color.gold(),
            ),
            view=HolidayDaySelectView(user_id),
            ephemeral=True,
        )

    @discord.ui.button(
        label="I'm Back",
        style=discord.ButtonStyle.green,
        emoji="\U0001f7e2",
        custom_id=HOLIDAY_BACK_CUSTOM_ID,
    )
    async def im_back(self, inter: discord.Interaction, button: discord.ui.Button):
        member = inter.user if isinstance(inter.user, discord.Member) else inter.guild.get_member(inter.user.id)
        if not member:
            return await inter.response.send_message("Could not find your member record.", ephemeral=True)

        removed = await remove_holiday_role(member)
        if not removed:
            return await inter.response.send_message(
                embed=discord.Embed(
                    description="You don't have the holiday role. You already have full access!",
                    color=discord.Color.greyple(),
                ),
                ephemeral=True,
            )

        desc = "\u2705 Welcome back! Full server access restored."
        user_data = userCollection.find_one({"_id": str(inter.user.id)}) or {}
        holiday_until = user_data.get("holiday_until")
        if holiday_until:
            if holiday_until.tzinfo is None:
                holiday_until = holiday_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < holiday_until:
                desc += "\n\n_Your streak protection is still active until the holiday timer expires._"
        await inter.response.send_message(
            embed=discord.Embed(description=desc, color=discord.Color.green()),
            ephemeral=True,
        )


class HolidayDaySelectView(ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.select(
        placeholder="Select days...",
        options=[discord.SelectOption(label=f"{d} Day{'s' if d > 1 else ''}", value=d) for d in range(1, 8)],
    )
    async def select_days(self, inter: discord.Interaction, select: ui.Select):
        days = int(select.values[0])
        user_id = self.user_id
        user_data = userCollection.find_one({"_id": user_id})
        if not user_data:
            return await inter.response.edit_message(content="Account not found.", embed=None, view=None)

        free_days = user_data.get("holiday", 0)
        free_days_used = min(free_days, days)
        paid_days = days - free_days_used
        total_wood_cost = paid_days * HOLIDAY_COST_PER_DAY

        resources = user_data.get("economy", {}).get("resources", {})
        wood_data = resources.get("wood", {})
        current_wood, _ = degrade.apply(
            wood_data.get("amount", 0),
            wood_data.get("degraded_at"),
            0.05,
        )

        if paid_days > 0 and current_wood < total_wood_cost:
            return await inter.response.edit_message(
                content=f"You need **{total_wood_cost} Wood** for {paid_days} day{'s' if paid_days > 1 else ''}. You have **{int(current_wood)} Wood**.",
                embed=None,
                view=None,
            )

        embed = discord.Embed(
            title="\U0001f334 Holiday",
            description=f"Take a **{days} day{'s' if days > 1 else ''}** holiday?\n\nYour streak will be frozen, and mentions/DMs will be paused.\n",
            color=discord.Color.teal(),
        )
        if free_days_used > 0:
            embed.add_field(name="Free Days", value=f"**{free_days_used}** day{'s' if free_days_used > 1 else ''}", inline=True)
        if paid_days > 0:
            embed.add_field(name="Wood Cost", value=f"**{total_wood_cost}** \U0001fab5 ({paid_days} \u00d7 {HOLIDAY_COST_PER_DAY})", inline=True)

        view = HolidayConfirmView(
            user_id=user_id,
            days=days,
            wood_cost=total_wood_cost,
            free_days_used=free_days_used,
            paid_days=paid_days,
        )
        await inter.response.edit_message(embed=embed, view=view)


class HolidayConfirmView(discord.ui.View):
    def __init__(self, user_id: str, days: int, wood_cost: int, free_days_used: int, paid_days: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.days = days
        self.wood_cost = wood_cost
        self.free_days_used = free_days_used
        self.paid_days = paid_days

    @discord.ui.button(label="Confirm Holiday", style=discord.ButtonStyle.green, emoji="🏖️")
    async def confirm(self, inter: discord.Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.user_id:
            return await inter.response.send_message("This isn't your holiday!", ephemeral=True)

        await inter.response.defer(ephemeral=True)

        user_data = userCollection.find_one({"_id": self.user_id})
        if not user_data:
            return await inter.followup.send("Account not found.", ephemeral=True)

        free_days = user_data.get("holiday", 0)
        now = datetime.now(timezone.utc)
        holiday_end = now + timedelta(days=self.days)

        update_ops = {"$set": {"holiday_until": holiday_end}}

        if self.paid_days > 0:
            resources = user_data.get("economy", {}).get("resources", {})
            wood_data = resources.get("wood", {})
            raw_amount = wood_data.get("amount", 0)
            degraded_at = wood_data.get("degraded_at")
            current_wood, wood_dt = degrade.apply(raw_amount, degraded_at, 0.05)

            if current_wood < self.paid_days * HOLIDAY_COST_PER_DAY:
                return await inter.followup.send("Not enough Wood. Try again.", ephemeral=True)

            new_wood = current_wood - (self.paid_days * HOLIDAY_COST_PER_DAY)
            update_ops["$set"]["economy.resources.wood.amount"] = new_wood
            update_ops["$set"]["economy.resources.wood.degraded_at"] = wood_dt

        if self.free_days_used > 0:
            remaining_free = free_days - self.free_days_used
            update_ops["$set"]["holiday"] = remaining_free

        userCollection.update_one({"_id": self.user_id}, update_ops)

        # Assign the holiday role so the user is locked to the holiday channel.
        member = inter.guild.get_member(int(self.user_id)) if inter.guild else None
        role_assigned = False
        if member:
            role_assigned = await assign_holiday_role(member)

        desc = f"Holiday activated for **{self.days} day{'s' if self.days > 1 else ''}**!\n"
        desc += f"Expires: <t:{int(holiday_end.timestamp())}:R>\n\n"
        if self.free_days_used > 0:
            desc += f"Free days used: **{self.free_days_used}**\n"
        if self.paid_days > 0:
            desc += f"Wood spent: **{self.paid_days * HOLIDAY_COST_PER_DAY}** \U0001fab5\n"
        desc += "\nStreak frozen. Mentions and DMs paused."
        if not role_assigned:
            desc += "\n\n_\u26a0\ufe0f Could not apply the holiday role. Ask an admin to check bot permissions._"

        embed = discord.Embed(
            title="🏖️ Holiday Activated!",
            description=desc,
            color=discord.Color.teal(),
        )
        await inter.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="✖️")
    async def cancel(self, inter: discord.Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.user_id:
            return
        await inter.response.edit_message(content="Holiday cancelled.", embed=None, view=None)


class Holiday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(HolidayPanelView())
        logger.info("HolidayPanelView registered")

    @app_commands.command(
        name="holiday",
        description="Take a holiday to freeze your streak, mentions, and DMs."
    )
    @app_commands.describe(days="Number of days for your holiday (1-7).")
    @app_commands.choices(days=[
        app_commands.Choice(name=f"{d} Day{'s' if d > 1 else ''}", value=d) for d in range(1, 8)
    ])
    async def holiday(self, inter: discord.Interaction, days: int):
        user_id = str(inter.user.id)

        user_data = userCollection.find_one({"_id": user_id})
        if not user_data:
            return await inter.response.send_message(
                embed=discord.Embed(description="No account found. Visit the website first.", color=discord.Color.red()),
                ephemeral=True
            )

        holiday_until = user_data.get("holiday_until")
        if holiday_until:
            if holiday_until.tzinfo is None:
                holiday_until = holiday_until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < holiday_until:
                remaining = holiday_until - datetime.now(timezone.utc)
                hours = int(remaining.total_seconds() // 3600)
                return await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"🏖️ You're already on holiday! **{hours}h {int((remaining.total_seconds() % 3600) // 60)}m** remaining.",
                        color=discord.Color.orange()
                    ),
                    ephemeral=True
                )

        free_days = user_data.get("holiday", 0)
        free_days_used = min(free_days, days)
        paid_days = days - free_days_used
        total_wood_cost = paid_days * HOLIDAY_COST_PER_DAY

        resources = user_data.get("economy", {}).get("resources", {})
        wood_data = resources.get("wood", {})
        current_wood, _ = degrade.apply(
            wood_data.get("amount", 0),
            wood_data.get("degraded_at"),
            0.05
        )

        if paid_days > 0 and current_wood < total_wood_cost:
            return await inter.response.send_message(
                embed=discord.Embed(
                    description=f"You need **{total_wood_cost} Wood** for {paid_days} day{'s' if paid_days > 1 else ''}. You have **{int(current_wood)} Wood**.\n\n"
                                f"You have **{free_days}** free holiday day{'s' if free_days != 1 else ''} available.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

        embed = discord.Embed(
            title="🏖️ Holiday",
            description=f"Take a **{days} day{'s' if days > 1 else ''}** holiday?\n\n"
                        f"Your streak will be frozen, and mentions/DMs will be paused.\n\n",
            color=discord.Color.teal()
        )

        if free_days_used > 0:
            embed.add_field(
                name="Free Days",
                value=f"**{free_days_used}** day{'s' if free_days_used > 1 else ''} (from your holiday balance)",
                inline=True
            )
        if paid_days > 0:
            embed.add_field(
                name="Wood Cost",
                value=f"**{total_wood_cost}** 🪵 ({paid_days} day{'s' if paid_days > 1 else ''} × {HOLIDAY_COST_PER_DAY})",
                inline=True
            )

        view = HolidayConfirmView(
            user_id=user_id,
            days=days,
            wood_cost=total_wood_cost,
            free_days_used=free_days_used,
            paid_days=paid_days,
        )
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(
        name="revise-holiday",
        description="Audit holiday status: who's on holiday, who broke streak, who's intact."
    )
    @app_commands.default_permissions(administrator=True)
    async def revise_holiday(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message(
                "You need **Manage Server** permission.", ephemeral=True
            )
        await inter.response.defer(ephemeral=True)

        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).date().isoformat()

        on_holiday = []
        broken_streak = []
        intact_streak = []

        cursor = userCollection.find(
            {},
            {"_id": 1, "name": 1, "streak": 1, "holiday_until": 1, "last_study_time": 1, "last_study_date": 1}
        )

        for doc in cursor:
            uid = doc["_id"]
            streak = doc.get("streak", 0)
            holiday_until = doc.get("holiday_until")
            name = doc.get("name") or uid

            if holiday_until:
                if holiday_until.tzinfo is None:
                    holiday_until = holiday_until.replace(tzinfo=timezone.utc)
                if now < holiday_until:
                    remaining = holiday_until - now
                    hrs = int(remaining.total_seconds() // 3600)
                    mins = int((remaining.total_seconds() % 3600) // 60)
                    on_holiday.append(f"\u2705 **{name}** \u2014 streak {streak}, holiday ends in {hrs}h {mins}m")
                    continue

            last_study = doc.get("last_study_time") or doc.get("last_study_date")
            if last_study:
                if isinstance(last_study, str):
                    last_date = last_study
                else:
                    if last_study.tzinfo is None:
                        last_study = last_study.replace(tzinfo=timezone.utc)
                    last_date = last_study.date().isoformat()
            else:
                last_date = None

            if streak > 0 and (last_date is None or last_date < yesterday):
                broken_streak.append(f"\u274c **{name}** \u2014 had {streak}-day streak")
            elif streak > 0:
                intact_streak.append(f"\U0001f525 **{name}** \u2014 {streak}-day streak")

        def _chunks(items, size=15):
            for i in range(0, len(items), size):
                yield "\n".join(items[i:i+size])

        embed = discord.Embed(
            title="\U0001f4cb Holiday Audit",
            description=f"Scanned **{sum(len(x) for x in [on_holiday, broken_streak, intact_streak])}** users.",
            color=config.msgColor,
            timestamp=now,
        )

        if on_holiday:
            pages = list(_chunks(on_holiday))
            embed.add_field(name=f"\U0001f3d6\ufe0f On Holiday ({len(on_holiday)})", value=pages[0], inline=False)
            for page in pages[1:]:
                embed.add_field(name="\u200b", value=page, inline=False)
        else:
            embed.add_field(name="\U0001f3d6\ufe0f On Holiday (0)", value="Nobody currently on holiday.", inline=False)

        if broken_streak:
            pages = list(_chunks(broken_streak))
            embed.add_field(name=f"\u274c Broken Streak ({len(broken_streak)})", value=pages[0], inline=False)
            for page in pages[1:]:
                embed.add_field(name="\u200b", value=page, inline=False)
        else:
            embed.add_field(name="\u274c Broken Streak (0)", value="No broken streaks.", inline=False)

        if intact_streak:
            pages = list(_chunks(intact_streak))
            embed.add_field(name=f"\U0001f525 Intact Streak ({len(intact_streak)})", value=pages[0], inline=False)
            for page in pages[1:]:
                embed.add_field(name="\u200b", value=page, inline=False)
        else:
            embed.add_field(name="\U0001f525 Intact Streak (0)", value="No intact streaks.", inline=False)

        await inter.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    Study_cog = Study(bot)
    Holiday_cog = Holiday(bot)
    await bot.add_cog(Study_cog)
    await bot.add_cog(Holiday_cog)
