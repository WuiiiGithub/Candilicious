import traceback
from discord.ext import commands
from library.logging import CogLogger, ListenerLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)

class Server(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Server Cog has been initialized and is ready for guild-specific management.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Server cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()



async def setup(bot):
    Server_cog = Server(bot)
    await bot.add_cog(Server_cog)
