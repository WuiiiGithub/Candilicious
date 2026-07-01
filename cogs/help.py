import discord, config, traceback
from discord import app_commands, ui
from discord.ext import commands
from library.logging import CogLogger, CommandLogger, ListenerLogger

filename = __name__.title()
cogLog = CogLogger(filename=filename)


class HelpSelect(ui.Select):
    def __init__(self, cogs_data: list, current: str):
        options = [
            discord.SelectOption(
                label="Home", description="Show all commands grouped by category",
                emoji="🏠", default=current == "Home"
            )
        ]
        for cog_name, cmds in cogs_data:
            options.append(
                discord.SelectOption(
                    label=cog_name, description=f"{len(cmds)} commands",
                    emoji="📁", default=cog_name == current
                )
            )
        super().__init__(placeholder="Navigate to a category...", options=options)
        self.cogs_data = cogs_data

    async def callback(self, interaction: discord.Interaction):
        embed = self.view.build_embed(self.values[0])
        await interaction.response.edit_message(
            embed=embed,
            view=HelpView(self.cogs_data, self.values[0])
        )


class HelpView(ui.View):
    def __init__(self, cogs_data: list, current: str = "Home"):
        super().__init__(timeout=120)
        self.cogs_data = cogs_data
        self.add_item(HelpSelect(cogs_data, current))

    def build_embed(self, target: str) -> discord.Embed:
        embed = discord.Embed(color=config.msgColor)
        if target == "Home":
            embed.title = "📚 Help Menu"
            for cog_name, cmds in self.cogs_data:
                if not cmds:
                    continue
                lines = "\n".join(f"`/{cmd.name}` — {cmd.description}" for cmd in cmds)
                embed.add_field(
                    name=f"📁 {cog_name} ({len(cmds)})",
                    value=lines,
                    inline=False
                )
        else:
            cmds = dict(self.cogs_data).get(target, [])
            embed.title = f"📁 {target} Commands"
            embed.description = f"{len(cmds)} command{'s' if len(cmds) != 1 else ''} available"
            for cmd in cmds:
                embed.add_field(
                    name=f"/{cmd.name}",
                    value=cmd.description or "No description",
                    inline=False
                )
        embed.set_footer(text="Use the dropdown below to navigate between categories")
        return embed

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Help Cog has been initialized.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Help cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.command(name="help", description="Shows all commands grouped by category.")
    async def help(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            bot = inter.client
            cogs_data = []
            for cog_name, cog in bot.cogs.items():
                if cog.qualified_name == "Help":
                    continue
                cmds = list(cog.get_app_commands())
                if cmds:
                    cogs_data.append((cog.qualified_name, cmds))

            view = HelpView(cogs_data)
            embed = view.build_embed("Home")
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
            cmdLog.process(status_code=100, name="Executed", details="Help menu displayed.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Help_cog = Help(bot)
    await bot.add_cog(Help_cog)
