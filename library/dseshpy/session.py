import asyncio
import hashlib
import secrets
import os
import logging
from datetime import datetime, timezone, timedelta
from . import collections
from . import checks
from discord import VoiceState, Member
import discord
import random
import config

logger = logging.getLogger(__name__)

import pymongo
from library import is_muted
session_collection = lambda: collections.get('session')


def generate_session_id(channel_id: str = "") -> str:
    """Generate a cryptographically random 16-char hex session ID."""
    return secrets.token_hex(8)

def _get_activity_type(state: VoiceState) -> str:
    if state.self_video and state.self_stream:
        return "cam+ss"
    elif state.self_video:
        return "cam"
    elif state.self_stream:
        return "ss"
    return "noact"

def _load_drop_config():
    """Read drop config directly from DB so changes take effect immediately."""
    cfg_col = collections.get("config")
    if cfg_col is None:
        return
    doc = cfg_col.find_one({"_id": "variables"})
    if not doc:
        return
    drops = doc.get("drops", {})
    resources = doc.get("resources", {})
    activity_tiers = doc.get("activity_tiers", [])
    premium = doc.get("premium", {})
    if drops:
        if "mean_time" in drops:
            config.DROP_MEAN_TIME = float(drops["mean_time"])
        if "variance" in drops:
            config.DROP_VARIANCE = float(drops["variance"])
        if "collection_time" in drops:
            config.DROP_COLLECTION_TIME = float(drops["collection_time"])
    wood = resources.get("wood", {})
    if wood:
        for k, attr in [("base_mean", "RESOURCE_WOOD_BASE_MEAN"), ("base_decay", "RESOURCE_WOOD_BASE_DECAY"),
                         ("decay_rate", "RESOURCE_WOOD_DECAY_RATE"), ("std_dev", "RESOURCE_WOOD_STD_DEV"),
                         ("min", "RESOURCE_WOOD_MIN")]:
            if k in wood:
                setattr(config, attr, float(wood[k]))
    iron = resources.get("iron", {})
    if iron:
        for k, attr in [("base_mean", "RESOURCE_IRON_BASE_MEAN"), ("base_decay", "RESOURCE_IRON_BASE_DECAY"),
                         ("decay_rate", "RESOURCE_IRON_DECAY_RATE"), ("std_dev", "RESOURCE_IRON_STD_DEV"),
                         ("min", "RESOURCE_IRON_MIN")]:
            if k in iron:
                setattr(config, attr, float(iron[k]))
    if "variance_factor_rate" in resources:
        config.RESOURCE_VARIANCE_FACTOR_RATE = float(resources["variance_factor_rate"])
    if "variance_factor_min" in resources:
        config.RESOURCE_VARIANCE_FACTOR_MIN = float(resources["variance_factor_min"])
    if isinstance(activity_tiers, list) and len(activity_tiers) == 4:
        config.ACTIVITY_TIERS = [tuple(t) for t in activity_tiers]
    if premium:
        if "cost" in premium:
            config.PREMIUM_COST = float(premium["cost"])
        if "ttl_days" in premium:
            config.PREMIUM_TTL_DAYS = float(premium["ttl_days"])
        if "unit" in premium:
            config.PREMIUM_UNIT = premium["unit"]
    level_up = doc.get("level_up", {})
    if level_up:
        if "xp_per_minute" in level_up:
            config.LEVEL_UP_XP_PER_MINUTE = int(level_up["xp_per_minute"])
        if "xp_threshold" in level_up:
            config.LEVEL_UP_XP_THRESHOLD = int(level_up["xp_threshold"])
        if "wood_base" in level_up:
            config.LEVEL_UP_WOOD_BASE = int(level_up["wood_base"])

class Session:
    """
    A session refers to a study session in discord vc
    """
    def __init__(
        self,
        guild_id: str, 
        channel_id: str,
        owner_id: str = None,
        members: dict = None,
        active_count: int = 0,
        members_limit: int = None,
        members_count: dict = None,
        vc_level: int = 1,
        vc_xp: int = 0,
        rent_type: str = "free",
        rent_amount: int = 0,

        # routines
        routine_callback_mean_time: int = 30,
        routine_drop_amount: int = 10,
        routines_fired_count: int=0,

        # session type: "cam", "ss", "cam+ss", "cam&ss", "cam+noact", "ss+noact", "*"
        session_type: str = "*",
        session_id: str = None,

        # level up
        started_at: str = None,
        last_level_up_at: str = None,
        pending_level_up: dict = None,
        level_up_message_id: str = None,

        **kwargs
    ):
        self.session_id = session_id or generate_session_id(channel_id)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        
        self.members_count = members_count or {
            "total": 0,
            "noact": 0,
            "ss": 0,
            "cam": 0
        }
        self.members_limit = members_limit
        self.vc_level = vc_level
        self.vc_xp = vc_xp
        self.rent_type = rent_type
        self.rent_amount = rent_amount
        self.session_type = session_type
        
        self.members = members or {}
        
        self.routine_callback_mean_time = routine_callback_mean_time
        self.routines_fired_count = routines_fired_count
        
        self.monitor_tasks = {}
        self.drop_task = None
        self.event_bus = None

        self.started_at = started_at
        self.last_level_up_at = last_level_up_at
        self.pending_level_up = pending_level_up
        self.level_up_message_id = level_up_message_id
        
    def to_dict(self):
        """Convert session state to dictionary for MongoDB."""
        d = {
            "session_id": self.session_id,
            "owner_id": self.owner_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "members": self.members,
            "members_limit": self.members_limit,
            "members_count": self.members_count,
            "vc_level": self.vc_level,
            "vc_xp": self.vc_xp,
            "rent_type": self.rent_type,
            "rent_amount": self.rent_amount,
            "routine_callback_mean_time": self.routine_callback_mean_time,
            "routines_fired_count": self.routines_fired_count,
            "session_type": self.session_type,
            "started_at": self.started_at,
            "last_level_up_at": self.last_level_up_at,
            "pending_level_up": self.pending_level_up,
            "level_up_message_id": self.level_up_message_id,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Session from MongoDB document."""
        data.pop("_id", None)
        if "session_id" not in data:
            data["session_id"] = data.get("channel_id")
        return cls(**data)

    async def activity_monitor(self, member: Member, exceptions_handler=None, session_category_id=None, ignore_channel_id=None):
        """Wait 5 minutes and disconnect user if they don't comply with session type or activity requirements."""
        await asyncio.sleep(300)
        
        if member.voice and checks.get_session_status(member.voice, session_category_id, ignore_channel_id) and str(member.voice.channel.id) == self.channel_id:
            after_type = _get_activity_type(member.voice)
            if not self._is_allowed(after_type):
                try:
                    who = member.display_name if is_muted(str(member.id)) else member.mention
                    embed = discord.Embed(
                        description=f"{who} You do not meet the session type requirements ({self._type_description()}). \U0001f6a8",
                        color=0x3498DB,
                    )
                    await member.voice.channel.send(embed=embed, delete_after=20)
                    await member.move_to(None)
                except:
                    pass


    def _sync_session_now(self):
        col = session_collection()
        if col is not None:
            col.update_one(
                {"session_id": self.session_id},
                {"$set": self.to_dict()},
                upsert=True
            )

    async def _emit_event(self, event_type, data):
        """Publish an event to the frontend via the event bus."""
        if self.event_bus:
            try:
                await self.event_bus.publish(self.session_id, event_type, data)
            except Exception:
                pass

    def _get_effective_xp(self) -> int:
        """Compute effective XP since last level-up (or session start)."""
        if not self.started_at:
            return 0
        started = datetime.fromisoformat(self.started_at) if isinstance(self.started_at, str) else self.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        ref_time = started
        if self.last_level_up_at:
            lu = datetime.fromisoformat(self.last_level_up_at) if isinstance(self.last_level_up_at, str) else self.last_level_up_at
            if lu.tzinfo is None:
                lu = lu.replace(tzinfo=timezone.utc)
            ref_time = lu
        elapsed_min = (datetime.now(timezone.utc) - ref_time).total_seconds() / 60.0
        return int(elapsed_min * config.LEVEL_UP_XP_PER_MINUTE)

    async def _check_level_up(self, channel=None):
        """Check if XP threshold is crossed and trigger level-up if so."""
        if self.pending_level_up:
            return
        if not self.started_at:
            return

        effective_xp = self._get_effective_xp()

        if effective_xp < config.LEVEL_UP_XP_THRESHOLD:
            return

        new_level = self.vc_level + 1
        wood_cost = config.LEVEL_UP_WOOD_BASE * new_level

        self.pending_level_up = {
            "new_level": new_level,
            "wood_cost": wood_cost,
            "paid_by": [],
            "total_members": len(self.members),
        }
        self._sync_session_now()

        await self._emit_event("level_up", {
            "new_level": new_level,
            "wood_cost": wood_cost,
            "total_members": len(self.members),
        })

        if self.guild_id != "web" and channel:
            domain = os.getenv("FRONTEND_DOMAIN", "")
            if domain and not domain.endswith("/"):
                domain += "/"
            link = f"{domain}projects?level_up={self.session_id}"
            embed = discord.Embed(
                title="\u2b06\ufe0f Level Up Available!",
                description=f"Level **{self.vc_level}** \u2192 **{new_level}**\nCost: **{wood_cost}** \U0001fab5 Wood per member\n\n0/{len(self.members)} paid",
                color=discord.Color.green(),
            )
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label=f"Pay {wood_cost} Wood",
                style=discord.ButtonStyle.link,
                url=link,
                emoji="\U0001fab5",
            ))
            try:
                msg = await channel.send(embed=embed, view=view)
                self.level_up_message_id = str(msg.id)
                self._sync_session_now()
            except (discord.NotFound, discord.HTTPException):
                pass

    async def drop_routine(self, channel: discord.VoiceChannel):
        logger.info("Drop routine started")
        try:
            while True:
                try:
                    _load_drop_config()
                    v = config.DROP_VARIANCE
                    mean = config.DROP_MEAN_TIME
                    d_col = collections.get("drop.offers")

                    await self._check_level_up(channel)

                    interval = random.uniform(1 - v, 1 + v) * mean
                    sleep_sec = interval * 60
                    await asyncio.sleep(sleep_sec)

                    if self.guild_id == "web":
                        if not self.members:
                            continue
                    else:
                        if not channel.members:
                            continue

                    token = secrets.token_urlsafe(32)
                    d_col = collections.get("drop.offers")
                    if d_col is not None:
                        d_col.insert_one({
                            "token": token,
                            "guild_id": self.guild_id,
                            "channel_id": self.channel_id,
                            "session_id": self.session_id,
                            "drop_number": self.routines_fired_count + 1,
                            "created_at": datetime.now(timezone.utc),
                            "expire_at": datetime.now(timezone.utc) + timedelta(seconds=config.DROP_COLLECTION_TIME + 5),
                        })
                    else:
                        logger.error("drop.offers collection not found")

                    domain = os.getenv("FRONTEND_DOMAIN", "")
                    if domain and not domain.endswith("/"):
                        domain += "/"
                    link = f"{domain}projects"

                    self.routines_fired_count += 1
                    self._sync_session_now()

                    await self._emit_event("drop_created", {
                        "token": token,
                        "drop_number": self.routines_fired_count,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "expire_at": (datetime.now(timezone.utc) + timedelta(seconds=config.DROP_COLLECTION_TIME)).isoformat(),
                    })

                    if self.guild_id != "web" and channel:
                        embed = discord.Embed(
                            title="\U0001f381 Drops Have Landed!",
                            description="Someone dropped goodies in the study VC!\nOpen the site to claim yours before they vanish!",
                            color=discord.Color.gold()
                        )
                        embed.set_footer(text="*Hurry \u2014 everyone can claim once!*")
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(
                            label="Claim Drop",
                            style=discord.ButtonStyle.link,
                            url=link,
                            emoji="\U0001f381",
                        ))
                        try:
                            await channel.send(embed=embed, view=view, delete_after=config.DROP_COLLECTION_TIME)
                        except (discord.NotFound, discord.HTTPException):
                            pass

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("Drop routine error")

        except asyncio.CancelledError:
            pass

    def update_settings(self, **kwargs):
        """Dynamically update session details like rent, vc_level, etc., ensuring DB sync."""
        updated = False
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                updated = True
        return updated

    def _seg_elapsed(self, member_id: str) -> float:
        seg = self.members.get(member_id, {}).get("_seg")
        if not seg:
            return 0.0
        seg_time = datetime.fromisoformat(seg) if isinstance(seg, str) else seg
        secs = (datetime.now() - seg_time).total_seconds()
        return max(0.0, secs)

    def _reset_seg(self, member_id: str):
        self.members[member_id]["_seg"] = datetime.now().isoformat()

    def _is_allowed(self, activity_type: str) -> bool:
        if self.session_type == "*":
            return True
        st = self.session_type
        if st == "cam":
            return activity_type in ("cam", "cam+ss")
        if st == "ss":
            return activity_type in ("ss", "cam+ss")
        if st == "cam+ss":
            return activity_type in ("cam", "ss", "cam+ss")
        if st == "cam&ss":
            return activity_type == "cam+ss"
        if st == "cam+noact":
            return activity_type in ("cam", "cam+ss", "noact")
        if st == "ss+noact":
            return activity_type in ("ss", "cam+ss", "noact")
        return True

    def _type_description(self) -> str:
        descriptions = {
            "cam": "camera on",
            "ss": "screen sharing",
            "cam+ss": "camera or screen share",
            "cam&ss": "both camera and screen share",
            "cam+noact": "camera on or no activity",
            "ss+noact": "screen sharing or no activity",
        }
        return descriptions.get(self.session_type, "any activity type")

    def _accrue_time(self, member_id: str, activity_type: str, seconds: float):
        if member_id not in self.members:
            return
        net = self.members[member_id].setdefault("net_time", {"cam": 0, "ss": 0, "noact": 0, "total": 0})
        net["total"] = net.get("total", 0) + seconds
        if activity_type == "cam+ss":
            net["cam"] = net.get("cam", 0) + seconds
            net["ss"] = net.get("ss", 0) + seconds
        elif activity_type in ("cam", "ss", "noact"):
            net[activity_type] = net.get(activity_type, 0) + seconds

        log_id = self.members[member_id].get("log_id")
        if log_id:
            act_col = collections.get("session.logs")
            if act_col is not None:
                inc = {"joined_at.total": seconds}
                if activity_type == "cam+ss":
                    inc["joined_at.cam"] = seconds
                    inc["joined_at.ss"] = seconds
                elif activity_type in ("cam", "ss", "noact"):
                    inc[f"joined_at.{activity_type}"] = seconds
                act_col.update_one(
                    {"_id": log_id},
                    {"$inc": inc}
                )

    def _close_sub_session(self, member_id: str, activity_type: str):
        if member_id not in self.members:
            return

        secs = self._seg_elapsed(member_id)
        if secs > 0:
            self._accrue_time(member_id, activity_type, secs)

        u_col = collections.get('user')
        if u_col is not None and secs > 0:
            u_col.update_one(
                {"_id": member_id},
                {"$inc": {f"servers.{self.guild_id}.time": secs}},
                upsert=True
            )

        now = datetime.now(timezone.utc)
        log_id = self.members[member_id].get("log_id")
        if log_id:
            act_col = collections.get("session.logs")
            if act_col is not None:
                act_col.update_one(
                    {"_id": log_id},
                    {"$set": {"left_at": now.isoformat()}}
                )

    def _start_sub_session(self, member_id: str):
        now = datetime.now(timezone.utc)
        if member_id not in self.members:
            self.members[member_id] = {
                "net_time": {"cam": 0, "ss": 0, "noact": 0, "total": 0},
                "last_activity": "noact",
            }

        act_col = collections.get("session.logs")
        if act_col is not None:
            latest = act_col.find_one(
                {"user_id": member_id, "session_id": self.session_id},
                sort=[("_id", -1)]
            )
            if latest and latest.get("left_at"):
                left_time = latest["left_at"]
                if isinstance(left_time, str):
                    left_time = datetime.fromisoformat(left_time)
                if (now - left_time).total_seconds() <= 60:
                    act_col.update_one(
                        {"_id": latest["_id"]},
                        {"$set": {
                            "left_at": None,
                            "joined_at.time": now.isoformat(),
                        }}
                    )
                    self.members[member_id]["log_id"] = latest["_id"]
                    self._reset_seg(member_id)
                    return

        result = act_col.insert_one({
            "user_id": member_id,
            "session_id": self.session_id,
            "guild_id": self.guild_id,
            "joined_at": {
                "time": now.isoformat(),
                "ss": 0,
                "noact": 0,
                "cam": 0,
                "total": 0,
            },
            "left_at": None,
        }) if act_col is not None else None
        if result:
            self.members[member_id]["log_id"] = result.inserted_id
        self._reset_seg(member_id)

    def _update_members_count(self):
        total = len(self.members)
        cam = 0
        ss = 0
        noact = 0
        for mid, mdata in self.members.items():
            if not isinstance(mdata, dict):
                continue
            act_type = mdata.get("last_activity", "noact")
            if act_type == "cam+ss":
                cam += 1
                ss += 1
            elif act_type == "cam":
                cam += 1
            elif act_type == "ss":
                ss += 1
            else:
                noact += 1
        self.members_count = {
            "total": total,
            "noact": noact,
            "ss": ss,
            "cam": cam,
        }

    def _track_activity_change(self, member_id: str, old_type: str, new_type: str):
        secs = self._seg_elapsed(member_id)
        if secs > 0:
            self._accrue_time(member_id, old_type, secs)
        self._reset_seg(member_id)
        self.members[member_id]["last_activity"] = new_type
        self._update_members_count()

    def _update_user_time(self, member: Member, activity_type: str = None):
        member_id = str(member.id)
        if member_id not in self.members:
            return

        secs = self._seg_elapsed(member_id)
        if secs <= 0:
            return

        act_type = activity_type or self.members[member_id].get("last_activity", "noact")
        self._accrue_time(member_id, act_type, secs)
        self._reset_seg(member_id)

        u_col = collections.get('user')
        if u_col is not None:
            u_col.update_one(
                {"_id": member_id},
                {
                    "$inc": {f"servers.{self.guild_id}.time": secs},
                    "$set": {"name": member.display_name},
                    "$setOnInsert": {"_id": member_id}
                },
                upsert=True
            )

    async def manage(self, member: Member, before: VoiceState, after: VoiceState, exceptions_handler=None, session_category_id=None, ignore_channel_id=None):
        member_id = str(member.id)
        
        channel = after.channel if (after.channel and str(after.channel.id) == self.channel_id) else before.channel
        
        is_after_in_session = after.channel and str(after.channel.id) == self.channel_id
        is_before_in_session = before.channel and str(before.channel.id) == self.channel_id
        
        if is_after_in_session and not is_before_in_session:
            # JOIN EVENT
            if self.owner_id is None:
                self.owner_id = member_id

            self._start_sub_session(member_id)
            after_type = _get_activity_type(after)
            self.members[member_id]["last_activity"] = after_type
            self._update_members_count()

            if len(self.members) == 1 and (not self.drop_task or self.drop_task.done()):
                if not self.started_at:
                    self.started_at = datetime.now(timezone.utc).isoformat()
                    self._sync_session_now()
                self.drop_task = asyncio.create_task(self.drop_routine(channel))
            
            if not self._is_allowed(after_type):
                task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                self.monitor_tasks[member_id] = task

            avatar_url = member.display_avatar.url if member.display_avatar else ""
            await self._emit_event("member_join", {
                "user_id": member_id,
                "username": member.name,
                "display_name": member.display_name,
                "avatar_url": avatar_url,
                "activity": after_type,
                "is_web_user": False,
            })

            import secrets, os, qrcode, io
            dm_status = False
            u_col = collections.get('user')
            if u_col is not None:
                web_token = secrets.token_urlsafe(32)
                u_col.update_one(
                    {"_id": member_id},
                    {"$set": {"webToken": web_token, "current_session": self.session_id}},
                    upsert=True
                )
                domain = os.getenv("FRONTEND_DOMAIN")
                if domain and not domain.endswith('/'):
                    domain = domain + "/"
                link = f"{domain}projects?webtoken={web_token}&session={self.session_id}"

                if not is_muted(member_id):
                    try:
                        qr = qrcode.QRCode(box_size=10, border=8)
                        qr.add_data(link)
                        qr.make(fit=True)
                        img = qr.make_image(fill="black", back_color="white")

                        with io.BytesIO() as image_binary:
                            img.save(image_binary, format="WEBP")
                            image_binary.seek(0)
                            await member.send(
                                content=f"# **[__Productivity Access!__](<{link}>)**\nThis link is only valid while you are in the study voice channel.",
                                file=discord.File(image_binary, "qrcode.png")
                            )
                        dm_status = True
                    except Exception:
                        dm_status = False
                
            who = member.display_name if is_muted(member_id) else member.mention
            embed = discord.Embed(
                title=f"\U0001f389 {member.display_name} joined the session! \U0001f389",
                description=f"Welcome {who}!\nStudy time starts!",
                color=0x3498DB,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            if dm_status:
                embed.add_field(name="Project Access", value="Secret access link has been sent to your DMs! :ninja:", inline=False)
            else:
                embed.add_field(name="Project Access", value="\u274c I couldn't DM you the access link. Please open your DMs and rejoin!", inline=False)

            if not self._is_allowed(after_type):
                embed.add_field(
                    name="\u26a0\ufe0f Session Type Restriction",
                    value=f"\U0001f534 This session requires **{self._type_description()}**.\nTurn on the required devices, or you'll be removed after 5 minutes!",
                    inline=False
                )
            try:
                await channel.send(content=who, embed=embed, delete_after=20)
            except (discord.NotFound, discord.HTTPException):
                pass
            
        elif is_before_in_session and not is_after_in_session:
            # LEAVE EVENT
            if member_id in self.monitor_tasks:
                self.monitor_tasks[member_id].cancel()
                del self.monitor_tasks[member_id]

            leave_act_type = self.members.get(member_id, {}).get("last_activity", "noact") if member_id in self.members else "noact"
            self._close_sub_session(member_id, leave_act_type)
            self.members.pop(member_id, None)
            old_owner = self.owner_id
            if member_id == old_owner:
                self.owner_id = next(iter(self.members)) if self.members else None
            self._update_members_count()

            await self._emit_event("member_leave", {
                "user_id": member_id,
            })
            if self.owner_id != old_owner:
                await self._emit_event("owner_change", {
                    "owner_id": self.owner_id,
                })

            u_col = collections.get('user')
            if u_col is not None:
                user_doc = u_col.find_one({"_id": member_id}, {"current_session": 1})
                if user_doc and user_doc.get("current_session") == self.session_id:
                    u_col.update_one(
                        {"_id": member_id},
                        {"$unset": {"webToken": "", "current_session": ""}}
                    )

            has_discord_members = any(
                not m.get("is_web_user", False)
                for m in self.members.values()
                if isinstance(m, dict)
            )

            if not self.channel_id.startswith("w") and not has_discord_members and self.members:
                self.channel_id = f"w{self.owner_id}"
                self.guild_id = "web"
                self._sync_session_now()

                if self.drop_task and not self.drop_task.done():
                    pass
            
            if len(self.members) == 0 and self.drop_task:
                self.drop_task.cancel()
                self.drop_task = None
            
            try:
                who = member.display_name if is_muted(member_id) else member.mention
                await channel.send(
                    embed=discord.Embed(
                        description=f"{who} might be on a break. \u2615",
                        color=0x3498DB,
                    ),
                    delete_after=90,
                )
            except discord.NotFound:
                pass
            except Exception:
                pass
            
        elif is_before_in_session and is_after_in_session:
            # STILL IN SESSION (Activity state changed)
            old_type = self.members.get(member_id, {}).get("last_activity", "noact") if member_id in self.members else "noact"
            new_type = _get_activity_type(after)

            if old_type != new_type:
                self._track_activity_change(member_id, old_type, new_type)
                await self._emit_event("activity_change", {
                    "user_id": member_id,
                    "activity": new_type,
                })

                if not self._is_allowed(new_type):
                    if member_id not in self.monitor_tasks:
                        task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                        self.monitor_tasks[member_id] = task
                        try:
                            who = member.display_name if is_muted(member_id) else member.mention
                            await channel.send(
                                embed=discord.Embed(
                                    description=f"{who} Your activity doesn't match this session's requirements ({self._type_description()}). \u26a0\ufe0f",
                                    color=0x3498DB,
                                ),
                                delete_after=20,
                            )
                        except (discord.NotFound, discord.HTTPException):
                            pass
                elif member_id in self.monitor_tasks:
                    self.monitor_tasks[member_id].cancel()
                    del self.monitor_tasks[member_id]

            if checks.is_activity_started(before, after):
                if self._is_allowed(new_type) and member_id in self.monitor_tasks:
                    self.monitor_tasks[member_id].cancel()
                    del self.monitor_tasks[member_id]

                if self.session_type != "*":
                    try:
                        who = member.display_name if is_muted(member_id) else member.mention
                        await channel.send(
                            embed=discord.Embed(
                                description=f"{who}'s Activity Detected! \u2705",
                                color=0x3498DB,
                            ),
                            delete_after=20,
                        )
                    except (discord.NotFound, discord.HTTPException):
                        pass
                
            elif checks.is_activity_stopped(before, after) and not self._is_allowed("noact"):
                if not exceptions_handler or await exceptions_handler.isNotInside(member_id):
                    self._update_user_time(member, old_type)
                    
                    who = member.display_name if is_muted(member_id) else member.mention
                    embed = discord.Embed(
                        title="\u26a0\ufe0f Attention Required!",
                        description=f"{who}, you turned off your camera or screen share.\n"
                        "Please turn it back on within **5 minutes**, or you will be removed.",
                        color=discord.Color.orange(),
                    )
                    try:
                        await channel.send(embed=embed, delete_after=20)
                    except (discord.NotFound, discord.HTTPException):
                        pass
                    
                    old_task = self.monitor_tasks.get(member_id)
                    if old_task:
                        old_task.cancel()
                        
                    task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                    self.monitor_tasks[member_id] = task

class SessionManager:
    """
    Manages discord study sessions seamlessly. Ensures single point of handling and DB sync.
    """
    def __init__(self, event_bus=None):
        self.active_sessions = {}
        self.channel_sessions = {}
        self.user_sessions = {}
        self.event_bus = event_bus

    def _get_collection(self):
        col = session_collection()
        if col is None:
            raise Exception("Session collection not initialized.")
        return col

    def sync(self, session: Session):
        """Syncs a single session state to MongoDB."""
        col = self._get_collection()
        col.update_one(
            {"session_id": session.session_id},
            {"$set": session.to_dict()},
            upsert=True
        )

    async def get_or_create_session(self, guild_id: str, channel_id: str) -> Session:
        """Fetches from memory, then DB, or creates anew."""
        existing_sid = self.channel_sessions.get(channel_id)
        if existing_sid and existing_sid in self.active_sessions:
            return self.active_sessions[existing_sid]

        col = self._get_collection()
        data = col.find_one({"channel_id": channel_id})
        
        if data:
            session = Session.from_dict(data)
        else:
            session = Session(
                guild_id=guild_id,
                channel_id=channel_id
            )
        
        session.event_bus = self.event_bus
        self.active_sessions[session.session_id] = session
        self.channel_sessions[channel_id] = session.session_id
        for mid in session.members:
            self.user_sessions[mid] = session.session_id
        return session

    async def process(self, member: Member, before: VoiceState, after: VoiceState, session_category_id: str, ignore_channel_id: str = None, exceptions_handler=None, **kwargs):
        """
        Single entry point to handle voice state updates.
        Delegates the event to the correct Session object(s) and ensures DB synchronization.
        """
        member_id = str(member.id)

        current_sid = self.user_sessions.get(member_id)
        if not current_sid:
            u_col = collections.get('user')
            if u_col is not None:
                user_doc = u_col.find_one({"_id": member_id}, {"current_session": 1})
                if user_doc and user_doc.get("current_session"):
                    current_sid = user_doc["current_session"]
                    self.user_sessions[member_id] = current_sid

        channels_involved = set()
        
        if before.channel and checks.get_session_status(before, session_category_id, ignore_channel_id):
            channels_involved.add(str(before.channel.id))
        
        if after.channel and checks.get_session_status(after, session_category_id, ignore_channel_id):
            channels_involved.add(str(after.channel.id))

        for channel_id in channels_involved:
            session = await self.get_or_create_session(str(member.guild.id), channel_id)

            if current_sid and session.session_id != current_sid:
                old_session = self.active_sessions.get(current_sid)
                if old_session:
                    old_user_data = old_session.members.get(member_id)
                    if old_user_data:
                        leave_act = old_user_data.get("last_activity", "noact")
                        old_session._close_sub_session(member_id, leave_act)
                        old_session.members.pop(member_id, None)
                        old_owner = old_session.owner_id
                        if member_id == old_owner:
                            old_session.owner_id = next(iter(old_session.members)) if old_session.members else None
                        old_session._update_members_count()

                        u_col = collections.get('user')
                        if u_col is not None:
                            u_col.update_one(
                                {"_id": member_id},
                                {"$unset": {"webToken": "", "current_session": ""}}
                            )

                        has_discord = any(
                            not m.get("is_web_user", False)
                            for m in old_session.members.values()
                            if isinstance(m, dict)
                        )
                        old_ch = old_session.channel_id
                        if not old_ch.startswith("w") and not has_discord and old_session.members:
                            old_session.channel_id = f"w{old_session.owner_id}"
                            old_session.guild_id = "web"
                            self.channel_sessions.pop(old_ch, None)
                            self.channel_sessions[old_session.channel_id] = old_session.session_id

                        if len(old_session.members) == 0:
                            self._cleanup_session(old_session)
                        else:
                            await old_session._emit_event("member_leave", {"user_id": member_id})
                            if old_session.owner_id != old_owner:
                                await old_session._emit_event("owner_change", {"owner_id": old_session.owner_id})
                            self.sync(old_session)
                else:
                    u_col = collections.get('user')
                    if u_col is not None:
                        u_col.update_one(
                            {"_id": member_id},
                            {"$unset": {"current_session": "", "webToken": ""}}
                        )
                    self.user_sessions.pop(member_id, None)
                    current_sid = None

            old_channel_id = session.channel_id
            session.update_settings(**kwargs)
            try:
                await session.manage(member, before, after, exceptions_handler, session_category_id, ignore_channel_id)
            finally:
                self.sync(session)

            if session.channel_id != old_channel_id:
                self.channel_sessions.pop(old_channel_id, None)
                self.channel_sessions[session.channel_id] = session.session_id

            if member_id in session.members:
                self.user_sessions[member_id] = session.session_id
            else:
                self.user_sessions.pop(member_id, None)

    def _cleanup_session(self, session: Session):
        """Remove a session from memory and DB."""
        u_col = collections.get('user')
        if u_col is not None:
            for uid in session.members:
                u_col.update_one(
                    {"_id": uid, "current_session": session.session_id},
                    {"$unset": {"current_session": ""}}
                )
        if session.session_id in self.active_sessions:
            del self.active_sessions[session.session_id]
        old_ch = None
        for ch, sid in list(self.channel_sessions.items()):
            if sid == session.session_id:
                old_ch = ch
                break
        if old_ch:
            del self.channel_sessions[old_ch]
        for uid, sid in list(self.user_sessions.items()):
            if sid == session.session_id:
                del self.user_sessions[uid]
        col = self._get_collection()
        col.delete_one({"session_id": session.session_id})
        if session.drop_task and not session.drop_task.done():
            session.drop_task.cancel()
