import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from . import verify_token

router = APIRouter()


class JoinRequest(BaseModel):
    initial_time: dict | None = None


def _build_avatar_url(user_id: str, user_data: dict) -> str:
    profile_pfp = user_data.get("profile_pfp")
    if profile_pfp:
        return profile_pfp
    pfp = user_data.get("pfp")
    if pfp:
        if pfp.startswith(("https://", "data:")):
            return pfp
        return f"https://cdn.discordapp.com/avatars/{user_id}/{pfp}.png"
    return f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"


async def _enrich_members(request: Request, session_doc: dict) -> list:
    raw_members = session_doc.get("members", {})
    if not raw_members:
        return []

    member_ids = list(raw_members.keys())
    if not member_ids:
        return []

    user_cursor = request.app.db["users"].find(
        {"_id": {"$in": member_ids}},
        {"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1},
    )

    user_map = {}
    async for doc in user_cursor:
        uid = doc["_id"]
        username = doc.get("name", "Unknown")
        display_name = doc.get("display_name") or username
        avatar_url = _build_avatar_url(uid, doc)
        user_map[uid] = {
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
        }

    owner_id = session_doc.get("owner_id")
    members = []
    for uid, mdata in raw_members.items():
        if not isinstance(mdata, dict):
            continue
        uinfo = user_map.get(uid, {
            "username": "Unknown",
            "display_name": "Unknown",
            "avatar_url": f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png",
        })
        members.append({
            "user_id": uid,
            "username": uinfo["username"],
            "display_name": uinfo["display_name"],
            "avatar_url": uinfo["avatar_url"],
            "activity": mdata.get("last_activity", "noact"),
            "net_time": mdata.get("net_time", {"cam": 0, "ss": 0, "noact": 0, "total": 0}),
            "is_owner": uid == owner_id,
            "is_web_user": mdata.get("is_web_user", False),
        })

    members.sort(key=lambda m: (not m["is_owner"], m["user_id"]))
    return members



def _session_response(session_doc: dict, members: list) -> dict:
    return {
        "ok": 1,
        "session": {
            "session_id": session_doc.get("session_id"),
            "owner_id": session_doc.get("owner_id"),
            "guild_id": session_doc.get("guild_id"),
            "channel_id": session_doc.get("channel_id"),
            "session_type": session_doc.get("session_type", "*"),
            "vc_level": session_doc.get("vc_level", 1),
            "vc_xp": session_doc.get("vc_xp", 0),
            "members_count": session_doc.get("members_count", {}),
            "members": members,
        },
    }


async def _remove_user_from_session(request: Request, user_id: str, session_doc: dict, event_bus=None):
    members_raw = session_doc.get("members", {})
    if user_id not in members_raw:
        return

    session_id = session_doc.get("session_id")

    user_act = members_raw[user_id].get("last_activity", "noact") if isinstance(members_raw[user_id], dict) else "noact"
    inc_fields = {"members_count.total": -1}
    if user_act == "cam+ss":
        inc_fields["members_count.cam"] = -1
        inc_fields["members_count.ss"] = -1
    elif user_act in ("cam", "ss", "noact"):
        inc_fields[f"members_count.{user_act}"] = -1

    await request.app.db["sessions"].update_one(
        {"session_id": session_id},
        {
            "$unset": {f"members.{user_id}": ""},
            "$inc": inc_fields,
        },
    )

    owner_id = session_doc.get("owner_id")
    new_owner_id = owner_id
    remaining = [mid for mid in members_raw if mid != user_id]

    if user_id == owner_id:
        new_owner_id = remaining[0] if remaining else None

    updated_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not updated_doc:
        sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
        if sm and session_id in sm.active_sessions:
            sm._cleanup_session(sm.active_sessions[session_id])
        return

    total = updated_doc.get("members_count", {}).get("total", 0)
    if total <= 0:
        sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
        if sm and session_id in sm.active_sessions:
            sm._cleanup_session(sm.active_sessions[session_id])
        else:
            await request.app.db["users"].update_one(
                {"_id": user_id},
                {"$unset": {"current_session": "", "webToken": ""}},
            )
            await request.app.db["sessions"].delete_one({"session_id": session_id})
            if sm:
                for uid, sid in list(sm.user_sessions.items()):
                    if sid == session_id:
                        del sm.user_sessions[uid]
                for ch, sid in list(sm.channel_sessions.items()):
                    if sid == session_id:
                        del sm.channel_sessions[ch]
        if event_bus:
            await event_bus.publish(session_id, "session_closed", {})
        return

    if new_owner_id and new_owner_id != owner_id:
        await request.app.db["sessions"].update_one(
            {"session_id": session_id},
            {"$set": {"owner_id": new_owner_id}},
        )

    has_discord = any(
        not m.get("is_web_user", False)
        for m in updated_doc.get("members", {}).values()
        if isinstance(m, dict)
    )
    channel_id = updated_doc.get("channel_id", "")
    if not channel_id.startswith("w") and not has_discord and remaining:
        await request.app.db["sessions"].update_one(
            {"session_id": session_id},
            {"$set": {
                "channel_id": f"w{new_owner_id}",
                "guild_id": "web",
            }},
        )

    if event_bus:
        await event_bus.publish(session_id, "member_leave", {"user_id": user_id})
        if new_owner_id != owner_id:
            await event_bus.publish(session_id, "owner_change", {"owner_id": new_owner_id})

    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$unset": {"current_session": ""}},
    )

    sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
    if sm and session_id in sm.active_sessions:
        sess = sm.active_sessions[session_id]
        sess.members.pop(user_id, None)
        sess.owner_id = new_owner_id
        old_ch = sess.channel_id
        new_ch = updated_doc.get("channel_id", sess.channel_id)
        sess.channel_id = new_ch
        sess.guild_id = updated_doc.get("guild_id", sess.guild_id)
        sess._update_members_count()
        sm.user_sessions.pop(user_id, None)
        if new_ch != old_ch:
            sm.channel_sessions.pop(old_ch, None)
            sm.channel_sessions[new_ch] = session_id


@router.get("/{session_id}")
async def get_session_state(
    request: Request,
    session_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    session_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Session not found")

    members_raw = session_doc.get("members", {})
    is_member = user_id in members_raw
    guild_id = session_doc.get("guild_id", "")

    if not is_member and guild_id != "web":
        in_guild = payload.get("in_guild", False)
        if not in_guild:
            raise HTTPException(status_code=403, detail="You must be in the guild to view this session")

    members = await _enrich_members(request, session_doc)
    return _session_response(session_doc, members)


@router.post("/{session_id}/join")
async def join_session(
    request: Request,
    session_id: str,
    body: JoinRequest = JoinRequest(),
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    existing_session = await request.app.db["sessions"].find_one(
        {"members": {f"$exists": True}, f"members.{user_id}": {"$exists": True}},
    )
    if existing_session:
        existing_sid = existing_session.get("session_id")
        if existing_sid != session_id:
            await _remove_user_from_session(request, user_id, existing_session, getattr(request.app.state, "event_bus", None))

    session_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Session not found. Make sure someone is in the voice channel.")

    members_raw = session_doc.get("members", {})
    if user_id in members_raw:
        members = await _enrich_members(request, session_doc)
        return _session_response(session_doc, members)

    guild_id = session_doc.get("guild_id", "")
    if guild_id != "web":
        bot = request.app.state.bot
        guild = bot.get_guild(int(guild_id)) if guild_id else None
        if guild:
            member = guild.get_member(int(user_id))
            if not member and not payload.get("in_guild", False):
                raise HTTPException(status_code=403, detail="You must be in the Discord guild to join this session")
        else:
            if not payload.get("in_guild", False):
                raise HTTPException(status_code=403, detail="You must be in the Discord guild to join this session")

    now = datetime.now(timezone.utc)

    initial_time = body.initial_time or {"cam": 0, "ss": 0, "noact": 0, "total": 0}

    await request.app.db["sessions"].update_one(
        {"session_id": session_id},
        {
            "$set": {
                f"members.{user_id}": {
                    "net_time": initial_time,
                    "last_activity": "noact",
                    "_seg": now.isoformat(),
                    "is_web_user": True,
                },
            },
            "$inc": {"members_count.total": 1, "members_count.noact": 1},
        },
    )

    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"current_session": session_id}},
    )

    user_data = await request.app.db["users"].find_one(
        {"_id": user_id},
        {"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1},
    )
    username = "Unknown"
    display_name = "Unknown"
    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    if user_data:
        username = user_data.get("name", "Unknown")
        display_name = user_data.get("display_name") or username
        avatar_url = _build_avatar_url(user_id, user_data)

    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus:
        await event_bus.publish(session_id, "member_join", {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "activity": "noact",
            "is_web_user": True,
        })

    sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
    if sm and session_id in sm.active_sessions:
        sess = sm.active_sessions[session_id]
        sess.members[user_id] = {
            "net_time": initial_time,
            "last_activity": "noact",
            "_seg": now.isoformat(),
            "is_web_user": True,
        }
        sess._update_members_count()
        sm.user_sessions[user_id] = session_id

    updated_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
    members = await _enrich_members(request, updated_doc)
    return _session_response(updated_doc, members)


@router.post("/{session_id}/leave")
async def leave_session(
    request: Request,
    session_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    session_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Session not found")

    members_raw = session_doc.get("members", {})
    if user_id not in members_raw:
        raise HTTPException(status_code=400, detail="You are not in this session")

    member_data = members_raw[user_id]
    is_web_user = isinstance(member_data, dict) and member_data.get("is_web_user", False)

    if not is_web_user:
        bot = getattr(request.app.state, "bot", None)
        guild_id = session_doc.get("guild_id")
        channel_id = session_doc.get("channel_id")
        if bot and guild_id and not channel_id.startswith("w"):
            try:
                guild = bot.get_guild(int(guild_id))
                if guild:
                    member = guild.get_member(int(user_id))
                    if member and member.voice:
                        await member.move_to(None)
            except Exception:
                pass

    event_bus = getattr(request.app.state, "event_bus", None)
    await _remove_user_from_session(request, user_id, session_doc, event_bus)
    return {"ok": 1}


@router.post("/create")
async def create_web_session(
    request: Request,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    existing = await request.app.db["sessions"].find_one(
        {"members": {f"$exists": True}, f"members.{user_id}": {"$exists": True}},
    )
    if existing:
        existing_sid = existing.get("session_id") or existing.get("_id")
        members_raw = existing.get("members", {})
        if len(members_raw) == 1:
            sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
            if sm and existing_sid in sm.active_sessions:
                sm._cleanup_session(sm.active_sessions[existing_sid])
            else:
                await request.app.db["users"].update_one(
                    {"_id": user_id},
                    {"$unset": {"current_session": "", "webToken": ""}},
                )
                await request.app.db["sessions"].delete_one({"session_id": existing_sid})
                if sm:
                    for uid, sid in list(sm.user_sessions.items()):
                        if sid == existing_sid:
                            del sm.user_sessions[uid]
                    for ch, sid in list(sm.channel_sessions.items()):
                        if sid == existing_sid:
                            del sm.channel_sessions[ch]
            event_bus = getattr(request.app.state, "event_bus", None)
            if event_bus:
                await event_bus.publish(existing_sid, "session_closed", {})
        else:
            await _remove_user_from_session(request, user_id, existing, getattr(request.app.state, "event_bus", None))

    from library.dseshpy.session import generate_session_id
    channel_id = f"w{user_id}"
    session_id = generate_session_id(channel_id)
    now = datetime.now(timezone.utc)

    session_doc = {
        "session_id": session_id,
        "owner_id": user_id,
        "guild_id": "web",
        "channel_id": channel_id,
        "members": {
            user_id: {
                "net_time": {"cam": 0, "ss": 0, "noact": 0, "total": 0},
                "last_activity": "noact",
                "_seg": now.isoformat(),
                "is_web_user": True,
            }
        },
        "members_count": {"total": 1, "noact": 1, "ss": 0, "cam": 0},
        "vc_level": 1,
        "vc_xp": 0,
        "session_type": "*",
    }

    await request.app.db["sessions"].insert_one(session_doc)
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"current_session": session_id}},
    )

    import config as _cfg
    sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
    if sm:
        from library.dseshpy.session import Session
        sess_obj = Session(
            session_id=session_id,
            owner_id=user_id,
            guild_id="web",
            channel_id=channel_id,
            members={
                user_id: {
                    "net_time": {"cam": 0, "ss": 0, "noact": 0, "total": 0},
                    "last_activity": "noact",
                    "_seg": now.isoformat(),
                    "is_web_user": True,
                }
            },
            members_count={"total": 1, "noact": 1, "ss": 0, "cam": 0},
            vc_level=1,
            vc_xp=0,
            routine_callback_mean_time=int(_cfg.DROP_MEAN_TIME),
            session_type="*",
        )
        sess_obj.event_bus = getattr(request.app.state, "event_bus", None)
        sm.active_sessions[session_id] = sess_obj
        sm.channel_sessions[channel_id] = session_id
        sm.user_sessions[user_id] = session_id
        import asyncio as _asyncio
        sess_obj.drop_task = _asyncio.create_task(sess_obj.drop_routine(None))
        print(f"[Drop] Web session {session_id}: registered in SessionManager, drop_routine started (mean_time={int(_cfg.DROP_MEAN_TIME)}min)", flush=True)
    else:
        print(f"[Drop] Web session {session_id}: WARNING — SessionManager not found on bot, drops will NOT fire", flush=True)

    user_data = await request.app.db["users"].find_one(
        {"_id": user_id},
        {"name": 1, "display_name": 1, "pfp": 1, "profile_pfp": 1},
    )
    username = "Unknown"
    display_name = "Unknown"
    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    if user_data:
        username = user_data.get("name", "Unknown")
        display_name = user_data.get("display_name") or username
        avatar_url = _build_avatar_url(user_id, user_data)

    members = await _enrich_members(request, session_doc)
    return _session_response(session_doc, members)


@router.get("/{session_id}/stream")
async def stream_session_events(
    request: Request,
    session_id: str,
    payload: dict = Depends(verify_token),
):

    event_bus = getattr(request.app.state, "event_bus", None)
    if not event_bus:
        raise HTTPException(status_code=503, detail="Event bus not available")

    sm = getattr(getattr(request.app.state, "bot", None), "session_manager", None)
    if sm and session_id not in sm.active_sessions:
        session_doc = await request.app.db["sessions"].find_one({"session_id": session_id})
        if session_doc:
            from library.dseshpy.session import Session
            sess_obj = Session.from_dict(session_doc)
            sess_obj.event_bus = event_bus
            sm.active_sessions[session_id] = sess_obj
            sm.channel_sessions[sess_obj.channel_id] = session_id
            for uid in sess_obj.members:
                sm.user_sessions[uid] = session_id
            sess_obj.drop_task = asyncio.create_task(sess_obj.drop_routine(None))
            print(f"[Drop] SSE reconnect: re-created session {session_id} in SessionManager, drop_routine started", flush=True)

    queue = await event_bus.subscribe(session_id)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected', 'data': {'session_id': session_id}})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}})}\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe(session_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
