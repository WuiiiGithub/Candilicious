import discord, pymongo, traceback, os, config, random, re
from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands, ui
from library.logging import *
from typing import Union
from datetime import datetime, timezone

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

_db = pymongo.MongoClient(host=config.dbURI)[config.dbName]
serverCollection = _db["servers"]
configCollection = _db["config"]

class ConfirmTextView(ui.View):
    def __init__(self, content: str, author_id: int):
        super().__init__(timeout=60)
        self.content = content
        self.author_id = author_id

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        
        self.stop()
        try:
            configCollection.update_one(
                {"_id": "reminders"}, 
                {"$addToSet": {"texts": self.content}}, 
                upsert=True
            )
            embed = discord.Embed(
                title="Text Added Successfully",
                description=self.content[:1024],
                color=config.msgColor
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Failed to save: {e}", embed=None, view=None
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)

class ConfirmGifView(ui.View):
    def __init__(self, gif_url: str, author_id: int):
        super().__init__(timeout=60)
        self.gif_url = gif_url
        self.author_id = author_id

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        
        self.stop()
        try:
            configCollection.update_one(
                {"_id": "reminders"}, 
                {"$addToSet": {"gifs": self.gif_url}}, 
                upsert=True
            )
            embed = discord.Embed(
                title="✅ GIF Added Successfully",
                color=config.msgColor
            )
            embed.set_image(url=self.gif_url)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Failed to save: {e}", embed=None, view=None
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)

class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminders_cache = []
        self.gifs = []
        self.texts = []

        cogLog.log_cog(
            action="starting", 
            status_code=0, 
            details="Entered the Cog!"
        )

        # Start the background task
        self.study_reminder.start()

    def cog_unload(self):
        self.study_reminder.cancel()

    @app_commands.command(
        name="rconfig", description="Configure your reminder for server."
    )
    @app_commands.describe(
        time="No. of minutes to repeat reminding.",
        channel="Select a channel to remind",
        text="Footer text to be used to remind with.",
    )
    async def rconfig(
        self,
        inter: discord.Interaction,
        channel: Union[discord.TextChannel, discord.VoiceChannel] = None,
        time: int = None,
        text: str = None,
    ):
        try:
            serverDoc = serverCollection.find_one({"_id": str(inter.guild_id)}) or {}
            reminderDoc = serverDoc.get("reminders", {})

            if not reminderDoc and not (channel or time or text):
                await inter.response.send_message(
                    "Reminders not configured! Provide parameters to setup.",
                    ephemeral=True,
                )
                return
            
            isUpdated = False
            if channel:
                reminderDoc["channel"] = str(channel.id)
                isUpdated = True
            if time:
                reminderDoc["time"] = time
                isUpdated = True
            if text:
                reminderDoc["text"] = text
                isUpdated = True

            # Update DB
            serverCollection.update_one(
                {"_id": str(inter.guild_id)},
                {"$set": {"reminders": reminderDoc}},
                upsert=True,
            )

            # Refresh cache immediately
            await self.refresh_reminders_cache()

            title = "Reminder Config"
            if isUpdated:
                title = "Updated " + title
            embed = discord.Embed(
                title=title, 
                color=config.msgColor
            )
            embed.add_field(
                name="Channel", 
                value=f"<#{reminderDoc.get('channel', 'Not Set')}>",
                inline=True
            )
            embed.add_field(
                name="Time", value=f"{reminderDoc.get('time', 'Not Set')} mins",
                inline=True
            )
            embed.add_field(
                name="Text", 
                value=reminderDoc.get("text", "Not Set"),
                inline=False
            )
            await inter.response.send_message(embed=embed)
        except Exception:
            traceback.print_exc()

    async def refresh_reminders_cache(self):
        """
        Helper to pull data from DB into memory.
        """
        try:
            pipeline = [{"$match": {"reminders": {"$exists": True, "$ne": None}}}]
            self.reminders_cache = list(serverCollection.aggregate(pipeline))

            conf = configCollection.find_one({"_id": "reminders"})
            if conf:
                self.texts = conf.get("texts", ["Keep studying!"])
                self.gifs = conf.get(
                    "gifs",
                    [
                        "https://images-ext-1.discordapp.net/external/urjscwFcuDFRDEaUyi4CIuMKyP-HdabaYLF8_iB3sno/https/media.tenor.com/dS1sKvQgD4AAAAPo/hamster-ayasan.mp4"
                    ],
                )
        except Exception:
            traceback.print_exc()

    @tasks.loop(minutes=1)
    async def study_reminder(self):
        if not self.reminders_cache:
            await self.refresh_reminders_cache()
            return

        now = datetime.now(timezone.utc)

        for reminder in self.reminders_cache:
            data = reminder.get("reminders", {})
            interval_mins = data.get("time")
            channel_id = data.get("channel")
            last_sent = data.get("last_sent")

            if not interval_mins or not channel_id:
                continue

            should_send = False
            if last_sent is None:
                should_send = True
            else:
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)

                diff = (now - last_sent).total_seconds() / 60.0
                if diff >= interval_mins:
                    should_send = True

            if should_send:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    try:
                        embed = discord.Embed(
                            title="📖 STUDY TIME!",
                            description=f"**{random.choice(self.texts) if self.texts else 'Time to study!'}**",
                            color=discord.Color.red(),
                            timestamp=datetime.now(),
                        )
                        embed.set_footer(text=data.get("text", "Focus!"))
                        embed.set_image(url=random.choice(self.gifs))

                        await channel.send(
                            content="YOOO WAKEUP @everyone",
                            embed=embed,
                            delete_after=3600,
                        )

                        # Update DB (Sync call)
                        serverCollection.update_one(
                            {"_id": reminder["_id"]},
                            {"$set": {"reminders.last_sent": now}},
                        )
                        data["last_sent"] = now
                    except Exception as e:
                        print(f"Failed to send reminder to {reminder['_id']}: {e}")

    @study_reminder.before_loop
    async def before_study_reminder(self):
        await self.bot.wait_until_ready()
        await self.refresh_reminders_cache()

    async def add_gif_context(self, inter: discord.Interaction, message: discord.Message):
        if inter.user.id != config.owner_id:
            return await inter.response.send_message(
                "You are not allowed to use this command.", ephemeral=True
            )

        gif_url = None
        tenor_pattern = r'https?://[^\s<>]*tenor\.com[^\s<>]*'
        match = re.search(tenor_pattern, message.content)
        if match:
            gif_url = match.group(0)

        if not gif_url and message.attachments:
            gif_url = message.attachments[0].url
        elif not gif_url and message.embeds:
            for emb in message.embeds:
                if emb.image:
                    gif_url = emb.image.url
                    break

        if not gif_url:
            return await inter.response.send_message(
                "No valid GIF found in this message.", 
                ephemeral=True
            )

        # Show confirmation
        embed = discord.Embed(
            title="Confirm Adding this GIF?",
            color=discord.Color.yellow()
        )
        embed.set_image(url=gif_url)

        view = ConfirmGifView(gif_url=gif_url, author_id=inter.user.id)
        await inter.response.send_message(embed=embed, view=view)

    async def add_text_context(
        self, inter: discord.Interaction, message: discord.Message
    ):
        if inter.user.id != config.owner_id:
            return await inter.response.send_message(
                "You are not allowed to use this command.", ephemeral=True
            )

        content = message.content.strip()
        if len(content) < 15:
            return await inter.response.send_message(
                "Message too short to add (min 15 characters).", ephemeral=True
            )

        content = re.sub(r"\s+", " ", content)

        # Show confirmation
        embed = discord.Embed(
            title="Confirm Adding this Text?",
            description=content[:1024],
            color=config.msgColor
        )
        embed.set_footer(text="This will be used in study reminders.")

        view = ConfirmTextView(content=content, author_id=inter.user.id)
        await inter.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    Reminders_cog = Reminders(bot)

    gif_menu = app_commands.ContextMenu(
        name="Add GIF to Reminders", callback=cog.add_gif_context
    )
    text_menu = app_commands.ContextMenu(
        name="Add Text to Reminders", callback=cog.add_text_context
    )

    await bot.add_cog(Reminders_cog)

    guild_ids = config.availableIn.get("guilds", [])
    for g_id in guild_ids:
        guild_obj = discord.Object(id=g_id)
        bot.tree.add_command(gif_menu, guild=guild_obj)
        bot.tree.add_command(text_menu, guild=guild_obj)