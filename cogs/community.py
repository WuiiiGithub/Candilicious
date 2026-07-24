import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback, random
from library.logging import CogLogger, CommandLogger, ListenerLogger
from library import degrade

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.DB_NAME]
userCollection = db["users"]

FIND_COST = 25


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()
        cogLog.log_cog(action="starting", status_code=0, details="Community Cog has been initialized and is ready for member interactions.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Community cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.guild_only()
    @app_commands.command(name='find', description='Find a study buddy.')
    async def find(self, inter: discord.Interaction):
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
                        description=f"You need **{FIND_COST} Iron** to find a buddy. You have **{int(iron_amount)} Iron**.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            await inter.response.defer(ephemeral=True)

            all_users = list(userCollection.find(
                {"_id": {"$ne": user_id}},
                {"_id": 1, "name": 1, "display_name": 1, "profile_pfp": 1}
            ))

            if not all_users:
                await inter.followup.send(
                    embed=discord.Embed(description="No other users found to pair with!", color=discord.Color.orange()),
                    ephemeral=True
                )
                return

            picked = random.choice(all_users)

            userCollection.update_one(
                {"_id": user_id},
                {"$set": {
                    "economy.resources.iron.amount": iron_amount - FIND_COST,
                    "economy.resources.iron.degraded_at": iron_dt,
                }}
            )

            display_name = picked.get("display_name") or picked.get("name") or "Unknown"
            pfp_url = picked.get("profile_pfp") or f"https://cdn.discordapp.com/embed/avatars/{int(picked['_id']) % 5}.png"

            embed = discord.Embed(
                title=display_name,
                description=f"You found a study buddy! Say hi to **{display_name}**.",
                color=config.msgColor
            )
            embed.set_thumbnail(url=pfp_url)
            embed.set_footer(text=f"-{FIND_COST} Iron")

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="View Profile",
                url=f"{config.FRONTEND_DOMAIN}/profile?user={picked['_id']}"
            ))

            await inter.followup.send(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Find Buddy", details=f"User {user_id} found buddy {picked['_id']} (-{FIND_COST} iron)")

        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Community_cog = Community(bot)
    await bot.add_cog(Community_cog)
