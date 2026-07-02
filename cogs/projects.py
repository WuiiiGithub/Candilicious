import discord, config, pymongo, os, traceback
from discord import app_commands, ui
from discord.ext import commands
from library.logging import CogLogger, CommandLogger, ListenerLogger
from datetime import datetime

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(host=os.getenv("MONGODB_URI"))[config.DB_NAME]

ITEMS_PER_PAGE = 5
TASKS_PER_PAGE = 10


class ProjectSelect(ui.Select):
    def __init__(self, projects: list, page: int):
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_projects = projects[start:end]
        opts = [
            discord.SelectOption(
                label=p["title"][:100],
                description=p.get("description", "")[:100] or "No description",
                value=p["project_id"]
            )
            for p in page_projects
        ]
        super().__init__(placeholder="Select a project...", options=opts, row=1)
        self.projects = projects
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        await self.view.on_project_selected(self.values[0], interaction)


class NavButton(ui.Button):
    def __init__(self, direction: str, disabled: bool = False):
        emoji = "◀️" if direction == "prev" else "▶️"
        super().__init__(emoji=emoji, style=discord.ButtonStyle.grey, disabled=disabled, row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.on_nav(self, interaction)


class BackButton(ui.Button):
    def __init__(self):
        super().__init__(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        await self.view.on_back(interaction)


class EditButton(ui.Button):
    def __init__(self):
        frontend = getattr(config, "FRONTEND_DOMAIN", "") or ""
        url = f"{frontend}/projects" if frontend else ""
        super().__init__(label="Open in Web", emoji="✏️", style=discord.ButtonStyle.link, url=url, row=2)


class BoardSelect(ui.Select):
    def __init__(self, boards: list, page: int):
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_boards = boards[start:end]
        opts = [
            discord.SelectOption(
                label=b["title"][:100],
                description=b.get("description", "")[:100] or "No description",
                value=b["board_id"]
            )
            for b in page_boards
        ]
        super().__init__(placeholder="Select a board...", options=opts, row=1)
        self.boards = boards
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        await self.view.on_board_selected(self.values[0], interaction)


class StatusSelect(ui.Select):
    def __init__(self, current: str = "all"):
        statuses = [
            ("all", "All", "Show all tasks"),
            ("todo", "Todo", "Tasks not started"),
            ("cooking", "Cooking", "Tasks in progress"),
            ("done", "Done", "Completed tasks"),
        ]
        opts = [
            discord.SelectOption(
                label=label, description=desc, value=val,
                emoji={"all": "📋", "todo": "📝", "cooking": "👨‍🍳", "done": "✅"}.get(val),
                default=val == current
            )
            for val, label, desc in statuses
        ]
        super().__init__(placeholder="Filter by status...", options=opts, row=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.on_status_changed(self.values[0], interaction)


class ProjectsHomeView(ui.View):
    def __init__(self, user_id: str, projects: list, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.projects = projects
        self.page = page
        self.total_pages = max(1, (len(projects) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        self.add_item(NavButton("prev", disabled=page == 0))
        self.add_item(NavButton("next", disabled=page >= self.total_pages - 1 or len(projects) == 0))
        if projects:
            self.add_item(ProjectSelect(projects, page))
        self.add_item(EditButton())

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(color=config.msgColor)
        if not self.projects:
            embed.title = "📁 Projects"
            embed.description = "No projects found. Create one on the web app!"
            return embed

        embed.title = f"📁 Projects (Page {self.page + 1}/{self.total_pages})"
        start = self.page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        for i, p in enumerate(self.projects[start:end], start=start + 1):
            boards = p.get("boards", {})
            stats = f"📝 Todo: {boards.get('todo', 0)} | 👨‍🍳 Cooking: {boards.get('cooking', 0)} | ✅ Done: {boards.get('done', 0)}"
            embed.add_field(
                name=f"{i}. {p['title']}",
                value=f"{p.get('description', '')[:200]}\n{stats}",
                inline=False
            )
        embed.set_footer(text="Select a project from the dropdown below")
        return embed

    async def on_project_selected(self, project_id: str, interaction: discord.Interaction):
        project = next((p for p in self.projects if p["project_id"] == project_id), None)
        if not project:
            await interaction.response.send_message("Project not found.", ephemeral=True)
            return
        boards = list(db["boards.docs"].find({"project_id": project_id, "user_id": self.user_id}))
        view = BoardsView(self.user_id, project, boards)
        embed = view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_nav(self, button: ui.Button, interaction: discord.Interaction):
        if button.emoji.name == "◀️":
            self.page -= 1
        else:
            self.page += 1
        view = ProjectsHomeView(self.user_id, self.projects, self.page)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class BoardsView(ui.View):
    def __init__(self, user_id: str, project: dict, boards: list, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.project = project
        self.boards = boards
        self.page = page
        self.total_pages = max(1, (len(boards) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        self.add_item(NavButton("prev", disabled=page == 0))
        self.add_item(NavButton("next", disabled=page >= self.total_pages - 1 or len(boards) == 0))
        if boards:
            self.add_item(BoardSelect(boards, page))
        self.add_item(BackButton())
        self.add_item(EditButton())

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(color=config.msgColor)
        embed.title = f"📋 {self.project['title']} — Boards"
        if self.boards:
            embed.description = f"Page {self.page + 1}/{self.total_pages}"
            start = self.page * ITEMS_PER_PAGE
            end = start + ITEMS_PER_PAGE
            for i, b in enumerate(self.boards[start:end], start=start + 1):
                raw_tasks = b.get("tasks", {})
                if isinstance(raw_tasks, dict):
                    task_list = list(raw_tasks.values())
                elif isinstance(raw_tasks, list):
                    task_list = raw_tasks
                else:
                    task_list = []
                total = len(task_list)
                todo = sum(1 for t in task_list if t.get("status") == "todo")
                cooking = sum(1 for t in task_list if t.get("status") == "cooking")
                done = sum(1 for t in task_list if t.get("status") == "done")
                desc = b.get("description", "") or "No description"
                embed.add_field(
                    name=f"{i}. {b['title']}",
                    value=f"{desc[:200]}\n📝 Todo: {todo} | 👨‍🍳 Cooking: {cooking} | ✅ Done: {done} | **{total} total**",
                    inline=False
                )
                thumb = b.get("thumbnail_link") or ""
                if thumb:
                    embed.set_author(name=b["title"], icon_url=thumb)
        else:
            embed.description = "No boards in this project yet."
        embed.set_footer(text="Select a board from the dropdown below")
        return embed

    async def on_board_selected(self, board_id: str, interaction: discord.Interaction):
        board = next((b for b in self.boards if b["board_id"] == board_id), None)
        if not board:
            await interaction.response.send_message("Board not found.", ephemeral=True)
            return
        view = TasksView(self.user_id, self.project, board)
        embed = view.build_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_nav(self, button: ui.Button, interaction: discord.Interaction):
        if button.emoji.name == "◀️":
            self.page -= 1
        else:
            self.page += 1
        view = BoardsView(self.user_id, self.project, self.boards, self.page)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    async def on_back(self, interaction: discord.Interaction):
        projects = list(db["projects.docs"].find({"user_id": self.user_id}))
        view = ProjectsHomeView(self.user_id, projects)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class TasksView(ui.View):
    def __init__(self, user_id: str, project: dict, board: dict, status: str = "all", page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.project = project
        self.board = board
        self.status = status
        self.page = page

        raw_tasks = board.get("tasks", {})
        if isinstance(raw_tasks, dict):
            all_tasks = list(raw_tasks.values())
        elif isinstance(raw_tasks, list):
            all_tasks = raw_tasks
        else:
            all_tasks = []

        if status != "all":
            all_tasks = [t for t in all_tasks if t.get("status") == status]

        self.tasks = all_tasks
        self.total_pages = max(1, (len(self.tasks) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)

        self.add_item(NavButton("prev", disabled=page == 0))
        self.add_item(NavButton("next", disabled=page >= self.total_pages - 1 or len(self.tasks) == 0))
        self.add_item(StatusSelect(status))
        self.add_item(BackButton())
        self.add_item(EditButton())

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(color=config.msgColor)
        status_label = {"all": "All", "todo": "Todo", "cooking": "Cooking", "done": "Done"}.get(self.status, "All")
        embed.title = f"✅ {self.board['title']} — {status_label}"

        thumb = self.board.get("thumbnail_link") or ""
        if thumb:
            embed.set_author(name=self.board["title"], icon_url=thumb)

        desc = self.board.get("description", "") or ""
        if desc:
            embed.description = desc[:250]

        if not self.tasks:
            embed.add_field(name="No tasks", value="No tasks match this filter.", inline=False)
        else:
            embed.description = (embed.description + "\n" if embed.description else "") + f"Page {self.page + 1}/{self.total_pages}"
            start = self.page * TASKS_PER_PAGE
            end = start + TASKS_PER_PAGE
            for i, t in enumerate(self.tasks[start:end], start=start + 1):
                text = t.get("text", "Untitled")[:200]
                priority = t.get("priority", "normal")
                p_emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢", "normal": "⚪"}.get(priority, "⚪")
                s_emoji = {"todo": "📝", "cooking": "👨‍🍳", "done": "✅"}.get(t.get("status", "todo"), "📝")
                embed.add_field(
                    name=f"{s_emoji} {i}. {text}",
                    value=f"Priority: {p_emoji} | Status: **{t.get('status', 'todo').title()}**",
                    inline=False
                )

        embed.set_footer(text="Use the dropdown to filter by status")
        return embed

    async def on_status_changed(self, status: str, interaction: discord.Interaction):
        view = TasksView(self.user_id, self.project, self.board, status)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    async def on_nav(self, button: ui.Button, interaction: discord.Interaction):
        if button.emoji.name == "◀️":
            self.page -= 1
        else:
            self.page += 1
        view = TasksView(self.user_id, self.project, self.board, self.status, self.page)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    async def on_back(self, interaction: discord.Interaction):
        boards = list(db["boards.docs"].find({"project_id": self.project["project_id"], "user_id": self.user_id}))
        view = BoardsView(self.user_id, self.project, boards)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class Projects(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Projects Cog has been initialized.")

    @commands.Cog.listener()
    async def on_ready(self):
        log = ListenerLogger(filename=filename, event_name="on_ready")
        try:
            log.process(status_code=0, message="Tree Sync", details="Trying to sync the application command tree...")
            await self.bot.tree.sync()
            log.complete(status_code=100, message="Sync Success", details="Bot Tree has been successfully synced for the Projects cog.")
        except Exception:
            log.error(status_code=-100, message="Sync Fail", details=traceback.format_exc())
        finally:
            log.send()

    @app_commands.command(name="projects", description="Browse and manage your projects and boards.")
    async def projects(self, inter: discord.Interaction):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            user_id = str(inter.user.id)
            projects = list(db["projects.docs"].find({"user_id": user_id}))

            view = ProjectsHomeView(user_id, projects)
            embed = view.build_embed()
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
            cmdLog.process(status_code=100, name="Executed", details=f"Projects menu displayed for user {user_id}.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()


async def setup(bot):
    Projects_cog = Projects(bot)
    await bot.add_cog(Projects_cog)
