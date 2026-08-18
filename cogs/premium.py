import discord, os, pymongo, traceback, config
from discord.ext import commands
from discord import app_commands
from typing import Optional
from library.logging import CogLogger, CommandLogger
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
                old_exp = existing.get("expire_at")
                if isinstance(old_exp, datetime):
                    if old_exp.tzinfo is None:
                        old_exp = old_exp.replace(tzinfo=timezone.utc)
                    if old_exp > datetime.now(timezone.utc):
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

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="✖\ufe0f")
    async def cancel_button(self, inter: discord.Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.user_id:
            return await inter.response.send_message("This isn't your menu.", ephemeral=True)
        await inter.response.edit_message(content="Cancelled.", embed=None, view=None)
        self.stop()


class Premium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Premium Cog Initialized")

    @app_commands.command(name="subscribe", description="Subscribe to premium or redeem an offer code")
    @app_commands.describe(code="Optional offer code to redeem")
    async def subscribe(self, inter: discord.Interaction, code: Optional[str] = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)
            user_data = userCollection.find_one({"_id": user_id})
            if not user_data:
                return await inter.response.send_message(
                    embed=discord.Embed(description="No account found. Visit the website first.", color=discord.Color.red()),
                    ephemeral=True
                )

            if code:
                offer = premiumOffersCollection.find_one({"code": code.upper()})
                if not offer:
                    return await inter.response.send_message(
                        embed=discord.Embed(description="Invalid offer code.", color=discord.Color.red()),
                        ephemeral=True
                    )
                now = datetime.now(timezone.utc)
                expire_at = now + timedelta(days=offer.get("ttl_days", config.PREMIUM_TTL_DAYS))

                existing = premiumCollection.find_one({"user_id": user_id})
                if existing:
                    old_exp = existing.get("expire_at")
                    if isinstance(old_exp, datetime):
                        if old_exp.tzinfo is None:
                            old_exp = old_exp.replace(tzinfo=timezone.utc)
                        if old_exp > now:
                            expire_at = old_exp + timedelta(days=offer.get("ttl_days", config.PREMIUM_TTL_DAYS))

                userCollection.update_one(
                    {"_id": user_id},
                    {"$set": {
                        "premium.type": "pro",
                        "premium.purchased_at": now,
                        "premium.expire_at": expire_at,
                    }}
                )
                premiumCollection.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "type": "pro",
                        "purchased_at": now,
                        "expire_at": expire_at,
                    }},
                    upsert=True
                )
                premiumOffersCollection.delete_one({"code": code.upper()})

                embed = discord.Embed(
                    title="Premium Activated",
                    description=f"Offer redeemed! Expires: <t:{int(expire_at.timestamp())}:R>",
                    color=discord.Color.green()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                cmdLog.process(status_code=100, name="Offer Redeemed", details=f"Code {code} redeemed")
                return

            existing = premiumCollection.find_one({"user_id": user_id})
            if existing:
                old_exp = existing.get("expire_at")
                if isinstance(old_exp, datetime):
                    if old_exp.tzinfo is None:
                        old_exp = old_exp.replace(tzinfo=timezone.utc)
                    if old_exp > datetime.now(timezone.utc):
                        return await inter.response.send_message(
                            embed=discord.Embed(
                                description=f"You're already **Pro**!\nExpires: <t:{int(old_exp.timestamp())}:R>",
                                color=discord.Color.green()
                            ),
                            ephemeral=True
                        )

            embed = discord.Embed(
                title="Candilicious Pro",
                description=(
                    f"Unlock VC Shield, boost XP, and more.\n\n"
                    f"**Cost:** {config.PREMIUM_COST} {UNIT_TITLE}\n"
                    f"**Duration:** {config.PREMIUM_TTL_DAYS} days"
                ),
                color=discord.Color.gold()
            )
            view = SubscribeView(user_id=user_id, cost=config.PREMIUM_COST, duration_days=config.PREMIUM_TTL_DAYS)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
            cmdLog.process(status_code=0, name="Sub Menu", details="Sent subscribe menu")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="unsubscribe", description="Cancel your premium subscription")
    async def unsubscribe(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)
            existing = premiumCollection.find_one({"user_id": user_id})
            if not existing:
                return await inter.response.send_message(
                    embed=discord.Embed(description="You don't have an active subscription.", color=discord.Color.red()),
                    ephemeral=True
                )

            premiumCollection.delete_one({"user_id": user_id})
            userCollection.update_one(
                {"_id": user_id},
                {"$set": {"premium.expire_at": datetime.now(timezone.utc)}}
            )

            await inter.response.send_message(
                embed=discord.Embed(description="Your **Pro** subscription has been cancelled.", color=discord.Color.orange()),
                ephemeral=True
            )
            cmdLog.process(status_code=100, name="Unsubscribed")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Premium_cog = Premium(bot)
    await bot.add_cog(Premium_cog)
