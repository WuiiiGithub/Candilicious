"""
RecoveryManager — orchestrates snapshot creation and startup recovery.
"""
import asyncio
import traceback
from datetime import datetime, timezone, timedelta
from library.logging import SystemLogger

log = SystemLogger(filename="Recovery")


class RecoveryManager:
    """
    Manages state snapshots and recovery for interrupted sessions.

    Usage:
        recovery = RecoveryManager(db, session_manager, event_bus, bot)
        await recovery.recover()          # call once on bot on_ready
        recovery.start_snapshot_task()    # start periodic snapshots
    """

    def __init__(self, db, session_manager=None, event_bus=None, bot=None):
        self.db = db
        self.snapshots = db["recovery.snapshots"]

        self.session_manager = session_manager
        self.event_bus = event_bus
        self.bot = bot
        self._snapshot_task = None

    # ─────────────────────── SNAPSHOT ───────────────────────

    async def take_snapshot(self):
        """Capture a point-in-time snapshot of all active sessions."""
        try:
            sessions = list(self.db["sessions"].find({}))
            for doc in sessions:
                doc.pop("_id", None)

            snapshot = {
                "timestamp": datetime.now(timezone.utc),
                "session_count": len(sessions),
                "sessions": sessions,
            }
            result = self.snapshots.insert_one(snapshot)

            # Prune old snapshots — keep last 50
            count = self.snapshots.count_documents({})
            if count > 50:
                oldest = list(self.snapshots.find().sort("timestamp", 1).limit(count - 50))
                ids = [d["_id"] for d in oldest]
                self.snapshots.delete_many({"_id": {"$in": ids}})

            return result.inserted_id
        except Exception as e:
            log.error(
                status_code=-50,
                message="Snapshot Failed",
                details=f"Could not take recovery snapshot: {e}",
            )
            return None

    def start_snapshot_task(self, interval_minutes=5):
        """Start a background loop that takes periodic snapshots."""
        if self._snapshot_task and not self._snapshot_task.done():
            return
        self._snapshot_task = asyncio.create_task(self._snapshot_loop(interval_minutes))

    def stop_snapshot_task(self):
        if self._snapshot_task and not self._snapshot_task.done():
            self._snapshot_task.cancel()

    async def _snapshot_loop(self, interval_minutes):
        try:
            while True:
                await asyncio.sleep(interval_minutes * 60)
                await self.take_snapshot()
        except asyncio.CancelledError:
            pass

    # ─────────────────────── RECOVERY ───────────────────────

    async def recover(self):
        """
        Main recovery entry point. Called once on bot ready.

        For each session in DB:
        - Discord sessions: check if VC still exists and has members
        - Web sessions: check if any member has recent activity
        - Cleanup orphaned user.current_session references
        """
        print("[Recovery] === RECOVERY START ===", flush=True)

        stats = {
            "resumed": 0,
            "cleaned": 0,
            "orphan_refs_cleared": 0,
            "errors": 0,
        }

        try:
            session_docs = list(self.db["sessions"].find({}))
            print(f"[Recovery] Found {len(session_docs)} session(s) in DB", flush=True)

            for session_doc in session_docs:
                try:
                    await self._recover_session(session_doc, stats)
                except Exception as e:
                    stats["errors"] += 1
                    print(f"[Recovery] ERROR recovering session {session_doc.get('session_id')}: {e}", flush=True)

            # Clean orphaned user.current_session refs
            self._clean_orphaned_user_refs(stats)

            # Clean stale drop offers
            self._clean_stale_drops()

            print(
                f"[Recovery] === RECOVERY DONE === "
                f"Resumed: {stats['resumed']}, Cleaned: {stats['cleaned']}, "
                f"Orphan refs cleared: {stats['orphan_refs_cleared']}, Errors: {stats['errors']}",
                flush=True,
            )
            return stats

        except Exception as e:
            print(f"[Recovery] FATAL: {traceback.format_exc()}", flush=True)
            return stats

    async def _recover_session(self, session_doc: dict, stats: dict):
        """Recover or clean up a single session."""
        session_id = session_doc.get("session_id")
        channel_id = session_doc.get("channel_id", "")
        guild_id = session_doc.get("guild_id", "")
        members = session_doc.get("members", {})
        owner_id = session_doc.get("owner_id")

        if not session_id:
            print("[Recovery] Skipping session with no session_id", flush=True)
            return

        print(f"[Recovery] Session {session_id}: guild={repr(guild_id)}, channel={repr(channel_id)}, members={len(members)}", flush=True)

        # ── Discord VC session ──
        if guild_id and guild_id != "web" and not channel_id.startswith("w"):
            print(f"[Recovery] → Routing to Discord recovery", flush=True)
            await self._recover_discord_session(session_doc, stats)
            return

        # ── Web-only session ──
        if guild_id == "web" or channel_id.startswith("w"):
            print(f"[Recovery] → Routing to Web recovery", flush=True)
            await self._recover_web_session(session_doc, stats)
            return

        print(f"[Recovery] → SKIPPED (no matching recovery path! guild={repr(guild_id)}, channel={repr(channel_id)})", flush=True)

    async def _recover_discord_session(self, session_doc: dict, stats: dict):
        """Recover a Discord voice channel session."""
        session_id = session_doc.get("session_id")
        channel_id = session_doc.get("channel_id")
        guild_id = session_doc.get("guild_id")
        members = session_doc.get("members", {})

        print(f"[Recovery] Discord session {session_id}: guild={guild_id}, channel={channel_id}, members={list(members.keys())}", flush=True)

        if not self.bot:
            print(f"[Recovery] No bot instance — cleaning", flush=True)
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # Check if the voice channel still exists
        try:
            guild = self.bot.get_guild(int(guild_id))
            print(f"[Recovery] get_guild({guild_id}) → {guild}", flush=True)
        except (ValueError, TypeError) as e:
            print(f"[Recovery] get_guild failed: {e}", flush=True)
            guild = None

        if not guild:
            print(f"[Recovery] Guild not found — cleaning session {session_id}", flush=True)
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # Use fetch_channel (API call) for accurate data at startup,
        # since cache may not have voice states populated yet.
        channel = None
        try:
            channel = await guild.fetch_channel(int(channel_id))
            print(f"[Recovery] fetch_channel({channel_id}) → {channel} (type={type(channel).__name__})", flush=True)
        except (ValueError, TypeError) as e:
            print(f"[Recovery] fetch_channel failed (ValueError/TypeError): {e}", flush=True)
            channel = None
        except Exception as e:
            print(f"[Recovery] fetch_channel failed: {e}", flush=True)
            channel = None

        if channel is None:
            print(f"[Recovery] Channel not found — cleaning session {session_id}", flush=True)
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # VC exists — check if anyone is still in it
        try:
            vc_member_ids = {str(m.id) for m in channel.members if not m.bot}
            print(f"[Recovery] channel.members → {len(channel.members)} total, {len(vc_member_ids)} non-bot: {vc_member_ids}", flush=True)
        except Exception as e:
            print(f"[Recovery] Failed to read channel.members: {e}", flush=True)
            vc_member_ids = set()

        if vc_member_ids:
            print(f"[Recovery] VC has members — resuming session {session_id}", flush=True)
            await self._resume_session(session_doc, channel, vc_member_ids, stats)
        else:
            print(f"[Recovery] VC is empty — cleaning session {session_id}", flush=True)
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            # Also delete the orphaned VC channel
            try:
                await channel.delete(reason="Recovery: empty study VC after bot restart")
                print(f"[Recovery] Deleted orphaned VC channel {channel_id}", flush=True)
            except Exception as e:
                print(f"[Recovery] Failed to delete VC channel: {e}", flush=True)

    async def _resume_session(self, session_doc: dict, channel, vc_member_ids: set, stats: dict):
        """Resume a session that still has active members."""
        session_id = session_doc.get("session_id")

        if not self.session_manager:
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # Check if already in memory
        if session_id in self.session_manager.active_sessions:
            stats["resumed"] += 1
            return

        # Recreate Session object from DB
        from library.dseshpy.session import Session
        sess = Session.from_dict(session_doc)
        sess.event_bus = self.event_bus

        # Prune members who are no longer in the VC
        stale_members = [mid for mid in list(sess.members.keys()) if mid not in vc_member_ids]
        for mid in stale_members:
            sess.members.pop(mid, None)
        sess._update_members_count()

        if not sess.members:
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # Register in SessionManager
        self.session_manager.active_sessions[session_id] = sess
        self.session_manager.channel_sessions[sess.channel_id] = session_id
        for mid in sess.members:
            self.session_manager.user_sessions[mid] = session_id

        # Restart drop routine
        if sess.drop_task is None or sess.drop_task.done():
            try:
                sess.drop_task = asyncio.create_task(sess.drop_routine(channel))
            except Exception:
                pass

        # Sync back to DB (pruned members)
        self.session_manager.sync(sess)

        stats["resumed"] += 1
        log.process(
            status_code=75,
            message="Session Resumed",
            details=f"Session {session_id} resumed with {len(sess.members)} member(s) in VC {sess.channel_id}",
        )

    async def _recover_web_session(self, session_doc: dict, stats: dict):
        """Recover or clean up a web-only session."""
        session_id = session_doc.get("session_id")
        members = session_doc.get("members", {})

        if not members:
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        # For web sessions, check if any member has a recent _seg timestamp
        # (indicates they were active recently). If the bot crashed, _seg will be
        # stale. We use a 30-minute grace window.
        now = datetime.now(timezone.utc)
        grace = timedelta(minutes=30)
        active_members = {}

        for uid, mdata in members.items():
            if not isinstance(mdata, dict):
                continue
            seg_str = mdata.get("_seg")
            if seg_str:
                try:
                    seg_time = datetime.fromisoformat(seg_str) if isinstance(seg_str, str) else seg_str
                    if seg_time.tzinfo is None:
                        seg_time = seg_time.replace(tzinfo=timezone.utc)
                    if (now - seg_time) < grace:
                        active_members[uid] = mdata
                except (ValueError, TypeError):
                    pass

        if active_members:
            # Some members were recently active — resume with those members
            await self._resume_web_session(session_doc, active_members, stats)
        else:
            # No recently active members — clean up
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)

    async def _resume_web_session(self, session_doc: dict, active_members: dict, stats: dict):
        """Resume a web session with recently active members."""
        session_id = session_doc.get("session_id")

        if not self.session_manager:
            stats["cleaned"] += 1
            await self._cleanup_session(session_doc)
            return

        if session_id in self.session_manager.active_sessions:
            stats["resumed"] += 1
            return

        from library.dseshpy.session import Session
        sess = Session.from_dict(session_doc)
        sess.event_bus = self.event_bus
        sess.members = active_members
        sess._update_members_count()

        self.session_manager.active_sessions[session_id] = sess
        self.session_manager.channel_sessions[sess.channel_id] = session_id
        for mid in sess.members:
            self.session_manager.user_sessions[mid] = session_id

        # Restart drop routine (pass None for channel since it's web-only)
        if sess.drop_task is None or sess.drop_task.done():
            try:
                sess.drop_task = asyncio.create_task(sess.drop_routine(None))
            except Exception:
                pass

        self.session_manager.sync(sess)
        stats["resumed"] += 1
        log.process(
            status_code=75,
            message="Web Session Resumed",
            details=f"Web session {session_id} resumed with {len(sess.members)} active member(s)",
        )

    # ─────────────────────── CLEANUP ───────────────────────

    async def _cleanup_session(self, session_doc: dict):
        """Formally end a session: clear user refs, remove DB doc, remove from memory."""
        session_id = session_doc.get("session_id")
        members = session_doc.get("members", {})
        print(f"[Recovery] _cleanup_session called for {session_id}", flush=True)

        # Clear current_session on all member user docs
        for uid in members:
            try:
                self.db["users"].update_one(
                    {"_id": uid, "current_session": session_id},
                    {"$unset": {"current_session": "", "webToken": ""}},
                )
                print(f"[Recovery] Cleared current_session for user {uid}", flush=True)
            except Exception as e:
                print(f"[Recovery] Failed to clear user {uid}: {e}", flush=True)

        # Remove from SessionManager memory
        if self.session_manager:
            if session_id in self.session_manager.active_sessions:
                sess = self.session_manager.active_sessions[session_id]
                if sess.drop_task and not sess.drop_task.done():
                    sess.drop_task.cancel()
                del self.session_manager.active_sessions[session_id]
                print(f"[Recovery] Removed from SessionManager active_sessions", flush=True)

            # Clean channel_sessions
            for ch, sid in list(self.session_manager.channel_sessions.items()):
                if sid == session_id:
                    del self.session_manager.channel_sessions[ch]

            # Clean user_sessions
            for uid, sid in list(self.session_manager.user_sessions.items()):
                if sid == session_id:
                    del self.session_manager.user_sessions[uid]

        # Delete from DB
        try:
            result = self.db["sessions"].delete_one({"session_id": session_id})
            print(f"[Recovery] DB delete_one result: deleted={result.deleted_count}", flush=True)
        except Exception as e:
            print(f"[Recovery] DB delete failed: {e}", flush=True)

        # Publish session_closed event
        if self.event_bus:
            try:
                await self.event_bus.publish(session_id, "session_closed", {})
                print(f"[Recovery] Published session_closed event for {session_id}", flush=True)
            except Exception as e:
                print(f"[Recovery] Failed to publish session_closed: {e}", flush=True)

    def _clean_orphaned_user_refs(self, stats: dict):
        """Remove current_session references on users that point to non-existent sessions."""
        try:
            cursor = self.db["users"].find(
                {"current_session": {"$exists": True, "$ne": None}},
                {"_id": 1, "current_session": 1},
            )
            orphaned = []
            for user_doc in cursor:
                uid = user_doc["_id"]
                sid = user_doc.get("current_session")
                if not sid:
                    continue

                exists = self.db["sessions"].find_one(
                    {"session_id": sid}, {"session_id": 1}
                )
                if not exists:
                    orphaned.append(uid)

            for uid in orphaned:
                self.db["users"].update_one(
                    {"_id": uid},
                    {"$unset": {"current_session": "", "webToken": ""}},
                )
                stats["orphan_refs_cleared"] += 1

            if orphaned:
                log.process(
                    status_code=50,
                    message="Orphans Cleaned",
                    details=f"Cleared {len(orphaned)} orphaned user.current_session reference(s)",
                )
        except Exception as e:
            log.error(
                status_code=-25,
                message="Orphan Cleanup Error",
                details=f"Error cleaning orphaned user refs: {e}",
            )

    def _clean_stale_drops(self):
        """Remove drop offers that are older than 1 hour (should have been cleaned by TTL, but just in case)."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            result = self.db["drop.offers"].delete_many(
                {"created_at": {"$lt": cutoff}}
            )
            if result.deleted_count > 0:
                log.process(
                    status_code=50,
                    message="Stale Drops Cleaned",
                    details=f"Removed {result.deleted_count} stale drop offer(s)",
                )
        except Exception:
            pass
