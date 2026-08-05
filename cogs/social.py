import discord
import pymongo
import config
from discord import app_commands
from discord.ext import commands
import os, asyncio, traceback, re, urllib.request
from datetime import datetime, timezone
from library.logging import CogLogger, CommandLogger
from library import is_muted, db
from library.usersync import discord_user_doc

filename = __name__.title()
cogLog = CogLogger(filename=filename)

db = pymongo.MongoClient(os.getenv("MONGODB_URI"))[config.DB_NAME]

DEFAULT_BIO = "Hey! I'm a new user who just joined recently :)"


class FollowBackView(discord.ui.View):
    def __init__(self, target_id: str, follower_id: str, profile_url: str = None):
        super().__init__(timeout=3600)
        self.target_id = target_id
        self.follower_id = follower_id
        if profile_url:
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="View Profile",
                url=profile_url
            ))

    @discord.ui.button(label="\U0001f49a Follow Back", style=discord.ButtonStyle.green)
    async def follow_back_button(self, inter: discord.Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.target_id:
            return await inter.response.send_message("This isn't your notification.", ephemeral=True)

        target_user = db["users"].find_one({"_id": self.target_id})
        follower_user = db["users"].find_one({"_id": self.follower_id})
        if not target_user or not follower_user:
            return await inter.response.send_message("One of the accounts is missing.", ephemeral=True)

        if self.target_id in follower_user.get("followers", []):
            await inter.response.edit_message(content="You already follow them back!", view=None, embed=None)
            return

        db["users"].update_one({"_id": self.follower_id}, {"$push": {"followers": self.target_id}})
        db["users"].update_one({"_id": self.target_id}, {"$push": {"following": self.follower_id}})
        for item in self.children:
            item.disabled = True
        await inter.response.edit_message(
            embed=discord.Embed(
                title="Followed Back",
                description="You are now following them back!",
                color=discord.Color.green()
            ),
            view=self
        )


async def notify_followers_of_post(
    bot: commands.Bot,
    author_id: str,
    post_title: str,
    post_caption: str,
    post_link: str,
    thumbnail_url: str | None = None,
    post_url: str | None = None,
):
    try:
        author = db["users"].find_one({"_id": author_id})
        if not author:
            return
        follower_ids = author.get("followers", [])
        if not follower_ids:
            return

        author_member = bot.get_user(int(author_id))
        display_name = author_member.display_name if author_member else "Unknown"
        avatar_url = author_member.display_avatar.url if author_member else None

        for fid in follower_ids:
            try:
                if is_muted(fid):
                    continue
                follower_user = bot.get_user(int(fid))
                if not follower_user:
                    continue

                embed = discord.Embed(
                    title=post_title,
                    description=post_caption,
                    color=config.msgColor,
                    url=post_url or post_link,
                )
                if thumbnail_url:
                    embed.set_image(url=thumbnail_url)
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)
                embed.set_footer(text=f"Posted by {display_name}", icon_url=avatar_url)
                embed.timestamp = datetime.now(timezone.utc)

                view = discord.ui.View()
                if post_url:
                    view.add_item(discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        label="View Post",
                        url=post_url,
                    ))
                if post_link:
                    view.add_item(discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        label="Open Link",
                        url=post_link,
                    ))

                await follower_user.send(embed=embed, view=view)
            except discord.Forbidden:
                pass
            except Exception:
                pass
    except Exception:
        pass

def fetch_og_image(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        for prop in (r'og:image', r'twitter:image'):
            match = re.search(
                rf'<meta\s+[^>]*(?:property|name)=["\']{prop}["\'][^>]*content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    rf'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{prop}["\']',
                    html,
                    re.IGNORECASE,
                )
            if match:
                content = match.group(1)
                if content.startswith("//"):
                    content = "https:" + content
                elif content.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    content = f"{parsed.scheme}://{parsed.netloc}{content}"
                return content
        return None
    except Exception:
        return None

class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cogLog.log_cog(action="starting", status_code=0, details="Social Cog has been initialized and is ready for social interactions.")

    @app_commands.command(name="profile", description="View your or another user's profile")
    async def profile(self, inter: discord.Interaction, user: discord.User = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            target = user or inter.user

            cmdLog.process(status_code=50, name="Data Fetch", details=f"Fetching profile for user {target.id}...")
            db["users"].update_one(
                {"_id": str(target.id)},
                {"$set": discord_user_doc(target)},
                upsert=True,
            )
            user_data = db["users"].find_one({"_id": str(target.id)})

            if inter.user.id != target.id:
                db["users"].update_one(
                    {"_id": str(target.id)},
                    {"$inc": {"profile_views": 1}},
                )
                user_data = db["users"].find_one({"_id": str(target.id)})

            display_name = target.display_name
            username = target.name
            avatar_url = target.display_avatar.url

            bio = DEFAULT_BIO
            followers_count = 0
            following_count = 0
            views = 0
            if user_data:
                if user_data.get("bio"):
                    bio = user_data["bio"]
                followers_count = len(user_data.get("followers", []))
                following_count = len(user_data.get("following", []))
                views = user_data.get("profile_views", 0)

            feed_count = db["social.posts"].count_documents({"user_id": str(target.id)})

            embed = discord.Embed(
                title=f"{display_name}",
                color=config.msgColor
            )
            embed.set_thumbnail(url=avatar_url)
            embed.add_field(name="Username", value=f"`@{username}`", inline=False)
            embed.add_field(name="Followers", value=str(followers_count), inline=True)
            embed.add_field(name="Following", value=str(following_count), inline=True)
            embed.add_field(name="Views", value=str(views), inline=True)
            embed.add_field(name="Feed", value=str(feed_count), inline=True)
            embed.add_field(name="Bio", value=bio, inline=False)

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Open Profile",
                url=f"{config.FRONTEND_DOMAIN}/profile?user_id={target.id}"
            ))

            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Profile Sent", details=f"Profile for {target.id} sent successfully.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="follow", description="Follow or unfollow a user")
    @app_commands.describe(user="The user to follow/unfollow")
    async def follow(self, inter: discord.Interaction, user: discord.User):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            current_id = str(inter.user.id)
            target_id = str(user.id)

            if current_id == target_id:
                embed = discord.Embed(
                    title="Error",
                    description="You cannot follow yourself.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            target_user = db["users"].find_one({"_id": target_id})
            if not target_user:
                embed = discord.Embed(
                    title="Error",
                    description="That user hasn't registered on the site yet.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            followers = target_user.get("followers", [])
            if current_id in followers:
                embed = discord.Embed(
                    title="Error",
                    description=f"You are already following {user.mention}.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            db["users"].update_one({"_id": target_id}, {"$push": {"followers": current_id}})
            db["users"].update_one({"_id": current_id}, {"$push": {"following": target_id}})
            resp = discord.Embed(
                title="Followed",
                description=f"You are now following {user.mention}.",
                color=config.msgColor
            )
            resp.set_footer(text="Followed")
            resp.timestamp = datetime.now(timezone.utc)
            await inter.response.send_message(embed=resp)

            try:
                if not is_muted(target_id):
                    notify = discord.Embed(
                        title="New Follower",
                        description=f"{inter.user.mention} followed you!",
                        color=config.msgColor
                    )
                    notify.set_thumbnail(url=inter.user.display_avatar.url)
                    notify.timestamp = datetime.now(timezone.utc)
                    await user.send(
                        embed=notify,
                        view=FollowBackView(target_id, current_id, f"{config.FRONTEND_DOMAIN}/profile?user_id={current_id}")
                    )
            except Exception:
                pass

            cmdLog.process(status_code=100, name="Follow", details=f"{current_id} followed {target_id}")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="unfollow", description="Unfollow a user")
    @app_commands.describe(user="The user to unfollow")
    async def unfollow(self, inter: discord.Interaction, user: discord.User):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            current_id = str(inter.user.id)
            target_id = str(user.id)

            if current_id == target_id:
                embed = discord.Embed(
                    title="Error",
                    description="You cannot unfollow yourself.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            target_user = db["users"].find_one({"_id": target_id})
            if not target_user:
                embed = discord.Embed(
                    title="Error",
                    description="That user hasn't registered on the site yet.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            followers = target_user.get("followers", [])
            if current_id not in followers:
                embed = discord.Embed(
                    title="Error",
                    description=f"You are not following {user.mention}.",
                    color=discord.Color.red()
                )
                await inter.response.send_message(embed=embed, ephemeral=True)
                return

            db["users"].update_one({"_id": target_id}, {"$pull": {"followers": current_id}})
            db["users"].update_one({"_id": current_id}, {"$pull": {"following": target_id}})
            resp = discord.Embed(
                title="Unfollowed",
                description=f"You have unfollowed {user.mention}.",
                color=config.msgColor
            )
            resp.set_footer(text="Unfollowed")
            resp.timestamp = datetime.now(timezone.utc)
            await inter.response.send_message(embed=resp)
            cmdLog.process(status_code=100, name="Unfollow", details=f"{current_id} unfollowed {target_id}")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="followers", description="View someone's followers list")
    @app_commands.describe(user="The user to check followers of (defaults to you)")
    async def followers(self, inter: discord.Interaction, user: discord.User = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            target = user or inter.user
            target_id = str(target.id)
            user_data = db["users"].find_one({"_id": target_id})
            if not user_data:
                await inter.response.send_message("User not found.", ephemeral=True)
                return

            all_followers = user_data.get("followers", [])
            total = len(all_followers)
            page_size = 10
            total_pages = max(1, (total + page_size - 1) // page_size)

            class FollowersView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.page = 1

                def get_page_data(self):
                    start = (self.page - 1) * page_size
                    ids = all_followers[start:start + page_size]

                    lines = []
                    for uid in ids:
                        u = db["users"].find_one({"_id": uid})
                        name = (u or {}).get("display_name") or (u or {}).get("name") or "Unknown"
                        lines.append(f"• <@{uid}> — {name}")
                    return "\n".join(lines) if lines else "No followers yet."

                def build_embed(self):
                    embed = discord.Embed(
                        title=f"{target.display_name}'s Followers",
                        description=self.get_page_data(),
                        color=config.msgColor
                    )
                    embed.set_footer(text=f"Page {self.page}/{total_pages} • {total} total")
                    return embed

                @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=True)
                async def prev_btn(self, button_inter: discord.Interaction, button: discord.ui.Button):
                    self.page -= 1
                    if self.page <= 1:
                        button.disabled = True
                    for child in self.children:
                        if child.label == "Next ▶":
                            child.disabled = False
                    await button_inter.response.edit_message(embed=self.build_embed(), view=self)

                @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
                async def next_btn(self, button_inter: discord.Interaction, button: discord.ui.Button):
                    self.page += 1
                    if self.page >= total_pages:
                        button.disabled = True
                    for child in self.children:
                        if child.label == "◀ Previous":
                            child.disabled = False
                    await button_inter.response.edit_message(embed=self.build_embed(), view=self)

            view = FollowersView()
            if total_pages <= 1:
                view.next_btn.disabled = True

            await inter.response.send_message(embed=view.build_embed(), view=view)
            cmdLog.process(status_code=100, name="Followers", details=f"Followers for {target_id} ({total} total)")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="following", description="View who someone is following")
    @app_commands.describe(user="The user to check following of (defaults to you)")
    async def following(self, inter: discord.Interaction, user: discord.User = None):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            target = user or inter.user
            target_id = str(target.id)
            user_data = db["users"].find_one({"_id": target_id})
            if not user_data:
                await inter.response.send_message("User not found.", ephemeral=True)
                return

            all_following = user_data.get("following", [])
            total = len(all_following)
            page_size = 10
            total_pages = max(1, (total + page_size - 1) // page_size)

            class FollowingView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.page = 1

                def get_page_data(self):
                    start = (self.page - 1) * page_size
                    ids = all_following[start:start + page_size]

                    lines = []
                    for uid in ids:
                        u = db["users"].find_one({"_id": uid})
                        name = (u or {}).get("display_name") or (u or {}).get("name") or "Unknown"
                        lines.append(f"• <@{uid}> — {name}")
                    return "\n".join(lines) if lines else "Not following anyone yet."

                def build_embed(self):
                    embed = discord.Embed(
                        title=f"{target.display_name} is Following",
                        description=self.get_page_data(),
                        color=config.msgColor
                    )
                    embed.set_footer(text=f"Page {self.page}/{total_pages} • {total} total")
                    return embed

                @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=True)
                async def prev_btn(self, button_inter: discord.Interaction, button: discord.ui.Button):
                    self.page -= 1
                    if self.page <= 1:
                        button.disabled = True
                    for child in self.children:
                        if child.label == "Next ▶":
                            child.disabled = False
                    await button_inter.response.edit_message(embed=self.build_embed(), view=self)

                @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
                async def next_btn(self, button_inter: discord.Interaction, button: discord.ui.Button):
                    self.page += 1
                    if self.page >= total_pages:
                        button.disabled = True
                    for child in self.children:
                        if child.label == "◀ Previous":
                            child.disabled = False
                    await button_inter.response.edit_message(embed=self.build_embed(), view=self)

            view = FollowingView()
            if total_pages <= 1:
                view.next_btn.disabled = True

            await inter.response.send_message(embed=view.build_embed(), view=view)
            cmdLog.process(status_code=100, name="Following", details=f"Following for {target_id} ({total} total)")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    @app_commands.command(name="post", description="Create a new social post with a link preview")
    @app_commands.describe(
        title="The title of your post",
        caption="The caption or description",
        link="The URL link to preview",
        thumbnail="Optional image or GIF to use as thumbnail (overrides auto-preview)"
    )
    async def post(
        self,
        inter: discord.Interaction,
        title: str,
        caption: str,
        link: str,
        thumbnail: discord.Attachment = None,
    ):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Validating", details="Validating post inputs...")

            if len(title) > 200:
                await inter.response.send_message("Title must be 200 characters or fewer.", ephemeral=True)
                return
            if len(caption) > 2000:
                await inter.response.send_message("Caption must be 2000 characters or fewer.", ephemeral=True)
                return
            if not link.startswith(("http://", "https://")):
                await inter.response.send_message("Link must be a valid URL (http/https).", ephemeral=True)
                return

            await inter.response.defer()

            thumbnail_url = None
            if thumbnail:
                thumbnail_url = thumbnail.url
            else:
                thumbnail_url = await asyncio.to_thread(fetch_og_image, link)

            post = {
                "user_id": str(inter.user.id),
                "title": title,
                "caption": caption,
                "link": link,
                "thumbnail_url": thumbnail_url,
                "likes": [],
                "like_count": 0,
                "views": 0,
                "created_at": datetime.now(timezone.utc),
            }
            result = db["social.posts"].insert_one(post)
            post_id = str(result.inserted_id)

            embed = discord.Embed(
                title=title,
                description=caption,
                color=config.msgColor,
                url=link,
            )
            if thumbnail_url:
                embed.set_image(url=thumbnail_url)
            embed.set_footer(text=f"Posted by {inter.user.display_name}", icon_url=inter.user.display_avatar.url)
            embed.timestamp = datetime.now(timezone.utc)

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="View Post",
                url=f"{config.FRONTEND_DOMAIN}/social/post/{post_id}"
            ))
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Open Link",
                url=link
            ))

            await inter.followup.send(embed=embed, view=view)

            await notify_followers_of_post(
                bot=self.bot,
                author_id=str(inter.user.id),
                post_title=title,
                post_caption=caption,
                post_link=link,
                thumbnail_url=thumbnail_url,
                post_url=f"{config.FRONTEND_DOMAIN}/social/post/{post_id}",
            )

            cmdLog.process(status_code=100, name="Post Created", details=f"Post {post_id} created by {inter.user.id}.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

async def setup(bot):
    Social_cog = Social(bot)
    await bot.add_cog(Social_cog)
