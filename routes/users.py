import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, Form, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import discord
import cloudinary
import cloudinary.uploader
import config
from . import verify_token, limiter
from library import is_muted

router = APIRouter()


class UserIdBody(BaseModel):
    user_id: str


class FollowBody(BaseModel):
    user_id: str


class ViewBody(BaseModel):
    user_id: str


class ListBody(BaseModel):
    user_id: str
    page: int = 1
    limit: int = 20


@router.get("/me")
async def get_current_user(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    username = payload.get("username", "Unknown")
    avatar_hash = payload.get("avatar", None)
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"

    user_data = await request.app.db["users"].find_one({"_id": user_id})
    bio = (user_data or {}).get("bio", "Hey! I'm a new user who just joined recently :)")
    profile_views = (user_data or {}).get("profile_views", 0)
    profile_pfp = (user_data or {}).get("profile_pfp", None)
    pfp = (user_data or {}).get("pfp", None)
    display_name = (user_data or {}).get("display_name") or username
    if profile_pfp:
        avatar_url = profile_pfp
    elif pfp:
        avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{user_id}/{pfp}.png"

    followers_count = len(user_data.get("followers", [])) if user_data else 0
    following_count = len(user_data.get("following", [])) if user_data else 0
    feed_count = await request.app.db["social.posts"].count_documents({"user_id": user_id})

    return {
        "ok": 1,
        "user": {
            "id": user_id,
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "bio": bio,
            "followers_count": followers_count,
            "following_count": following_count,
            "feed_count": feed_count,
            "views": profile_views,
        },
    }


@router.post("/profile")
async def get_user(request: Request, body: UserIdBody, payload: dict = Depends(verify_token)):
    user_id = body.user_id
    user_data = await request.app.db["users"].find_one({"_id": user_id})
    if not user_data:
        user_data = {}

    username = user_data.get("name", "Unknown")
    profile_pfp = user_data.get("profile_pfp", None)
    pfp = user_data.get("pfp", None)
    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    if profile_pfp:
        avatar_url = profile_pfp
    elif pfp:
        avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{user_id}/{pfp}.png"

    bio = user_data.get("bio", "Hey! I'm a new user who just joined recently :)")
    profile_views = user_data.get("profile_views", 0)
    display_name = user_data.get("display_name") or username

    followers = user_data.get("followers", [])
    following = user_data.get("following", [])
    followers_count = len(followers)
    following_count = len(following)
    feed_count = await request.app.db["social.posts"].count_documents({"user_id": user_id})

    current_user_id = payload.get("sub")
    followed_by_me = current_user_id in followers

    return {
        "ok": 1,
        "user": {
            "id": user_id,
            "username": username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "bio": bio,
            "followers_count": followers_count,
            "following_count": following_count,
            "feed_count": feed_count,
            "views": profile_views,
            "followed_by_me": followed_by_me,
        },
    }


@router.put("/me/pfp")
async def set_pfp(
    request: Request,
    payload: dict = Depends(verify_token),
    url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    user_id = payload.get("sub")

    if not url and not file:
        raise HTTPException(status_code=400, detail="Provide either a URL or an image file")

    if url:
        if not url.startswith(("https://",)):
            raise HTTPException(status_code=400, detail="URL must start with https://")
        await request.app.db["users"].update_one(
            {"_id": user_id},
            {"$set": {"profile_pfp": url}},
        )
        return {"ok": 1, "avatar_url": url}

    if file:
        contents = await file.read()
        if len(contents) > 512 * 1024:
            raise HTTPException(status_code=400, detail="File must be 512KB or smaller")
        if file.content_type and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")

        if not config.CLOUDINARY_URL:
            raise HTTPException(status_code=500, detail="Cloudinary not configured")

        cloudinary.config(secure=True)
        try:
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                contents,
                folder="candilicious/pfp",
                resource_type="image",
            )
            avatar_url = result["secure_url"]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

        await request.app.db["users"].update_one(
            {"_id": user_id},
            {"$set": {"profile_pfp": avatar_url}},
        )
        return {"ok": 1, "avatar_url": avatar_url}


@router.delete("/me/pfp")
async def remove_pfp(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$unset": {"profile_pfp": ""}},
    )
    avatar_hash = payload.get("avatar", None)
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    return {"ok": 1, "avatar_url": avatar_url}


@router.put("/me/bio")
async def set_bio(request: Request, payload: dict = Depends(verify_token), bio: str = Form(...)):
    user_id = payload.get("sub")
    if len(bio) > 500:
        raise HTTPException(status_code=400, detail="Bio must be 500 characters or fewer")
    await request.app.db["users"].update_one(
        {"_id": user_id},
        {"$set": {"bio": bio}},
    )
    return {"ok": 1, "bio": bio}


@router.post("/follow")
@limiter.limit("15/minute")
async def toggle_follow(request: Request, body: FollowBody, payload: dict = Depends(verify_token)):
    current_user_id = payload.get("sub")
    target_id = body.user_id

    if current_user_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target_user = await request.app.db["users"].find_one({"_id": target_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    followers = target_user.get("followers", [])
    is_following = current_user_id in followers

    if is_following:
        result = await request.app.db["users"].update_one(
            {"_id": target_id, "followers": current_user_id},
            {"$pull": {"followers": current_user_id}},
        )
        if result.modified_count > 0:
            await request.app.db["users"].update_one(
                {"_id": current_user_id, "following": target_id},
                {"$pull": {"following": target_id}},
            )
        return {"ok": 1, "following": False}
    else:
        result = await request.app.db["users"].update_one(
            {"_id": target_id, "followers": {"$ne": current_user_id}},
            {"$addToSet": {"followers": current_user_id}},
        )
        if result.modified_count > 0:
            await request.app.db["users"].update_one(
                {"_id": current_user_id, "following": {"$ne": target_id}},
                {"$addToSet": {"following": target_id}},
            )

        try:
            if not is_muted(target_id):
                bot = request.app.state.bot
                follower_user = await bot.fetch_user(int(current_user_id))
                target_discord = await bot.fetch_user(int(target_id))
                notify = discord.Embed(
                    title="New Follower",
                    description=f"{follower_user.mention} followed you!",
                    color=config.msgColor
                )
                notify.set_thumbnail(url=follower_user.display_avatar.url)
                notify.timestamp = datetime.now(timezone.utc)
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="View Profile",
                    url=f"{config.FRONTEND_DOMAIN}/profile?user_id={current_user_id}"
                ))
                await target_discord.send(embed=notify, view=view)
        except Exception:
            pass

        return {"ok": 1, "following": True}


@router.post("/followers")
async def get_followers(request: Request, body: ListBody, payload: dict = Depends(verify_token)):
    user_data = await request.app.db["users"].find_one({"_id": body.user_id})
    all_ids = (user_data or {}).get("followers", [])
    total = len(all_ids)
    total_pages = max(1, (total + body.limit - 1) // body.limit)
    start = (body.page - 1) * body.limit
    page_ids = all_ids[start:start + body.limit]

    users = []
    if page_ids:
        cursor = request.app.db["users"].find(
            {"_id": {"$in": page_ids}},
            {"display_name": 1, "name": 1, "profile_pfp": 1, "pfp": 1},
        )
        user_map = {}
        async for doc in cursor:
            uid = doc["_id"]
            name = doc.get("name", "Unknown")
            profile_pfp = doc.get("profile_pfp", None)
            pfp = doc.get("pfp", None)
            avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
            if profile_pfp:
                avatar_url = profile_pfp
            elif pfp:
                avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{uid}/{pfp}.png"
            user_map[uid] = {
                "id": uid,
                "username": name,
                "display_name": doc.get("display_name") or name,
                "avatar_url": avatar_url,
            }
        users = [user_map[uid] for uid in page_ids if uid in user_map]

    return {
        "ok": 1,
        "followers": users,
        "page": body.page,
        "limit": body.limit,
        "total": total,
        "total_pages": total_pages,
        "has_prev": body.page > 1,
        "has_next": body.page < total_pages,
    }


@router.post("/following")
async def get_following(request: Request, body: ListBody, payload: dict = Depends(verify_token)):
    user_data = await request.app.db["users"].find_one({"_id": body.user_id})
    all_ids = (user_data or {}).get("following", [])
    total = len(all_ids)
    total_pages = max(1, (total + body.limit - 1) // body.limit)
    start = (body.page - 1) * body.limit
    page_ids = all_ids[start:start + body.limit]

    users = []
    if page_ids:
        cursor = request.app.db["users"].find(
            {"_id": {"$in": page_ids}},
            {"display_name": 1, "name": 1, "profile_pfp": 1, "pfp": 1},
        )
        user_map = {}
        async for doc in cursor:
            uid = doc["_id"]
            name = doc.get("name", "Unknown")
            profile_pfp = doc.get("profile_pfp", None)
            pfp = doc.get("pfp", None)
            avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
            if profile_pfp:
                avatar_url = profile_pfp
            elif pfp:
                avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{uid}/{pfp}.png"
            user_map[uid] = {
                "id": uid,
                "username": name,
                "display_name": doc.get("display_name") or name,
                "avatar_url": avatar_url,
            }
        users = [user_map[uid] for uid in page_ids if uid in user_map]

    return {
        "ok": 1,
        "following": users,
        "page": body.page,
        "limit": body.limit,
        "total": total,
        "total_pages": total_pages,
        "has_prev": body.page > 1,
        "has_next": body.page < total_pages,
    }


@router.post("/view")
@limiter.limit("60/minute")
async def increment_view(request: Request, body: ViewBody, payload: dict = Depends(verify_token)):
    current_user_id = payload.get("sub")
    target_id = body.user_id
    if current_user_id != target_id:
        await request.app.db["users"].update_one(
            {"_id": target_id},
            {"$inc": {"profile_views": 1}},
        )
    updated = await request.app.db["users"].find_one(
        {"_id": target_id},
        {"profile_views": 1},
    )
    return {"ok": 1, "views": (updated or {}).get("profile_views", 0)}
