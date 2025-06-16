from __future__ import annotations
from discord import (
    Embed,
    Interaction,
    app_commands,
    Object,
    utils,
    FFmpegPCMAudio
)
from datetime import timedelta
import os, config, pymongo
from traceback import print_exc
from discord.ext import commands

memes = {
    "audio": {},
    "effects": {}
}

serverCollection = pymongo.MongoClient(os.getenv('MONGODB_URI'))[config.dbName]['Servers']

for filename in os.listdir('static/memes/audio/songs'):
    file_path = os.path.join('static/memes/audio/songs', filename)
    if os.path.isfile(file_path):
        base_name = os.path.splitext(os.path.basename(filename))[0].title()
        abs_path = os.path.abspath(file_path)
        memes['audio'][base_name] = abs_path

for filename in os.listdir('static/memes/audio/effects'):
    file_path = os.path.join('static/memes/audio/effects', filename)
    if os.path.isfile(file_path):
        base_name = os.path.splitext(os.path.basename(filename))[0].title()
        abs_path = os.path.abspath(file_path)
        memes['effects'][base_name] = abs_path

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
        except:
            print_exc()

    # commands
    @app_commands.command(name="plays", description="Play meme songs in VC")
    @app_commands.choices(sound = [
        app_commands.Choice(name=name.replace('-', ' '), value=name) for name in memes['audio'].keys()
    ])
    async def play_sound(
        self,
        inter: Interaction,
        sound: str
    ):
        try:
            serverDetails = serverCollection.find_one({'_id': str(inter.guild_id)})
            if serverDetails==None:
                print("The server is not configured")
                await inter.response.send_message(embed=Embed(
                    description='The server is not configured. Please configure the server and try again later.',
                    color=config.msgColor
                ))

            file_path = memes['audio'][sound]
            voice = inter.user.voice

            if not voice:
                await inter.response.send_message("You need to be in a voice channel!", ephemeral=True)
                return
            
            if serverDetails['channel'] == str(voice.channel.id):
                await inter.response.send_message(embed=Embed(
                    description="Sorry, You can't play memes in study channel.",
                    color=config.msgColor
                ))
                return
            
            if not os.path.isfile(file_path):
                await inter.response.send_message("Sound file not found!", ephemeral=True)
                return
            vc = await voice.channel.connect()
            await inter.response.send_message(f"🎵 Playing *{sound.replace('-', ' ')}* ~*{inter.user.display_name}*")
            vc.play(FFmpegPCMAudio(file_path), after=lambda e: print(f"Finished playing: {e}"))
            while vc.is_playing():
                await utils.sleep_until(utils.utcnow() + timedelta(seconds=1))
            await vc.disconnect()
        except Exception as e:
            print_exc()
        
    @app_commands.command(name="playeff", description="Play meme effects in VC")
    @app_commands.choices(sound = [
        app_commands.Choice(name=name.replace('-', ' '), value=name) for name in memes['effects'].keys()
    ])
    async def play_effects(
        self,
        inter: Interaction,
        sound: str
    ):
        try:
            serverDetails = serverCollection.find_one({'_id': str(inter.guild_id)})
            if serverDetails==None:
                print("The server is not configured")
                await inter.response.send_message(embed=Embed(
                    description='The server is not configured. Please configure the server and try again later.',
                    color=config.msgColor
                ))
                return

            file_path = memes['effects'][sound]
            voice = inter.user.voice
            
            if not voice:
                await inter.response.send_message("You need to be in a voice channel!", ephemeral=True)
                return
            
            if serverDetails['channel'] == str(voice.channel.id):
                await inter.response.send_message(embed=Embed(
                    description="Sorry, You can't play memes in study channel.",
                    color=config.msgColor
                ))  
                return
            
            if not os.path.isfile(file_path):
                await inter.response.send_message("Sound file not found!", ephemeral=True)
                return
            vc = await voice.channel.connect()
            await inter.response.send_message(f"🎵 Playing *{sound.replace('-', ' ')}*   ~*{inter.user.display_name}*")
            vc.play(FFmpegPCMAudio(file_path), after=lambda e: print(f"Finished playing: {e}"))
            while vc.is_playing():
                await utils.sleep_until(utils.utcnow() + timedelta(seconds=1))
            await vc.disconnect()
        except Exception as e:
            print_exc()

async def setup(bot):
    General_cog = Fun(bot)
    await bot.add_cog(General_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in General_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=Object(id=guild_id))