import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import os, traceback, random
from library.logging import CogLogger, CommandLogger
from library import degrade, db
from library.usersync import sync_member_from_discord

filename = __name__.title()
cogLog = CogLogger(filename=filename)

userCollection = db["users"]

FIND_COST = 25


class FindView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Payment", style=discord.ButtonStyle.green)
    async def pay_button(self, inter: discord.Interaction, button: discord.ui.Button):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if str(inter.user.id) != self.user_id:
                return await inter.response.send_message("This isn't your menu.", ephemeral=True)

            user_data = userCollection.find_one({"_id": self.user_id})
            if not user_data:
                return await inter.response.send_message("No account found. Visit the website first.", ephemeral=True)

            resources = user_data.get("economy", {}).get("resources", {})
            iron_data = resources.get("iron", {})
            iron_amount, iron_dt = degrade.apply(
                iron_data.get("amount", 0),
                iron_data.get("degraded_at"),
                0.03
            )

            if iron_amount < FIND_COST:
                return await inter.response.send_message(
                    f"You need **`{FIND_COST}`** Iron to find a buddy. You have **`{int(iron_amount)}`** Iron.",
                    ephemeral=True
                )

            all_users = list(userCollection.find(
                {"_id": {"$ne": self.user_id}},
                {"_id": 1, "name": 1, "display_name": 1, "profile_pfp": 1}
            ))

            if not all_users:
                return await inter.response.send_message(
                    embed=discord.Embed(description="No other users found to pair with!", color=discord.Color.orange()),
                    ephemeral=True
                )

            picked = random.choice(all_users)
            picked_id = picked["_id"]

            userCollection.update_one(
                {"_id": self.user_id},
                {"$set": {
                    "economy.resources.iron.amount": iron_amount - FIND_COST,
                    "economy.resources.iron.degraded_at": iron_dt,
                }}
            )

            synced = sync_member_from_discord(userCollection, picked_id, inter.guild)
            if synced:
                picked = {**picked, **{k: v for k, v in discord_user_doc_from_store(synced).items() if v}}

            display_name = picked.get("display_name") or picked.get("name") or "Unknown"
            pfp = picked.get("profile_pfp") or picked.get("pfp")
            pfp_url = pfp if (pfp and pfp.startswith(("https://", "data:"))) else (
                f"https://cdn.discordapp.com/avatars/{picked_id}/{pfp}.png" if pfp else f"https://cdn.discordapp.com/embed/avatars/{int(picked_id) % 5}.png"
            )

            buddy_lines = [
                f"**{display_name}** matched with you! Say hi and start studying together.",
                f"The search is over — **{display_name}** is your new study partner!",
                f"**{display_name}** is ready to join you. Time to hit the books!",
                f"Great news! **{display_name}** wants to study with you.",
                f"Search complete — **{display_name}** is could be your study buddy!",
                f"Here's your buddy: **{display_name}**. Good luck studying!",
            ]
            intro = random.choice(buddy_lines)

            embed = discord.Embed(
                title="\U0001f44b Buddy Found!",
                description=f"{intro}",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=pfp_url)
            embed.add_field(
                name="\U0001f4d6 What's next?",
                value=(
                    "1. Send a friendly hello \U0001f44b\n"
                    "2. Pick a time to study together \U0001f4c5\n"
                    "3. Crush your goals \U0001f680\n"
                ),
                inline=False
            )

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="View Profile",
                url=f"{config.FRONTEND_DOMAIN}/profile?user={picked_id}"
            ))

            await inter.response.edit_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Find Buddy", details=f"User {self.user_id} found buddy {picked_id} (-{FIND_COST} iron)")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
            if not inter.response.is_done():
                await inter.response.send_message("Something went wrong.", ephemeral=True)
        finally:
            cmdLog.send()
            self.stop()


def discord_user_doc_from_store(user_data: dict) -> dict:
    """Normalize a stored users doc into name/display/pfp fields."""
    if not user_data:
        return {}
    return {
        "name": user_data.get("name"),
        "display_name": user_data.get("display_name"),
        "pfp": user_data.get("pfp") or user_data.get("profile_pfp"),
    }


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()
        cogLog.log_cog(action="starting", status_code=0, details="Community Cog has been initialized and is ready for member interactions.")

    @commands.Cog.listener()
    async def on_interaction(self, inter: discord.Interaction):
        if inter.type != discord.InteractionType.application_command or inter.user is None or inter.user.bot:
            return
        if inter.guild is None:
            return
        try:
            sync_member_from_discord(userCollection, str(inter.user.id), inter.guild)
        except Exception:
            pass

    @app_commands.guild_only()
    @app_commands.command(name='lookup', description='Find a study buddy.')
    async def lookup(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)

            user_data = userCollection.find_one({"_id": user_id})
            if not user_data:
                await inter.response.send_message(
                    embed=discord.Embed(description="No account found. Visit the website first.", color=discord.Color.red()),
                    ephemeral=True
                )
                return

            resources = user_data.get("economy", {}).get("resources", {})
            iron_data = resources.get("iron", {})
            iron_amount, iron_dt = degrade.apply(
                iron_data.get("amount", 0),
                iron_data.get("degraded_at"),
                0.03
            )

            if iron_amount < FIND_COST:
                await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"You need **`{FIND_COST}`** Iron to find a buddy. You have **`{int(iron_amount)}`** Iron.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            amt = int(iron_amount)
            embed = discord.Embed(
                title="\U0001f4b3 Find a Study Buddy",
                description=(
                    f"This will cost **`{FIND_COST}`** Iron to find a study buddy.\n"
                    f"You currently have **`{amt}`** Iron.\n"
                    f"Press the button below to confirm the payment."
                ),
                color=discord.Color.green()
            )

            view = FindView(user_id)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
            cmdLog.process(status_code=100, name="Preview Sent", details=f"User {user_id} shown find preview (-{FIND_COST} iron)")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Community_cog = Community(bot)
    await bot.add_cog(Community_cog)
