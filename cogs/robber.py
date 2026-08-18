import asyncio
import logging
import math
import random
from datetime import datetime, timedelta, timezone

import pymongo
import config
import discord
from discord import ui
from discord.ext import commands, tasks

from library import db, degrade, is_muted
from library.logging import CogLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)
logger = logging.getLogger(__name__)

userCollection = db["users"]
configCollection = db["config"]
jailCollection = db["robber"]
activityChannels = db["robber.activity.channels"]
activityMembers = db["robber.activity.members"]

try:
    activityChannels.drop_index("last_at_1")
except pymongo.errors.OperationFailure:
    pass
activityChannels.create_index("last_at", expireAfterSeconds=7 * 86400)

try:
    activityMembers.drop_index("last_at_1")
except pymongo.errors.OperationFailure:
    pass
activityMembers.create_index("last_at", expireAfterSeconds=7 * 86400)

ROAST_LINES = [
    "Nothing to rob here! Someone skipped too many study sessions.",
    "Zero wood? Go study first, then we'll talk business!",
    "I came for your wood but found nothing but excuses. Hit the books, my friend!",
    "Your pockets are as empty as your study logs. Get back to studying!",
    "Not a single piece of wood to steal \u2014 that's what no studying does to a person!",
    "Even your wood is scared of you. Try studying, then I'll come back for a real robbery!",
    "This robbery is a bust! Come back when you've actually studied and earned some wood!",
    "I'd rob you, but your wallet has cobwebs. Maybe open a book before opening a shop!",
]

DONATE_LINES = [
    "A mysterious billionaire appeared and is throwing resources at everyone!",
    "Money rain! A generous billionaire is feeling lucky today!",
    "Breaking: Local billionaire loses wallet, demands you pick it up!",
    "A wild philanthropist has entered the chat!",
    "Someone tell Elon \u2014 there's a new billionaire in town!",
]

DONATE_IRON_LINES = [
    "A mysterious billionaire appeared and is tossing rare iron scraps!",
    "Iron rain! A generous billionaire is feeling extra generous today!",
    "Breaking: Local billionaire found a mine, demands you take some iron!",
]


class RobberView(ui.View):
    def __init__(
        self,
        victim_id: str,
        amount: int,
        can_jail: bool = True,
        on_jail=None,
    ):
        super().__init__(timeout=config.ROB_MESSAGE_TTL)
        self.victim_id = victim_id
        self.amount = amount
        self.jailed = False
        self.on_jail = on_jail
        if not can_jail:
            self.jail.disabled = True

    @ui.button(label="Jail", style=discord.ButtonStyle.danger)
    async def jail(self, interaction: discord.Interaction, button: ui.Button):
        if str(interaction.user.id) != self.victim_id:
            response_embed = discord.Embed(
                "Breaking News!",
                description="Only the victim can call the police!",
                color=discord.Color.red()
            )
            response_embed.set_thumbnail(url="https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExbXhoeXk1cmhmbGc2eGhqeXJqaTJ0OGVqdWwxdnZyaW1xc2tldnVmaSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/k1oI9MmH9nxJfxfy0o/giphy.gif")
            response_embed.set_footer(text="Credits to Giphy", icon_url="https://giphy.com/static/img/giphy-logo.webp")
            return await interaction.response.send_message(
                embed=response_embed,
                ephemeral=True
            )

        self.jailed = True
        button.disabled = True

        if self.on_jail is not None:
            try:
                result = self.on_jail()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Failed to lock up Billu Badmosh")

        embed = discord.Embed(
            title="\U0001f6a8 Billu Badmosh Caught!",
            description=(
                f"Police caught **Billu Badmosh**! He's locked up for "
                f"the rest of the day. Your **{self.amount} \U0001fab5 wood** "
                f"is safe \u2014 money returned!"
            ),
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url="https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExbXhoeXk1cmhmbGc2eGhqeXJqaTJ0OGVqdWwxdnZyaW1xc2tldnVmaSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/k1oI9MmH9nxJfxfy0o/giphy.gif")
        embed.set_footer(text="Credits to Giphy", icon_url="https://giphy.com/static/img/giphy-logo.webp")

        await interaction.response.edit_message(
            content=interaction.message.content, embed=embed, view=self
        )
        self.stop()


class DonateView(ui.View):
    def __init__(self, wood: int, iron: int):
        super().__init__(timeout=config.DONATE_MESSAGE_TTL)
        self.wood = wood
        self.iron = iron
        self.claimed = False
        self.claimer_id = None
        if iron <= 0:
            self.claim_iron.disabled = True

    @ui.button(label="Claim Wood", style=discord.ButtonStyle.green, emoji="\U0001fab5")
    async def claim_wood(self, interaction: discord.Interaction, button: ui.Button):
        if self.claimed:
            return await interaction.response.send_message(
                "Someone already claimed it!", ephemeral=True
            )
        self.claimed = True
        self.claimer_id = str(interaction.user.id)
        self.stop()

        userCollection.update_one(
            {"_id": self.claimer_id},
            {"$inc": {
                "economy.resources.wood.amount": self.wood,
            },
            "$set": {
                "economy.resources.wood.degraded_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

        embed = discord.Embed(
            title="\U0001f4b0 Resource Claimed!",
            description=(
                f"**{interaction.user.display_name}** claimed "
                f"**{self.wood} \U0001fab5 wood**"
                + (f" and **{self.iron} \u26cf iron**!" if self.iron > 0 else "!")
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
        embed.set_footer(text="The billionaire tips their hat to you!", icon_url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")

        await interaction.response.edit_message(
            embed=embed, view=None
        )

    @ui.button(label="Claim Iron", style=discord.ButtonStyle.blurple, emoji="\u26cf")
    async def claim_iron(self, interaction: discord.Interaction, button: ui.Button):
        if self.claimed:
            return await interaction.response.send_message(
                "Someone already claimed it!", ephemeral=True
            )
        self.claimed = True
        self.claimer_id = str(interaction.user.id)
        self.stop()

        userCollection.update_one(
            {"_id": self.claimer_id},
            {"$inc": {
                "economy.resources.iron.amount": self.iron,
            },
            "$set": {
                "economy.resources.iron.degraded_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

        embed = discord.Embed(
            title="\U0001f4b0 Resource Claimed!",
            description=(
                f"**{interaction.user.display_name}** claimed "
                f"**{self.iron} \u26cf iron**"
                + (f" and **{self.wood} \U0001fab5 wood**!" if self.wood > 0 else "!")
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
        embed.set_footer(text="The billionaire tips their hat to you!", icon_url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")

        await interaction.response.edit_message(
            embed=embed, view=None
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = discord.Embed(
                title="\U0001f4b0 Donation Expired",
                description="The billionaire got bored and left. Nobody claimed the resources in time!",
                color=discord.Color.greyple(),
            )
            embed.set_thumbnail(url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
            try:
                await self.message.edit(embed=embed, view=None)
            except (discord.HTTPException, discord.NotFound):
                pass


class Robber(commands.Cog):
    """Billu Badmosh \u2014 a mischievous robber who appears when the server is active.
    A billionaire also occasionally appears to donate resources.

    Victim selection is weighted by chat activity in the most active channel.
    Top chatters have higher odds, but noise ensures random members also get
    a chance \u2014 keeping things unpredictable and fair.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.robber_loop.start()
        self._track_channel = None
        if config.ROB_TRACK_CHANNEL:
            self._track_channel = config.ROB_TRACK_CHANNEL.lower()

        cogLog.log_cog(
            action="starting",
            status_code=0,
            details="Billu Badmosh cog has been initialized.",
        )

    def cog_unload(self):
        self.robber_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if self._track_channel is not None:
            ch_name = (message.channel.name or "").lower()
            if ch_name != self._track_channel:
                return

        now = datetime.now(timezone.utc)
        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        user_id = str(message.author.id)

        activityChannels.update_one(
            {"_id": channel_id},
            {"$set": {"guild_id": guild_id, "last_at": now}, "$inc": {"count": 1}},
            upsert=True,
        )
        activityMembers.update_one(
            {"_id": f"{channel_id}:{user_id}"},
            {"$set": {"guild_id": guild_id, "channel_id": channel_id, "user_id": user_id, "last_at": now}, "$inc": {"count": 1}},
            upsert=True,
        )

    def _find_target_channel(self, guild: discord.Guild):
        """Pick the most active text channel from activity tracking, fallback to general."""
        window = datetime.now(timezone.utc) - timedelta(hours=24)
        guild_id = str(guild.id)

        top = activityChannels.find_one(
            {"guild_id": guild_id, "last_at": {"$gt": window}},
            sort=[("count", -1)],
        )
        if top:
            ch = guild.get_channel(int(top["_id"]))
            if ch and ch.permissions_for(guild.me).send_messages:
                return ch

        candidates = [
            c for c in guild.text_channels
            if c.permissions_for(guild.me).send_messages
        ]
        if not candidates:
            return None

        for channel in candidates:
            if channel.name.lower() in ("general", "general-chat", "main", "main-chat"):
                return channel

        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            return guild.system_channel

        return candidates[0]

    async def _pick_victim(self, guild: discord.Guild, channel: discord.TextChannel):
        """Weighted victim selection based on chat activity with noise.

        - Top 10 chatters share ~60% probability, decaying exponentially (#1 > #2 > ... > #10).
        - Remaining ~40% spread across ALL non-bot guild members (including top 10).
        - 20% noise chance: fully random pick, ignoring weights entirely.
        """
        guild_id = str(guild.id)
        channel_id = str(channel.id)

        all_members = [m for m in guild.members if not m.bot]
        if not all_members:
            try:
                all_members = [m async for m in guild.fetch_members() if not m.bot]
            except Exception:
                return None
        if not all_members:
            return None

        noise = random.random() < config.ROB_NOISE_CHANCE
        if noise:
            return random.choice(all_members)

        top_docs = list(
            activityMembers.find({"channel_id": channel_id, "guild_id": guild_id})
            .sort("count", -1)
            .limit(10)
        )

        if not top_docs:
            return random.choice(all_members)

        top_ids = [d["user_id"] for d in top_docs]
        top_counts = [d["count"] for d in top_docs]

        total_top = sum(top_counts)
        if total_top == 0:
            return random.choice(all_members)

        active_mass = 0.60
        random_mass = 0.40

        weights = {}
        for i, uid in enumerate(top_ids):
            rank_weight = math.exp(-0.25 * i)
            ratio = top_counts[i] / total_top
            weights[uid] = rank_weight * ratio

        total_weight = sum(weights.values())
        if total_weight > 0:
            for uid in weights:
                weights[uid] = (weights[uid] / total_weight) * active_mass

        per_random = random_mass / max(len(all_members), 1)
        for m in all_members:
            mid = str(m.id)
            if mid in weights:
                weights[mid] += per_random
            else:
                weights[mid] = per_random

        total = sum(weights.values())
        if total <= 0:
            return random.choice(all_members)

        r = random.random() * total
        cumulative = 0.0
        for m in all_members:
            cumulative += weights.get(str(m.id), 0)
            if r <= cumulative:
                return m

        return all_members[-1]

    def _jailed_until(self):
        doc = jailCollection.find_one({"_id": "state"}, {"jailed_until": 1})
        until = doc.get("jailed_until") if doc else None
        if until is None:
            return None
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until

    def _is_jailed(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        until = self._jailed_until()
        return until is not None and now < until

    def _jail_billu(self) -> datetime:
        now = datetime.now(timezone.utc)
        until = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        jailCollection.update_one(
            {"_id": "state"},
            {"$set": {"jailed_until": until, "jailed_at": now}},
            upsert=True,
        )
        logger.info("Billu Badmosh is now jailed until %s", until.isoformat())
        return until

    def _release_billu(self):
        jailCollection.delete_one({"_id": "state"})

    def _get_wood(self, user_id: str) -> int:
        user_data = userCollection.find_one({"_id": user_id}, {"economy": 1})
        resources = (user_data or {}).get("economy", {}).get("resources", {})
        wood_data = resources.get("wood", {})

        rates_doc = configCollection.find_one({"_id": "degradation_rates"})
        wood_rate = rates_doc.get("wood", 0.05) if rates_doc else 0.05

        wood, _ = degrade.apply(
            wood_data.get("amount", 0), wood_data.get("degraded_at"), wood_rate
        )
        return wood

    def _deduct_wood(self, user_id: str, amount: int):
        userCollection.update_one(
            {"_id": user_id},
            {"$set": {
                "economy.resources.wood.amount": amount,
                "economy.resources.wood.degraded_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    def _build_robber_embed(self, description: str) -> discord.Embed:
        embed = discord.Embed(
            title="\U0001f9b9 Robbery",
            description=description,
            color=discord.Color.dark_red(),
        )
        embed.set_author(name="Billu Badmosh", icon_url="https://i.giphy.com/QM5dSUeS2nRL2s8KM4.webp")
        embed.set_thumbnail(url="https://i.giphy.com/QM5dSUeS2nRL2s8KM4.webp")
        embed.set_image(url="https://i.giphy.com/jFgZGu2ShCwhkmeoY8.webp")
        embed.set_footer(text="Credits to Giphy", icon_url="https://giphy.com/static/img/giphy-logo.webp")
        return embed

    def _build_donate_embed(self, wood: int, iron: int) -> discord.Embed:
        resource_text = f"**{wood} \U0001fab5 wood**"
        if iron > 0:
            resource_text += f" and **{iron} \u26cf iron**"

        description = random.choice(DONATE_IRON_LINES if iron > 0 and wood <= 0 else DONATE_LINES)
        description += f"\n\nFirst to claim gets **{resource_text}**!"

        embed = discord.Embed(
            title="\U0001f4b0 Billionaire Donated!",
            description=description,
            color=discord.Color.gold(),
        )
        embed.set_author(name="Mr. Billionaire", icon_url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
        embed.set_thumbnail(url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
        embed.set_image(url="https://i.giphy.com/WoRz0xf3fUBWTWXUJ0.webp")
        embed.set_footer(
            text=f"Claim within {config.DONATE_MESSAGE_TTL} seconds!",
            icon_url="https://giphy.com/static/img/giphy-logo.webp",
        )
        return embed

    def _has_recent_activity(self, guild_id: str) -> bool:
        """Check if there's been message activity in the last window."""
        window = datetime.now(timezone.utc) - timedelta(minutes=config.ROB_ACTIVITY_WINDOW_MIN)
        return activityChannels.count_documents(
            {"guild_id": guild_id, "last_at": {"$gt": window}},
            limit=1,
        ) > 0

    async def _donate_guild(self, guild_id: int):
        """Billionaire donates resources to the server. Anyone can claim."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        if not self._has_recent_activity(str(guild_id)):
            logger.info("No recent activity in guild %s, skipping donation.", guild_id)
            return

        channel = self._find_target_channel(guild)
        if not channel:
            return

        wood = random.randint(config.DONATE_WOOD_MIN, config.DONATE_WOOD_MAX)
        iron = 0
        if random.random() < config.DONATE_IRON_CHANCE:
            iron = random.randint(config.DONATE_IRON_MIN, config.DONATE_IRON_MAX)

        embed = self._build_donate_embed(wood, iron)
        view = DonateView(wood, iron)

        try:
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        except (discord.HTTPException, discord.NotFound):
            return

        await view.wait()

        if view.claimed:
            logger.info(
                "Billionaire donation claimed by %s in guild %s (%s wood, %s iron)",
                view.claimer_id, guild_id, wood, iron,
            )
        else:
            logger.info("Billionaire donation expired unclaimed in guild %s", guild_id)

    async def _rob_guild(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        if not self._has_recent_activity(str(guild_id)):
            logger.info("No recent activity in guild %s, skipping robbery.", guild_id)
            return

        channel = self._find_target_channel(guild)
        if not channel:
            return

        victim = await self._pick_victim(guild, channel)
        if not victim:
            return

        victim_id = str(victim.id)
        wood = self._get_wood(victim_id)
        who = f"<@{victim_id}>" if not is_muted(victim_id) else victim_id

        if wood <= 0:
            embed = self._build_robber_embed(
                f"{random.choice(ROAST_LINES)}\n\n...and he slips away."
            )
            view = RobberView(victim_id, 0, can_jail=False)
            try:
                await channel.send(
                    content=who,
                    embed=embed,
                    view=view,
                    delete_after=config.ROB_MESSAGE_TTL,
                )
            except (discord.HTTPException, discord.NotFound):
                pass
            return

        amount = random.randint(1, min(config.ROB_WOOD_MAX, wood))

        embed = self._build_robber_embed(
            f"**Billu Badmosh** robbed **{amount} \U0001fab5 wood** of resources!"
        )
        embed.set_footer(
            text=f"Jail him within {config.ROB_MESSAGE_TTL} seconds to get your wood back!"
        )

        view = RobberView(victim_id, amount, can_jail=True, on_jail=self._jail_billu)
        try:
            await channel.send(
                content=who,
                embed=embed,
                view=view,
                delete_after=config.ROB_MESSAGE_TTL,
            )
        except (discord.HTTPException, discord.NotFound):
            return

        await view.wait()

        if view.jailed:
            logger.info("Billu Badmosh was jailed in guild %s", guild_id)
            return

        logger.info(
            "Billu Badmosh stole %s wood from %s in guild %s",
            amount, victim_id, guild_id,
        )
        self._deduct_wood(victim_id, max(0, wood - amount))

    @tasks.loop(hours=1)
    async def robber_loop(self):
        now = datetime.now(timezone.utc)

        if self._is_jailed(now):
            logger.info(
                "Billu Badmosh is still in jail (until %s) \u2014 no robberies today.",
                self._jailed_until().isoformat(),
            )
            jitter = random.uniform(
                -config.ROB_INTERVAL_JITTER_MIN, config.ROB_INTERVAL_JITTER_MIN
            )
            self.robber_loop.change_interval(
                minutes=max(5, config.ROB_MEAN_INTERVAL_MIN + jitter)
            )
            return

        if self._jailed_until() is not None:
            self._release_billu()
            logger.info("Billu Badmosh has been released from jail.")

        for guild_id in config.availableIn.get("guilds", []):
            try:
                if random.random() < config.DONATE_CHANCE:
                    await self._donate_guild(int(guild_id))
                else:
                    await self._rob_guild(int(guild_id))
            except Exception as e:
                logger.exception(
                    "Rob/Donate routine failed for guild %s: %s", guild_id, e
                )

        jitter = random.uniform(
            -config.ROB_INTERVAL_JITTER_MIN, config.ROB_INTERVAL_JITTER_MIN
        )
        self.robber_loop.change_interval(
            minutes=max(5, config.ROB_MEAN_INTERVAL_MIN + jitter)
        )

    @robber_loop.before_loop
    async def before_robber_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Robber(bot))
