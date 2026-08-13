import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

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

ROAST_LINES = [
    "Nothing to rob here! Someone skipped too many study sessions.",
    "Zero wood? Go study first, then we'll talk business!",
    "I came for your wood but found nothing but excuses. Hit the books, my friend!",
    "Your pockets are as empty as your study logs. Get back to studying!",
    "Not a single piece of wood to steal — that's what no studying does to a person!",
    "Even your wood is scared of you. Try studying, then I'll come back for a real robbery!",
    "This robbery is a bust! Come back when you've actually studied and earned some wood!",
    "I'd rob you, but your wallet has cobwebs. Maybe open a book before opening a shop!",
]


class RobberView(ui.View):
    """The jail button. Only the victim can press it.

    The view times out after ``config.ROB_MESSAGE_TTL`` seconds; if the victim
    presses jail before that, ``jailed`` is set, ``on_jail`` fires (locking
    Billu up for the day) and ``stop()`` is called so the caller knows the wood
    must be returned instead of stolen.
    """

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

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed is not None:
            embed.description = (
                f"\U0001f6a8 Police caught **Billu Badmosh**! He's locked up for "
                f"the rest of the day. Your **{self.amount} \U0001fab5 wood** "
                f"is safe — money returned!"
            )
            embed.color = discord.Color.green()

        await interaction.response.edit_message(
            content=interaction.message.content, embed=embed, view=self
        )
        self.stop()


class Robber(commands.Cog):
    """Billu Badmosh — a mischievous robber who visits every server roughly
    every hour (plus or minus a random 15 minutes).

    He picks a random member, tries to steal up to 50 wood from them and gives
    the victim 10 seconds to hit the Jail button. If jailed, the police catch
    him and the wood is returned. Otherwise the wood is gone. Victims with no
    wood at all just get roasted instead.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.robber_loop.start()

        cogLog.log_cog(
            action="starting",
            status_code=0,
            details="Billu Badmosh cog has been initialized.",
        )

    def cog_unload(self):
        self.robber_loop.cancel()

    def _find_target_channel(self, guild: discord.Guild):
        """Prefer the server's general channel, else its default channel."""
        candidates = [
            c
            for c in guild.text_channels
            if c.permissions_for(guild.me).send_messages
        ]
        if not candidates:
            return None

        for channel in candidates:
            if channel.name.lower() in ("general", "general-chat", "main", "main-chat"):
                return channel

        if (
            guild.system_channel
            and guild.system_channel.permissions_for(guild.me).send_messages
        ):
            return guild.system_channel

        return candidates[0]

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
        """Lock Billu up for the rest of the current (UTC) day."""
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

    async def _rob_guild(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = self._find_target_channel(guild)
        if not channel:
            return

        members = [m for m in guild.members if not m.bot]
        if not members:
            try:
                members = [m async for m in guild.fetch_members() if not m.bot]
            except Exception:
                members = []
        if not members:
            return

        victim = random.choice(members)
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
                "Billu Badmosh is still in jail (until %s) — no robberies today.",
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
                await self._rob_guild(int(guild_id))
            except Exception as e:
                logger.exception(
                    "Robbery routine failed for guild %s: %s", guild_id, e
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
