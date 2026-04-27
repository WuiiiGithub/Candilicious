import discord, pymongo, traceback, os, config, random, re
from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands
from library.logging import *
from typing import Union
from datetime import datetime, timezone

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

_db = pymongo.MongoClient(host=config.dbURI)[config.dbName]
serverCollection = _db['server']
configCollection = _db['config']

class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminders = None

        self.isReminderConfigChanged = False
        self.gifs = None
        self.texts = None

        self.contextMenus = [
            app_commands.ContextMenu(
                name='Add GIF',
                callback=self.add_GIF,
            ),
            app_commands.ContextMenu(
                name='Add TXT',
                callback=self.add_TXT,
            )
        ]
        cogLog.log_cog(
            action='starting',
            status_code=0,
            details='Entered the Cog!'
        )

    @commands.Cog.listener()
    async def on_ready(self):
        cogLog.log_cog(
            action='syncing',
            status_code=0,
            details='Sycing with the Bot Tree!'
        )
        await self.bot.tree.sync()
        cogLog.log_cog(
            action='syncing',
            status_code=0,
            details='Sycing with the Bot Tree!'
        )

    @app_commands.command(name="rconfig", description="Configure your reminder for server.")
    @app_commands.describe(
        time='No. of minutes to repeat reminding.',
        channel='Select a channel to remind',
        text='Footer text to be used to remind with.'
    )
    async def rconfig(self, inter: discord.Interaction, channel: Union[discord.TextChannel, discord.VoiceChannel]=None, time: int=None, text: str=None):
        try:
            serverDoc = serverCollection.find_one({'_id': str(inter.guild_id)})             
            reminderDoc = {}
            if serverDoc:
                reminderDoc = serverDoc.get('reminders', {})
            
            if not reminderDoc and not (channel or time or text):
                await inter.response.send_message(
                    embed=discord.Embed(
                        description='Reminders not configured!',
                        color=config.msgColor
                    ),
                    ephemeral=True 
                )
                return
                
            didUpdateFlag = False
            if channel:
                reminderDoc['channel'] = channel.id
                didUpdateFlag = True
            if time:
                reminderDoc['time'] = time
                didUpdateFlag = True
            if text:
                reminderDoc['text'] = text
                didUpdateFlag = True

            title = 'Reminder Config'
            if didUpdateFlag:
                serverCollection.update_one(
                    {'_id': str(inter.guild_id)},
                    {
                        "$set": {
                            "reminders": reminderDoc
                        }
                    },
                    upsert=True 
                )
                title += ' Updated'

            embed = discord.Embed(
                title=title,
                color=config.msgColor
            )
            embed.add_field(
                name='Channel',
                value=f"<#{reminderDoc.get('channel', 'Not Set')}>",
                inline=False
            )
            embed.add_field(
                name='Time',
                value=f"{reminderDoc.get('time', 'Not Set')} mins",
                inline=False
            )
            embed.add_field(
                name='Text',
                value=reminderDoc.get('text', 'Not Set'),
                inline=False
            )
            await inter.response.send_message(embed=embed)
        except Exception as e:
            traceback.print_exc()

    @tasks.loop(minutes=60)
    async def study_reminder(self):
        if self.reminders == []:
            return
        else:
            # After fetching data, send reminders
            for reminder in self.reminders:
                now = datetime.now(timezone.utc)
                interval = float(reminder.get("time", 180))
                last_sent = reminder.get("last_sent")

                should_send = False
                if last_sent is None:
                    should_send = True
                else:
                    # Ensuring last sent should be timezone aware
                    if last_sent.tzinfo is None:
                        last_sent = last_sent.replace(tzinfo=timezone.utc)
                    
                    diff = (now - last_sent).total_seconds() / 60.0
                    if diff >= interval:
                        should_send = True

                if should_send:
                    channel = self.bot.get_channel(reminder["reminders"]["channel"]) 
                    if channel:
                        embed = discord.Embed(
                            title="📖 STUDY TIME!",
                            description=f"**{random.choice(self.texts)}**",
                            color=discord.Color.red(),
                            timestamp=datetime.now()
                        )                        
                        embed.set_footer(text=reminder['reminders']["text"])
                        embed.set_image(url=random.choice(self.gifs))
                        
                        await channel.send(content="YOOO WAKEUP @everyone", embed=embed, delete_after=60*1.9)

                        # Update last_sent in DB
                        await serverCollection.update_one(
                            filter={
                                "_id": reminder['_id']
                            },
                            update={
                                "$set": {
                                    "reminders.last_sent": now
                                }
                            }
                        )

    @study_reminder.before_loop
    async def before_study_reminder(self):
        try:
            pipeline = [
                {
                    "$match": {
                        "reminder": {
                            "$exists": True,
                            "$ne": None
                        }
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "reminders": 1
                    }
                }
            ]
            self.reminders = list(serverCollection.aggregate(pipeline))
            print(self.reminders)
            if self.isReminderConfigChanged:
                data = configCollection.find_one({"name": "reminders"})
                self.texts, self.gifs = data['texts'], data['gifs']
        except Exception as e:
            traceback.print_exc()
        
    async def add_GIF(self, inter: discord.Interaction, message: discord.Message):

        if inter.user.id != config.owner_id:
            await inter.response.send_message(
                "You are not allowed to use this command.",
                ephemeral=True
            )
            return

        gif_url = None

        #  Attachments (most reliable)
        if message.attachments:
            for att in message.attachments:
                if att.filename.lower().endswith(("gif", "webp", "mp4")):
                    gif_url = att.url
                    break

        #  Embed images (Tenor/Giphy often land here)
        if not gif_url and message.embeds:
            for emb in message.embeds:
                if emb.image and emb.image.url:
                    gif_url = emb.image.url
                    break

        # Regex from message content
        if not gif_url:
            match = re.search(
                r"(https?://[^\s]+?\.(?:gif|webp|mp4)(\?[^\s]*)?)", 
                message.content
            )
            if match:
                gif_url = match.group(1)

        # Validation
        if not gif_url:
            embed = discord.Embed(
                description="No valid GIF found in this message.",
                color=config.msgColor
            )
            await inter.response.send_message(
                embed,
                ephemeral=True
            )
            return

        # 5. DB update (no duplicates)
        configCollection.update_one(
            {"name": "reminders"},
            {"$addToSet": {"gifs": gif_url}}
        )

        embed = discord.Embed(
            description="GIF Added ✅",
            color=config.msgColor
        )
        embed.set_image(url=gif_url)

        await inter.response.send_message(embed=embed, ephemeral=True)

    async def add_TXT(self, inter: discord.Interaction, message: discord.Message):

        if inter.user.id != config.owner_id:
            await inter.response.send_message(
                "You are not allowed to use this command.",
                ephemeral=True
            )
            return

        text = message.content.strip()

        # Filtering small/empty messages
        if len(text) < 15:
            await inter.response.send_message(
                "Message too short to add.",
                ephemeral=True
            )
            return

        # removing spammy whitespace
        text = re.sub(r"\s+", " ", text)

        # DB update
        configCollection.update_one(
            {"name": "reminders"},
            {"$addToSet": {"texts": text}}
        )

        embed = discord.Embed(
            description="Text Added ✅", 
            color=config.msgColor
        )
        embed.add_field(name="Saved Text", value=text[:1024], inline=False)

        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    Reminders_cog = Reminders(bot)
    await bot.add_cog(Reminders_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in Reminders_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))
        for ctxMenu in Reminders_cog.contextMenus:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(ctxMenu, guild=discord.Object(id=guild_id))