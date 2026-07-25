import discord, os, pymongo, traceback, config
from discord.ext import commands
from discord import app_commands
from typing import Optional
from library.logging import CogLogger, CommandLogger, ListenerLogger
from library import degrade, db
from datetime import datetime, timezone, timedelta

filename = __name__.title()
cogLog = CogLogger(filename=filename)

premiumCollection = db["premium"]
premiumOffersCollection = db["premium.offers"]
userCollection = db["users"]

try:
    premiumCollection.drop_index("expire_at_1")
except pymongo.errors.OperationFailure:
    pass
premiumCollection.create_index("expire_at", expireAfterSeconds=0)
premiumOffersCollection.create_index("code", unique=True)

RESOURCE_UNIT = getattr(config, "PREMIUM_UNIT", "iron")
UNIT_EMOJI = "\U0001fab5" if RESOURCE_UNIT == "wood" else "\U0001f529"
UNIT_TITLE = RESOURCE_UNIT.title()


class SubscribeView(discord.ui.View):
    def __init__(self, user_id: str, cost: int, duration_days: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cost = cost
        self.duration_days = duration_days

    @discord.ui.button(label="Pay", style=discord.ButtonStyle.green)
    async def pay_button(self, inter: discord.Interaction, button: discord.ui.Button):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if str(inter.user.id) != self.user_id:
                return await inter.response.send_message("This isn't your menu.", ephemeral=True)

            user_data = userCollection.find_one({"_id": self.user_id})
            if not user_data:
                return await inter.response.send_message("No account found. Visit the website first.", ephemeral=True)

            existing = premiumCollection.find_one({"user_id": self.user_id})
            if existing:
                return await inter.response.send_message("You're already subscribed!", ephemeral=True)

            resources = user_data.get("economy", {}).get("resources", {})
            unit_data = resources.get(RESOURCE_UNIT, {})
            unit_amount, unit_dt = degrade.apply(
                unit_data.get("amount", 0),
                unit_data.get("degraded_at"),
                0.03
            )

            if unit_amount < self.cost:
                return await inter.response.send_message(
                    f"You need **{self.cost} {UNIT_TITLE}**. You have **{unit_amount} {UNIT_TITLE}**.",
                    ephemeral=True
                )

            now = datetime.now(timezone.utc)
            expire_at = now + timedelta(days=self.duration_days)

            userCollection.update_one(
                {"_id": self.user_id},
                {"$set": {
                    f"economy.resources.{RESOURCE_UNIT}.amount": unit_amount - self.cost,
                    f"economy.resources.{RESOURCE_UNIT}.degraded_at": unit_dt,
                    "premium.type": "pro",
                    "premium.purchased_at": now,
                    "premium.expire_at": expire_at,
                }}
            )

            premiumCollection.insert_one({
                "user_id": self.user_id,
                "type": "pro",
                "purchased_at": now,
                "expire_at": expire_at,
            })

            button.disabled = True
            await inter.response.edit_message(view=self)
            await inter.followup.send(
                f"You're now a **Pro** subscriber! \U0001f389\n**-{self.cost}** {UNIT_EMOJI} {UNIT_TITLE}\nExpires: <t:{int(expire_at.timestamp())}:R>",
                ephemeral=True
            )
            cmdLog.process(status_code=100, name=f"Subscribed Pro \u2014 {self.cost} {UNIT_TITLE}")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
            if not inter.response.is_done():
                await inter.response.send_message("Something went wrong.", ephemeral=True)
        finally:
            cmdLog.send()
            self.stop()


class Premium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Premium Cog Initialized")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Syncing Tree")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success")
        except Exception:
            log.error(status_code=-100, message="Sync Failed", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.command(name="subscribe", description="Subscribe to premium or redeem an offer code")
    async def subscribe(self, inter: discord.Interaction, code: Optional[str] = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            await inter.response.send_message(
                embed=discord.Embed(
                    description="This command will be available in the next release.",
                    color=discord.Color.blurple()
                ),
                ephemeral=True
            )
            cmdLog.process(status_code=100, name="Disabled", details="Subscribe command disabled — future release.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="unsubscribe", description="Cancel your premium subscription")
    async def unsubscribe(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            await inter.response.send_message(
                embed=discord.Embed(
                    description="This command will be available in the next release.",
                    color=discord.Color.blurple()
                ),
                ephemeral=True
            )
            cmdLog.process(status_code=100, name="Disabled", details="Unsubscribe command disabled — future release.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Premium_cog = Premium(bot)
    await bot.add_cog(Premium_cog)
