from discord.ext import commands
from library.logging import CogLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

class Server(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Server Cog has been initialized and is ready for guild-specific management.")



async def setup(bot):
    Server_cog = Server(bot)
    await bot.add_cog(Server_cog)
