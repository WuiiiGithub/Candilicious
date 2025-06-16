import discord
import config
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import os, pymongo, traceback
from library import logging, session

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.dbName]

#dlog = logging.Logger("Server", style="default")

class Server(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeMembers = set()

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
        except:
            traceback.print_exc()

    @app_commands.guild_only()
    @app_commands.command(name='attendence', description='Mark your attendence here :)')
    async def find(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )
    
    @app_commands.guild_only()
    @app_commands.command(name='clean', description='Remove all inactive people in server.')
    async def clean(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )
    
    @app_commands.guild_only()
    @app_commands.command(name='invite', description='Manage invite links to users.')
    async def invite(self, inter: discord.Interaction):
        link = await inter.channel.create_invite()
        await inter.response.send_message(
            embed=discord.Embed(
                title="Invite",
                description=f"Wishing you to [join us](<{link}>).",
                color=config.msgColor
            ),
            ephemeral=True
        )
    
    @app_commands.guild_only()
    @app_commands.command(name='lookup', description='Find a study buddy.')
    async def lookup(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )


    @app_commands.guild_only()
    @app_commands.command(
        name="doubt", 
        description="Flag this as a doubt."
    )
    async def doubt(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"The command is still under construction."
            )
        )

async def setup(bot):
    Server_cog = Server(bot)
    await bot.add_cog(Server_cog)

    guild_ids = config.availableIn["guilds"]
    for guild_id in guild_ids:
        for command in Server_cog.__cog_app_commands__:
            print(f"Adding {command.name} in server with ID {guild_id}.")
            bot.tree.add_command(command, guild=discord.Object(id=guild_id))