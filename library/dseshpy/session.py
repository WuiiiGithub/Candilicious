import asyncio
from datetime import datetime
from . import collections
from . import checks
from discord import VoiceState, Member
import discord
import random

# the below import and assigning is just for keyboard auto complete help
import pymongo
session_collection = lambda: collections.get('session')

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
        routine_callback_mean_time: int = 30, # interval in minutes
        routine_drop_amount: int = 10,
        routines_fired_count: int=0,

        # session type
        is_cam_session: bool = False,
        is_screen_share_session: bool = False,
        is_no_activity_session: bool = True,
        is_type_restricted_session: bool = False,
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
        self.is_cam_session = is_cam_session
        self.is_screen_share_session = is_screen_share_session
        self.is_no_activity_session = is_no_activity_session
        self.is_type_restricted_session = is_type_restricted_session
        
        self.members = members or {}
        self.active_count = active_count
        
        self.routine_callback_mean_time = routine_callback_mean_time
        self.routine_drop_amount = routine_drop_amount
        self.routines_fired_count = routines_fired_count
        
        # in-memory task tracking (not saved to DB)
        self.monitor_tasks = {}
        self.drop_task = None
        
    def to_dict(self):
        """Convert session state to dictionary for MongoDB."""
        return {
            "_id": self.channel_id,
            "owner_id": self.owner_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "members": self.members,
            "active_count": self.active_count,
            "members_limit": self.members_limit,
            "members_count": self.members_count,
            "vc_level": self.vc_level,
            "vc_xp": self.vc_xp,
            "rent_type": self.rent_type,
            "rent_amount": self.rent_amount,
            "routine_callback_mean_time": self.routine_callback_mean_time,
            "routine_drop_amount": self.routine_drop_amount,
            "routines_fired_count": self.routines_fired_count,
            "is_cam_session": self.is_cam_session,
            "is_screen_share_session": self.is_screen_share_session,
            "is_no_activity_session": self.is_no_activity_session,
            "is_type_restricted_session": self.is_type_restricted_session,
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Create a Session from MongoDB document."""
        data.pop("_id", None)
        return cls(**data)

    async def activity_monitor(self, member: Member, exceptions_handler=None, session_category_id=None, ignore_channel_id=None):
        """Wait 5 minutes and disconnect user if they don't enable camera or screen share."""
        await asyncio.sleep(300)
        
        if member.voice and checks.get_session_status(member.voice, session_category_id, ignore_channel_id) and str(member.voice.channel.id) == self.channel_id:
            if not checks.is_session_activity(member.voice):
                try:
                    await member.voice.channel.send(
                        embed=discord.Embed(
                            description=f"{member.mention} Inactivity Detected. 🚨",
                            color=0x3498DB,
                        ),
                        delete_after=20,
                    )
                    await member.move_to(None)
                    # Time during this inactivity is voided
                    self.members.pop(str(member.id), None)
                except:
                    pass

    async def drop_routine(self, channel: discord.VoiceChannel):
        """Drops randomized rewards periodically for all members in the session based on their activity."""
        try:
            while True:
                # Calculate randomized interval
                interval = random.uniform(0.5, 1.5) * self.routine_callback_mean_time
                await asyncio.sleep(interval * 60)
                
                if not channel.members:
                    continue
                    
                embed = discord.Embed(
                    title="💰 Session Rewards Dropped! 💰",
                    color=discord.Color.gold()
                )
                
                base_drop = self.routine_drop_amount
                # Renting, boosting, and VC level increase rewards
                multiplier = 1.0 + (self.vc_level * 0.1) + (self.rent_amount * 0.05)
                
                drop_details = []
                for member in channel.members:
                    if member.bot: continue
                    
                    state = member.voice
                    if not state: continue
                    
                    # Reward hierarchy
                    if state.self_video and state.self_stream:
                        activity_mult = 2.5
                        act_str = "Cam + Stream"
                    elif state.self_video:
                        activity_mult = 2.0
                        act_str = "Cam"
                    elif state.self_stream:
                        activity_mult = 1.5
                        act_str = "Stream"
                    else:
                        activity_mult = 1.0
                        act_str = "No Activity"
                        
                    mean_drop = base_drop * multiplier * activity_mult
                    variance = mean_drop * 0.2  # 20% variance shift
                    
                    actual_drop = max(1, int(random.uniform(mean_drop - variance, mean_drop + variance)))
                    
                    drop_details.append(f"{member.mention}: **{actual_drop}** 🪙 *({act_str})*")
                
                if drop_details:
                    embed.description = "\n".join(drop_details)
                    self.routines_fired_count += 1
                    await channel.send(embed=embed, delete_after=60)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Drop routine error: {e}")

    def update_settings(self, **kwargs):
        """Dynamically update session details like rent, vc_level, etc., ensuring DB sync."""
        updated = False
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                updated = True
        return updated

    def _handle_activity_start(self):
        self.active_count += 1

    def _handle_activity_stop(self):
        self.active_count = max(0, self.active_count - 1)
        
    def _update_user_time(self, member: Member):
        member_id = str(member.id)
        if member_id in self.members and "joined_at" in self.members[member_id]:
            joined_at = datetime.fromisoformat(self.members[member_id]["joined_at"])
            secs = (datetime.now() - joined_at).total_seconds()
            
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
            self.members[member_id]["joined_at"] = datetime.now().isoformat()

    async def manage(self, member: Member, before: VoiceState, after: VoiceState, exceptions_handler=None, session_category_id=None, ignore_channel_id=None):
        member_id = str(member.id)
        
        # Determine the channel relevant to this session instance
        channel = after.channel if (after.channel and str(after.channel.id) == self.channel_id) else before.channel
        
        is_after_in_session = after.channel and str(after.channel.id) == self.channel_id
        is_before_in_session = before.channel and str(before.channel.id) == self.channel_id
        
        if is_after_in_session and not is_before_in_session:
            # JOIN EVENT
            self.members[member_id] = {"joined_at": datetime.now().isoformat()}
            
            # Start drop task if first member joins
            if len(self.members) == 1 and not self.drop_task:
                self.drop_task = asyncio.create_task(self.drop_routine(channel))
            
            task = asyncio.create_task(self.activity_monitor(member, exceptions_handler, session_category_id, ignore_channel_id))
            self.monitor_tasks[member_id] = task
            
            if checks.is_session_activity(after):
                self._handle_activity_start()
                task.cancel()
                self.monitor_tasks.pop(member_id, None)

            # Project Access Logic
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
                title=f"🎉 {member.display_name} joined the session! 🎉",
                description=f"Welcome {member.mention}!\nStudy time starts!",
                color=0x3498DB,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            if dm_status:
                embed.add_field(name="Project Access", value="Secret access link has been sent to your DMs! :ninja:", inline=False)
            else:
                embed.add_field(name="Project Access", value="❌ I couldn't DM you the access link. Please open your DMs and rejoin!", inline=False)

            if not exceptions_handler or exceptions_handler.isNotInside(member_id):
                embed.add_field(
                    name="Request",
                    value="🔴 Please turn on your **camera or screen share**. Otherwise, you may be removed after 5 minutes!",
                    inline=False
                )
            await channel.send(content=member.mention, embed=embed, delete_after=20)
            
        elif is_before_in_session and not is_after_in_session:
            # LEAVE EVENT
            if member_id in self.monitor_tasks:
                self.monitor_tasks[member_id].cancel()
                del self.monitor_tasks[member_id]

            self._update_user_time(member)
            self.members.pop(member_id, None)
            
            # Revoke Project Access
            u_col = collections.get('user')
            if u_col is not None:
                u_col.update_one({"_id": member_id}, {"$unset": {"webToken": ""}})
            
            # Cancel drop task if everyone left
            if len(self.members) == 0 and self.drop_task:
                self.drop_task.cancel()
                self.drop_task = None
            
            if checks.is_session_activity(before):
                self._handle_activity_stop()
                
            await channel.send(
                embed=discord.Embed(
                    description=f"{member.mention} might be on a break. ☕",
                    color=0x3498DB,
                ),
                delete_after=90,
            )
            
        elif is_before_in_session and is_after_in_session:
            # STILL IN SESSION (Activity state changed)
            if checks.is_activity_started(before, after):
                if member_id in self.monitor_tasks:
                    self.monitor_tasks[member_id].cancel()
                    del self.monitor_tasks[member_id]
                    
                self._handle_activity_start()
                
                await channel.send(
                    embed=discord.Embed(
                        description=f"{member.mention}'s Activity Detected! ✅",
                        color=0x3498DB,
                    ),
                    delete_after=20,
                )
                
            elif checks.is_activity_stopped(before, after):
                self._handle_activity_stop()
                
                if not exceptions_handler or exceptions_handler.isNotInside(member_id):
                    self._update_user_time(member)
                    
                    embed = discord.Embed(
                        title="⚠️ Attention Required!",
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

