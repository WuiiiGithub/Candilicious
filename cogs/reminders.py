import discord, pymongo, traceback, os, config, random, re, asyncio
from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands, ui
from library.logging import *
from datetime import datetime, timezone

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

_db = pymongo.MongoClient(host=config.MONGODB_URI)[config.DB_NAME]
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
            details="Reminders Cog Initialized"
        )

        # Start the background task
        self.study_reminder.start()

    def cog_unload(self):
        self.study_reminder.cancel()



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
            cogLog.log_cog(action="error", status_code=-100, details=f"Failed to refresh reminders cache:\n{traceback.format_exc()}")

    @tasks.loop(minutes=1)
    async def study_reminder(self):
        if not self.reminders_cache:
            await self.refresh_reminders_cache()
            return

        now = datetime.now(timezone.utc)
        taskLog = TaskLogger(filename=filename, task_name="study_reminder")
        sent_any = False

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

                        is_picked_member_bot = True
                        while is_picked_member_bot:
                            member = random.choice(channel.guild.members)
                            is_picked_member_bot = member.bot

                        await channel.send(
                            content=f"YOOO WAKEUP {member.mention}",
                            embed=embed
                        )

                        # Update DB (Sync call)
                        serverCollection.update_one(
                            {"_id": reminder["_id"]},
                            {"$set": {"reminders.last_sent": now}},
                        )
                        data["last_sent"] = now
                        taskLog.during(status_code=75, message="Success", details=f"Reminder successfully sent to channel {channel_id}")
                        sent_any = True
                    except Exception as e:
                        taskLog.during(status_code=-75, message="Fail", details=f"Failed to send reminder to {reminder['_id']}: {e}")
                        sent_any = True
        
        if sent_any:
            taskLog.send()

    @study_reminder.before_loop
    async def before_study_reminder(self):
        taskLog = TaskLogger(filename=filename, task_name="study_reminder")
        taskLog.before(status_code=0, message="Waiting", details="Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        taskLog.before(status_code=75, message="Ready", details="Bot is ready; refreshing reminders cache from database.")
        await self.refresh_reminders_cache()
        taskLog.send()

    async def add_gif_context(self, inter: discord.Interaction, message: discord.Message):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if inter.user.id != config.OWNER_ID:
                await inter.response.send_message(
                    "You are not allowed to use this command.", ephemeral=True
                )
                cmdLog.process(status_code=-100, name="Denied", details="Unauthorized user attempted to add a GIF.")
                return

            cmdLog.process(status_code=50, name="Processing", details="Searching for a valid GIF in the message...")
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
                await inter.response.send_message(
                    "No valid GIF found in this message.", 
                    ephemeral=True
                )
                cmdLog.process(status_code=-25, name="Missing", details="No GIF URL could be extracted from the message.")
                return

            # Show confirmation
            embed = discord.Embed(
                title="Confirm Adding this GIF?",
                color=discord.Color.yellow()
            )
            embed.set_image(url=gif_url)

            view = ConfirmGifView(gif_url=gif_url, author_id=inter.user.id)
            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Executed", details="Confirmation prompt for GIF addition has been sent.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    async def add_text_context(
        self, inter: discord.Interaction, message: discord.Message
    ):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if inter.user.id != config.OWNER_ID:
                await inter.response.send_message(
                    "You are not allowed to use this command.", ephemeral=True
                )
                cmdLog.process(status_code=-100, name="Denied", details="Unauthorized user attempted to add reminder text.")
                return

            cmdLog.process(status_code=50, name="Processing", details="Cleaning and validating the message content...")
            content = message.content.strip()
            if len(content) < 15:
                await inter.response.send_message(
                    "Message too short to add (min 15 characters).", ephemeral=True
                )
                cmdLog.process(status_code=-25, name="Warning", details="The message provided is too short for a reminder.")
                return

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
            cmdLog.process(status_code=100, name="Executed", details="Confirmation prompt for text addition has been sent.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(
        name="reminder",
        description="Set a reminder for yourself."
    )
    @app_commands.describe(
        days="Number of days until the reminder.",
        hrs="Number of hours until the reminder.",
        mins="Number of minutes until the reminder.",
        secs="Number of seconds until the reminder.",
        text="The message for the reminder."
    )
    async def reminder(
        self,
        inter: discord.Interaction,
        days: int = 0,
        hrs: int = 0,
        mins: int = 0,
        secs: int = 0,
        text: str = "Times up! 🔔"
    ):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Input Calc", details="Calculating total wait time for the reminder...")
            total_seconds = secs + (mins * 60) + (hrs * 3600) + (days * 86400)

            if total_seconds <= 0:
                total_seconds = 300

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Reminder Set!",
                    description=f"Your reminder has been set for {days} days, {hrs} hours, {mins} minutes, and {secs} seconds.\nMessage: {text}",
                    color=config.msgColor
                ),
                ephemeral=True
            )

            cmdLog.process(status_code=100, name="Task Set", details=f"Reminder successfully scheduled for {total_seconds} seconds from now.")
            asyncio.create_task(self.reminder_runner(inter.user, total_seconds, text))
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    async def reminder_runner(self, user: discord.User, time: int, text: str):
        taskLog = TaskLogger(filename=filename, task_name="reminder_runner")
        try:
            taskLog.before(status_code=50, message="Delaying", details=f"Beginning {time}s wait before delivering reminder to {user.name}")
            taskLog.send()
            await asyncio.sleep(time)

            resLog = TaskLogger(filename=filename, task_name="reminder_runner")
            await user.send(
                embed=discord.Embed(
                    title="⏰ Reminder",
                    description=text,
                    color=config.msgColor,
                    timestamp=datetime.now()
                )
            )
            resLog.after(status_code=100, message="DM Send", details=f"Reminder successfully delivered to {user.name}.")
            resLog.send()
        except discord.Forbidden:
            resLog.after(status_code=-25, message="DM Blocked", details=f"Unable to send reminder DM to {user.name}; they may have DMs disabled.")
            resLog.send()
        except Exception as e:
            resLog.after(status_code=-100, message="Error", details=str(e))
            resLog.send()

async def setup(bot: commands.Bot):
    Reminders_cog = Reminders(bot)

    gif_menu = app_commands.ContextMenu(
        name="Add GIF to Reminders", callback=Reminders_cog.add_gif_context
    )
    text_menu = app_commands.ContextMenu(
        name="Add Text to Reminders", callback=Reminders_cog.add_text_context
    )

    await bot.add_cog(Reminders_cog)

    guild_ids = config.availableIn.get("guilds", [])
    for g_id in guild_ids:
        guild_obj = discord.Object(id=g_id)
        bot.tree.add_command(gif_menu, guild=guild_obj)
        bot.tree.add_command(text_menu, guild=guild_obj)
