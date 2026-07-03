import asyncio
import secrets
import os
from datetime import datetime, timezone, timedelta
from . import collections
from . import checks
from discord import VoiceState, Member
import discord
import random
import config

import pymongo
session_collection = lambda: collections.get('session')

def _get_activity_type(state: VoiceState) -> str:
    if state.self_video and state.self_stream:
        return "cam+ss"
    elif state.self_video:
        return "cam"
    elif state.self_stream:
        return "ss"
    return "noact"

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
        **kwargs
    ):
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
        
    def to_dict(self):
        """Convert session state to dictionary for MongoDB."""
        d = {
            "_id": self.channel_id,
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
        }
        return d

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Session from MongoDB document."""
        data.pop("_id", None)
        return cls(**data)

    async def activity_monitor(self, member: Member, exceptions_handler=None, session_category_id=None, ignore_channel_id=None):
        """Wait 5 minutes and disconnect user if they don't comply with session type or activity requirements."""
        await asyncio.sleep(300)
        
        if member.voice and checks.get_session_status(member.voice, session_category_id, ignore_channel_id) and str(member.voice.channel.id) == self.channel_id:
            after_type = _get_activity_type(member.voice)
            if not self._is_allowed(after_type):
                try:
                    embed = discord.Embed(
                        description=f"{member.mention} You do not meet the session type requirements ({self._type_description()}). \U0001f6a8",
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
                {"_id": self.channel_id},
                {"$set": self.to_dict()},
                upsert=True
            )

    async def drop_routine(self, channel: discord.VoiceChannel):
        try:
            while True:
                try:
                    v = config.DROP_VARIANCE
                    interval = random.uniform(1 - v, 1 + v) * self.routine_callback_mean_time
                    await asyncio.sleep(interval * 60)

                    if not channel.members:
                        continue

                    token = secrets.token_urlsafe(32)
                    d_col = collections.get("drop.offers")
                    if d_col is not None:
                        d_col.insert_one({
                            "token": token,
                            "guild_id": self.guild_id,
                            "channel_id": self.channel_id,
                            "drop_number": self.routines_fired_count + 1,
                            "created_at": datetime.now(timezone.utc),
                            "expire_at": datetime.now(timezone.utc) + timedelta(seconds=config.DROP_COLLECTION_TIME + 5),
                        })

                    domain = os.getenv("FRONTEND_DOMAIN", "")
                    if domain and not domain.endswith("/"):
                        domain += "/"
                    link = f"{domain}drops?token={token}"

                    self.routines_fired_count += 1
                    self._sync_session_now()

                    embed = discord.Embed(
                        title="\U0001f381 Drops Have Landed!",
                        description=f"Someone dropped goodies in the study VC!\n\U0001f4e6 **[__Collect yours here by clicking this text!__]({link})**",
                        color=discord.Color.gold()
                    )
                    embed.set_footer(text="*Hurry \u2014 everyone can claim once!*")
                    await channel.send(embed=embed, delete_after=config.DROP_COLLECTION_TIME)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"Drop routine iteration error: {e}")

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
                {"user_id": member_id, "session_id": self.channel_id},
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
            "session_id": self.channel_id,
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
                self.drop_task = asyncio.create_task(self.drop_routine(channel))
            
            if not self._is_allowed(after_type):
                task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                self.monitor_tasks[member_id] = task

            import secrets, os, qrcode, io
            dm_status = False
            u_col = collections.get('user')
            if u_col is not None:
                web_token = secrets.token_urlsafe(32)
                u_col.update_one(
                    {"_id": member_id},
                    {"$set": {"webToken": web_token}},
                    upsert=True
                )
                domain = os.getenv("WEBSITE_DOMAIN")
                if domain and not domain.endswith('/'):
                    domain = domain + "/"
                link = f"{domain}projects/{web_token}"

                qr = qrcode.QRCode(box_size=10, border=8)
                qr.add_data(link)
                qr.make(fit=True)
                img = qr.make_image(fill="black", back_color="white")

                try:
                    with io.BytesIO() as image_binary:
                        img.save(image_binary, format="WEBP")
                        image_binary.seek(0)
                        await member.send(
                            content=f"# **[__Productivity Access!__](<{link}>)**\nThis link is only valid while you are in the study voice channel.",
                            file=discord.File(image_binary, "qrcode.png")
                        )
                    dm_status = True
                except discord.Forbidden:
                    dm_status = False
                
            embed = discord.Embed(
                title=f"\U0001f389 {member.display_name} joined the session! \U0001f389",
                description=f"Welcome {member.mention}!\nStudy time starts!",
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
            await channel.send(content=member.mention, embed=embed, delete_after=20)
            
        elif is_before_in_session and not is_after_in_session:
            # LEAVE EVENT
            if member_id in self.monitor_tasks:
                self.monitor_tasks[member_id].cancel()
                del self.monitor_tasks[member_id]

            leave_act_type = self.members.get(member_id, {}).get("last_activity", "noact") if member_id in self.members else "noact"
            self._close_sub_session(member_id, leave_act_type)
            self.members.pop(member_id, None)
            if member_id == self.owner_id:
                self.owner_id = next(iter(self.members)) if self.members else None
            self._update_members_count()

            u_col = collections.get('user')
            if u_col is not None:
                u_col.update_one({"_id": member_id}, {"$unset": {"webToken": ""}})
            
            if len(self.members) == 0 and self.drop_task:
                self.drop_task.cancel()
                self.drop_task = None
            
            try:
                await channel.send(
                    embed=discord.Embed(
                        description=f"{member.mention} might be on a break. \u2615",
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

                if not self._is_allowed(new_type):
                    if member_id not in self.monitor_tasks:
                        task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                        self.monitor_tasks[member_id] = task
                        await channel.send(
                            embed=discord.Embed(
                                description=f"{member.mention} Your activity doesn't match this session's requirements ({self._type_description()}). \u26a0\ufe0f",
                                color=0x3498DB,
                            ),
                            delete_after=20,
                        )
                elif member_id in self.monitor_tasks:
                    self.monitor_tasks[member_id].cancel()
                    del self.monitor_tasks[member_id]

            if checks.is_activity_started(before, after):
                if self._is_allowed(new_type) and member_id in self.monitor_tasks:
                    self.monitor_tasks[member_id].cancel()
                    del self.monitor_tasks[member_id]

                if self.session_type != "*":
                    await channel.send(
                        embed=discord.Embed(
                            description=f"{member.mention}'s Activity Detected! \u2705",
                            color=0x3498DB,
                        ),
                        delete_after=20,
                    )
                
            elif checks.is_activity_stopped(before, after) and not self._is_allowed("noact"):
                if not exceptions_handler or exceptions_handler.isNotInside(member_id):
                    self._update_user_time(member, old_type)
                    
                    embed = discord.Embed(
                        title="\u26a0\ufe0f Attention Required!",
                        description=f"{member.mention}, you turned off your camera or screen share.\n"
                        "Please turn it back on within **5 minutes**, or you will be removed.",
                        color=discord.Color.orange(),
                    )
                    await channel.send(embed=embed, delete_after=20)
                    
                    old_task = self.monitor_tasks.get(member_id)
                    if old_task:
                        old_task.cancel()
                        
                    task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
                    self.monitor_tasks[member_id] = task

class SessionManager:
    """
    Manages discord study sessions seamlessly. Ensures single point of handling and DB sync.
    """
    def __init__(self):
        self.active_sessions = {}

    def _get_collection(self):
        col = session_collection()
        if col is None:
            raise Exception("Session collection not initialized.")
        return col

    def sync(self, session: Session):
        """Syncs a single session state to MongoDB."""
        col = self._get_collection()
        col.update_one(
            {"_id": session.channel_id},
            {"$set": session.to_dict()},
            upsert=True
        )

    async def get_or_create_session(self, guild_id: str, channel_id: str) -> Session:
        """Fetches from memory, then DB, or creates anew."""
        if channel_id in self.active_sessions:
            return self.active_sessions[channel_id]

        col = self._get_collection()
        data = col.find_one({"_id": channel_id})
        
        if data:
            session = Session.from_dict(data)
        else:
            session = Session(
                guild_id=guild_id,
                channel_id=channel_id
            )
            
        self.active_sessions[channel_id] = session
        return session

    async def process(self, member: Member, before: VoiceState, after: VoiceState, session_category_id: str, ignore_channel_id: str = None, exceptions_handler=None, **kwargs):
        """
        Single entry point to handle voice state updates.
        Delegates the event to the correct Session object(s) and ensures DB synchronization.
        """
        channels_involved = set()
        
        if before.channel and checks.get_session_status(before, session_category_id, ignore_channel_id):
            channels_involved.add(str(before.channel.id))
        
        if after.channel and checks.get_session_status(after, session_category_id, ignore_channel_id):
            channels_involved.add(str(after.channel.id))

        for channel_id in channels_involved:
            session = await self.get_or_create_session(str(member.guild.id), channel_id)
            session.update_settings(**kwargs)
            await session.manage(member, before, after, exceptions_handler, session_category_id, ignore_channel_id)
            self.sync(session)
