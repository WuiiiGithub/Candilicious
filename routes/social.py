import uuid
import asyncio
import hashlib
import time
from fastapi import APIRouter, Request, Depends, HTTPException, Query, UploadFile, File, Form
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from . import verify_token, optional_token, limiter
from cogs.social import notify_followers_of_post
import config

router = APIRouter()


class CreatePostRequest(BaseModel):
    title: str
    caption: str
    link: str
    thumbnail_url: Optional[str] = None


@router.get("/posts")
async def get_posts(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    payload: dict = Depends(verify_token),
):
    current_user_id = payload.get("sub")
    filter_query = {}
    if user_id:
        filter_query["user_id"] = user_id

    following_list = []
    if not user_id and current_user_id:
        me = await request.app.db["users"].find_one({"_id": current_user_id})
        following_list = me.get("following", []) if me else []

    if not user_id and following_list:
        pipeline = [
            {"$addFields": {"_followed": {"$in": ["$user_id", following_list]}}},
            {"$sort": {"_followed": -1, "created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
        ]
        docs = await request.app.db["social.posts"].aggregate(pipeline).to_list(length=limit)
    else:
        cursor = (
            request.app.db["social.posts"]
            .find(filter_query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        docs = [doc async for doc in cursor]

    user_cache: dict[str, dict] = {}
    posts = []
    for doc in docs:
        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        doc["is_custom"] = bool(doc.get("custom_id"))
        doc["liked_by_me"] = current_user_id in doc.get("likes", [])
        doc["disliked_by_me"] = current_user_id in doc.get("dislikes", [])
        doc.pop("likes", None)
        doc.pop("dislikes", None)
        doc.pop("content", None)

        uid = doc.get("user_id", "")
        if uid and uid not in user_cache:
            u = await request.app.db["users"].find_one({"_id": uid})
            if u:
                name = u.get("name", "Unknown")
                pfp = u.get("profile_pfp") or u.get("pfp")
                avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
                if pfp:
                    avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{uid}/{pfp}.png"
                user_cache[uid] = {
                    "user_id": uid,
                    "display_name": u.get("display_name") or name,
                    "avatar_url": avatar_url,
                    "username": name,
                }
            else:
                user_cache[uid] = {"user_id": uid, "display_name": "Unknown", "avatar_url": f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png", "username": "Unknown"}

        doc["author"] = user_cache.get(uid, {"display_name": "Unknown", "avatar_url": f"https://cdn.discordapp.com/embed/avatars/0.png"})
        posts.append(doc)

    return {"ok": 1, "posts": posts}


@router.get("/posts/{post_id}")
async def get_post(
    request: Request,
    post_id: str,
    payload: dict = Depends(optional_token),
):
    current_user_id = payload.get("sub") if payload else None
    doc = None
    custom_doc = None

    try:
        doc = await request.app.db["social.posts"].find_one({"_id": ObjectId(post_id)})
    except Exception:
        pass

    if doc:
        custom_id = doc.get("custom_id")
        if custom_id:
            custom_doc = await request.app.db["posts.custom"].find_one({"_id": custom_id})
    else:
        custom_doc = await request.app.db["posts.custom"].find_one({"_id": post_id})
        if custom_doc:
            card = await request.app.db["social.posts"].find_one({"custom_id": post_id})
            if card:
                doc = card

    if not doc and not custom_doc:
        raise HTTPException(status_code=404, detail="Post not found")

    is_custom = custom_doc is not None

    if doc:
        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        doc["liked_by_me"] = current_user_id in doc.get("likes", [])
        doc["disliked_by_me"] = current_user_id in doc.get("dislikes", [])
        doc.pop("likes", None)
        doc.pop("dislikes", None)
        author_id = doc.get("user_id", "")
        if custom_doc:
            for key in ("writing_time", "ip"):
                if key in custom_doc:
                    doc[key] = custom_doc[key]
    elif custom_doc:
        custom_doc["_id"] = str(custom_doc["_id"])
        if isinstance(custom_doc.get("created_at"), datetime):
            custom_doc["created_at"] = custom_doc["created_at"].isoformat()
        custom_doc["liked_by_me"] = current_user_id in custom_doc.get("likes", [])
        custom_doc["disliked_by_me"] = current_user_id in custom_doc.get("dislikes", [])
        custom_doc.pop("likes", None)
        custom_doc.pop("dislikes", None)
        author_id = custom_doc.get("user_id", "")
        doc = custom_doc

    author_data = await request.app.db["users"].find_one({"_id": author_id}) or {}
    username = author_data.get("name", "Unknown")
    display_name = author_data.get("display_name") or username
    profile_pfp = author_data.get("profile_pfp")
    pfp = author_data.get("pfp")
    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(author_id) % 5}.png"
    if profile_pfp:
        avatar_url = profile_pfp
    elif pfp:
        avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{author_id}/{pfp}.png"

    doc["author"] = {
        "user_id": author_id,
        "display_name": display_name,
        "avatar_url": avatar_url,
    }
    doc["is_custom"] = is_custom

    return {"ok": 1, "post": doc}


@router.post("/posts")
@limiter.limit("5/minute")
async def create_post(
    request: Request,
    body: CreatePostRequest,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    if len(body.title) > 200:
        raise HTTPException(status_code=400, detail="Title must be 200 characters or fewer")
    if len(body.caption) > 2000:
        raise HTTPException(status_code=400, detail="Caption must be 2000 characters or fewer")
    if not body.link.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link must be a valid URL")

    post = {
        "user_id": user_id,
        "title": body.title,
        "caption": body.caption,
        "link": body.link,
        "thumbnail_url": body.thumbnail_url,
        "likes": [],
        "like_count": 0,
        "dislikes": [],
        "dislike_count": 0,
        "views": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await request.app.db["social.posts"].insert_one(post)

    post["_id"] = str(result.inserted_id)
    post["created_at"] = post["created_at"].isoformat()

    bot = request.app.state.bot
    asyncio.create_task(notify_followers_of_post(
        bot=bot,
        author_id=user_id,
        post_title=body.title,
        post_caption=body.caption,
        post_link=body.link,
        thumbnail_url=body.thumbnail_url,
        post_url=f"{config.FRONTEND_DOMAIN}/social/post/{post['_id']}",
    ))

    return {"ok": 1, "post": post}


class UpdatePostRequest(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    thumbnail_url: Optional[str] = None


@router.put("/posts/{post_id}")
async def update_post(
    request: Request,
    post_id: str,
    body: UpdatePostRequest,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    try:
        post = await request.app.db["social.posts"].find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own posts")

    update_fields: dict = {}
    if body.title is not None:
        if len(body.title) > 200:
            raise HTTPException(status_code=400, detail="Title must be 200 characters or fewer")
        update_fields["title"] = body.title
    if body.caption is not None:
        if len(body.caption) > 2000:
            raise HTTPException(status_code=400, detail="Caption must be 2000 characters or fewer")
        update_fields["caption"] = body.caption
    if body.thumbnail_url is not None:
        update_fields["thumbnail_url"] = body.thumbnail_url

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    await request.app.db["social.posts"].update_one(
        {"_id": ObjectId(post_id)},
        {"$set": update_fields},
    )

    updated = await request.app.db["social.posts"].find_one({"_id": ObjectId(post_id)})

    return {"ok": 1, "post": _serialize_post(updated)}


@router.delete("/posts/{post_id}")
async def delete_post(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    try:
        post = await request.app.db["social.posts"].find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own posts")

    await request.app.db["social.posts"].delete_one({"_id": ObjectId(post_id)})

    return {"ok": 1}


def _serialize_post(post: dict) -> dict:
    post["_id"] = str(post["_id"])
    if isinstance(post.get("created_at"), datetime):
        post["created_at"] = post["created_at"].isoformat()
    return post


@router.post("/posts/{post_id}/like")
@limiter.limit("30/minute")
async def toggle_like(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")
    collection = None
    oid = None

    try:
        oid = ObjectId(post_id)
    except Exception:
        pass

    if oid:
        post = await request.app.db["social.posts"].find_one({"_id": oid})
        if post:
            collection = "social.posts"

    if not collection:
        post = await request.app.db["posts.custom"].find_one({"_id": post_id})
        if post:
            collection = "posts.custom"

    if not post or not collection:
        raise HTTPException(status_code=404, detail="Post not found")

    find_id = oid if collection == "social.posts" else post_id
    likes = post.get("likes", [])
    dislikes = post.get("dislikes", [])

    if user_id in likes:
        result = await request.app.db[collection].update_one(
            {"_id": find_id, "likes": user_id},
            {"$pull": {"likes": user_id}, "$inc": {"like_count": -1}},
        )
        liked = result.modified_count > 0
    else:
        update: dict = {"$addToSet": {"likes": user_id}, "$inc": {"like_count": 1}}
        if user_id in dislikes:
            update["$pull"] = {"dislikes": user_id}
            update["$inc"]["dislike_count"] = -1
        result = await request.app.db[collection].update_one(
            {"_id": find_id, "likes": {"$ne": user_id}},
            update,
        )
        liked = result.modified_count > 0

    updated = await request.app.db[collection].find_one(
        {"_id": find_id},
        {"like_count": 1, "dislike_count": 1},
    )

    return {
        "ok": 1,
        "liked": liked,
        "like_count": updated.get("like_count", 0) if updated else 0,
        "dislike_count": updated.get("dislike_count", 0) if updated else 0,
    }


@router.post("/posts/{post_id}/dislike")
@limiter.limit("30/minute")
async def toggle_dislike(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")
    collection = None
    oid = None

    try:
        oid = ObjectId(post_id)
    except Exception:
        pass

    if oid:
        post = await request.app.db["social.posts"].find_one({"_id": oid})
        if post:
            collection = "social.posts"

    if not collection:
        post = await request.app.db["posts.custom"].find_one({"_id": post_id})
        if post:
            collection = "posts.custom"

    if not post or not collection:
        raise HTTPException(status_code=404, detail="Post not found")

    find_id = oid if collection == "social.posts" else post_id
    dislikes = post.get("dislikes", [])
    likes = post.get("likes", [])

    if user_id in dislikes:
        result = await request.app.db[collection].update_one(
            {"_id": find_id, "dislikes": user_id},
            {"$pull": {"dislikes": user_id}, "$inc": {"dislike_count": -1}},
        )
        disliked = result.modified_count > 0
    else:
        update: dict = {"$addToSet": {"dislikes": user_id}, "$inc": {"dislike_count": 1}}
        if user_id in likes:
            update["$pull"] = {"likes": user_id}
            update["$inc"]["like_count"] = -1
        result = await request.app.db[collection].update_one(
            {"_id": find_id, "dislikes": {"$ne": user_id}},
            update,
        )
        disliked = result.modified_count > 0

    updated = await request.app.db[collection].find_one(
        {"_id": find_id},
        {"dislike_count": 1, "like_count": 1},
    )

    return {
        "ok": 1,
        "disliked": disliked,
        "dislike_count": updated.get("dislike_count", 0) if updated else 0,
        "like_count": updated.get("like_count", 0) if updated else 0,
    }


@router.post("/posts/{post_id}/view")
@limiter.limit("60/minute")
async def increment_post_view(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    oid = None
    try:
        oid = ObjectId(post_id)
    except Exception:
        pass

    if oid:
        result = await request.app.db["social.posts"].update_one(
            {"_id": oid},
            {"$inc": {"views": 1}},
        )
        if result.matched_count > 0:
            updated = await request.app.db["social.posts"].find_one(
                {"_id": oid},
                {"views": 1},
            )
            return {"ok": 1, "views": updated.get("views", 1) if updated else 1}

    result = await request.app.db["posts.custom"].update_one(
        {"_id": post_id},
        {"$inc": {"views": 1}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")

    await request.app.db["social.posts"].update_one(
        {"custom_id": post_id},
        {"$inc": {"views": 1}},
    )

    updated_social = await request.app.db["social.posts"].find_one(
        {"custom_id": post_id},
        {"views": 1},
    )
    views = updated_social.get("views", 1) if updated_social else 1
    return {"ok": 1, "views": views}


class CreateCustomPostRequest(BaseModel):
    title: str
    description: str
    content: str
    thumbnail_url: Optional[str] = None
    writing_time: Optional[int] = None


class UpdateCustomPostRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    thumbnail_url: Optional[str] = None


@router.put("/posts/custom/{post_id}")
async def update_custom_post(
    request: Request,
    post_id: str,
    body: UpdateCustomPostRequest,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    custom_post = await request.app.db["posts.custom"].find_one({"_id": post_id})
    if not custom_post:
        raise HTTPException(status_code=404, detail="Post not found")

    if custom_post.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own posts")

    update_fields: dict = {}
    social_fields: dict = {}

    if body.title is not None:
        if len(body.title) > 200:
            raise HTTPException(status_code=400, detail="Title must be 200 characters or fewer")
        update_fields["title"] = body.title
        social_fields["title"] = body.title
    if body.description is not None:
        if len(body.description) > 2000:
            raise HTTPException(status_code=400, detail="Description must be 2000 characters or fewer")
        update_fields["description"] = body.description
        social_fields["caption"] = body.description
    if body.content is not None:
        update_fields["content"] = body.content
        social_fields["content"] = body.content
    if body.thumbnail_url is not None:
        update_fields["thumbnail"] = body.thumbnail_url
        social_fields["thumbnail_url"] = body.thumbnail_url

    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    await request.app.db["posts.custom"].update_one(
        {"_id": post_id},
        {"$set": update_fields},
    )

    if social_fields:
        await request.app.db["social.posts"].update_one(
            {"custom_id": post_id},
            {"$set": social_fields},
        )

    updated = await request.app.db["posts.custom"].find_one({"_id": post_id})

    return {"ok": 1, "post": _serialize_post(updated)}


@router.post("/posts/custom/thumbnail")
async def upload_custom_thumbnail(
    request: Request,
    payload: dict = Depends(verify_token),
    file: UploadFile = File(...),
):
    contents = await file.read()
    if len(contents) > 512 * 1024:
        raise HTTPException(status_code=400, detail="File must be 512KB or smaller")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    if not config.CLOUDINARY_URL:
        raise HTTPException(status_code=500, detail="Cloudinary not configured")

    import cloudinary
    import cloudinary.uploader

    cloudinary.config()
    try:
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            contents,
            folder="candilicious/thumbnails",
            resource_type="image",
        )
        return {"ok": 1, "thumbnail_url": result["secure_url"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/posts/custom")
@limiter.limit("5/minute")
async def create_custom_post(
    request: Request,
    body: CreateCustomPostRequest,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    if len(body.title) > 200:
        raise HTTPException(status_code=400, detail="Title must be 200 characters or fewer")
    if len(body.description) > 2000:
        raise HTTPException(status_code=400, detail="Description must be 2000 characters or fewer")

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)

    post_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    custom_post = {
        "_id": post_id,
        "user_id": user_id,
        "title": body.title,
        "description": body.description,
        "thumbnail": body.thumbnail_url,
        "writing_time": body.writing_time,
        "ip": ip,
        "created_at": now,
    }
    await request.app.db["posts.custom"].insert_one(custom_post)

    site_link = f"{config.FRONTEND_DOMAIN}/posts?id={post_id}"

    card = {
        "user_id": user_id,
        "title": body.title,
        "caption": body.description,
        "link": site_link,
        "thumbnail_url": body.thumbnail_url,
        "content": body.content,
        "custom_id": post_id,
        "likes": [],
        "like_count": 0,
        "dislikes": [],
        "dislike_count": 0,
        "views": 0,
        "created_at": now,
    }
    result = await request.app.db["social.posts"].insert_one(card)

    social_post_id = str(result.inserted_id)
    bot = request.app.state.bot
    asyncio.create_task(notify_followers_of_post(
        bot=bot,
        author_id=user_id,
        post_title=body.title,
        post_caption=body.description,
        post_link=site_link,
        thumbnail_url=body.thumbnail_url,
        post_url=f"{config.FRONTEND_DOMAIN}/social/post/{social_post_id}",
    ))

    return {"ok": 1, "post": {"_id": social_post_id, "custom_id": post_id, "created_at": now.isoformat()}}


@router.get("/posts/custom")
async def get_custom_posts(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    payload: dict = Depends(verify_token),
):
    filter_query = {}
    if user_id:
        filter_query["user_id"] = user_id

    cursor = (
        request.app.db["posts.custom"]
        .find(filter_query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    current_user_id = payload.get("sub")
    posts = []
    user_cache: dict[str, dict] = {}

    async for doc in cursor:
        uid = doc.get("user_id", "")
        if uid not in user_cache:
            user_data = await request.app.db["users"].find_one({"_id": uid})
            if user_data:
                username = user_data.get("name", "Unknown")
                profile_pfp = user_data.get("profile_pfp", None)
                pfp = user_data.get("pfp", None)
                avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
                if profile_pfp:
                    avatar_url = profile_pfp
                elif pfp:
                    avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{uid}/{pfp}.png"
                user_cache[uid] = {
                    "id": uid,
                    "username": username,
                    "display_name": user_data.get("display_name") or username,
                    "avatar_url": avatar_url,
                }
            else:
                user_cache[uid] = {"id": uid, "username": "Unknown", "display_name": "Unknown", "avatar_url": f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"}

        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        doc["liked_by_me"] = current_user_id in doc.get("likes", [])
        doc["user"] = user_cache.get(uid, {})
        doc.pop("likes", None)
        doc.pop("content", None)
        posts.append(doc)

    return {"ok": 1, "posts": posts}


@router.get("/posts/custom/{post_id}")
async def get_custom_post(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    doc = await request.app.db["posts.custom"].find_one({"_id": post_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Post not found")

    card = await request.app.db["social.posts"].find_one({"custom_id": post_id})
    if card:
        doc["link"] = card.get("link")

    current_user_id = payload.get("sub")
    uid = doc.get("user_id", "")

    user_data = await request.app.db["users"].find_one({"_id": uid})
    user_info = {"id": uid, "username": "Unknown", "display_name": "Unknown", "avatar_url": f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"}
    if user_data:
        username = user_data.get("name", "Unknown")
        profile_pfp = user_data.get("profile_pfp", None)
        pfp = user_data.get("pfp", None)
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
        if profile_pfp:
            avatar_url = profile_pfp
        elif pfp:
            avatar_url = pfp if pfp.startswith(("https://", "data:")) else f"https://cdn.discordapp.com/avatars/{uid}/{pfp}.png"
        user_info = {"id": uid, "username": username, "display_name": user_data.get("display_name") or username, "avatar_url": avatar_url}

    doc["_id"] = str(doc["_id"])
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    doc["liked_by_me"] = current_user_id in doc.get("likes", [])
    doc["user"] = user_info
    doc.pop("likes", None)

    return {"ok": 1, "post": doc}


@router.post("/posts/custom/{post_id}/like")
async def toggle_custom_like(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    user_id = payload.get("sub")

    post = await request.app.db["posts.custom"].find_one({"_id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    likes = post.get("likes", [])
    if user_id in likes:
        result = await request.app.db["posts.custom"].update_one(
            {"_id": post_id, "likes": user_id},
            {"$pull": {"likes": user_id}, "$inc": {"like_count": -1}},
        )
        liked = result.modified_count > 0
    else:
        result = await request.app.db["posts.custom"].update_one(
            {"_id": post_id, "likes": {"$ne": user_id}},
            {"$addToSet": {"likes": user_id}, "$inc": {"like_count": 1}},
        )
        liked = result.modified_count > 0

    updated = await request.app.db["posts.custom"].find_one(
        {"_id": post_id},
        {"like_count": 1, "likes": 1},
    )

    return {
        "ok": 1,
        "liked": liked,
        "like_count": updated.get("like_count", 0) if updated else 0,
    }


@router.post("/posts/custom/{post_id}/view")
async def increment_custom_post_view(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    result = await request.app.db["posts.custom"].update_one(
        {"_id": post_id},
        {"$inc": {"views": 1}},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"ok": 1}
