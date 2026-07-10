import base64
import uuid
from fastapi import APIRouter, Request, Depends, HTTPException, Query, UploadFile, File, Form
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from . import verify_token

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
    filter_query = {}
    if user_id:
        filter_query["user_id"] = user_id

    cursor = (
        request.app.db["social.posts"]
        .find(filter_query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    current_user_id = payload.get("sub")
    posts = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        doc["liked_by_me"] = current_user_id in doc.get("likes", [])
        doc["disliked_by_me"] = current_user_id in doc.get("dislikes", [])
        doc.pop("likes", None)
        doc.pop("dislikes", None)
        posts.append(doc)

    return {"ok": 1, "posts": posts}


@router.get("/posts/{post_id}")
async def get_post(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    try:
        doc = await request.app.db["social.posts"].find_one({"_id": ObjectId(post_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")

    if not doc:
        raise HTTPException(status_code=404, detail="Post not found")

    current_user_id = payload.get("sub")
    doc["_id"] = str(doc["_id"])
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    doc["liked_by_me"] = current_user_id in doc.get("likes", [])
    doc["disliked_by_me"] = current_user_id in doc.get("dislikes", [])
    doc.pop("likes", None)
    doc.pop("dislikes", None)

    return {"ok": 1, "post": doc}


@router.post("/posts")
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

    return {"ok": 1, "post": post}


@router.post("/posts/{post_id}/like")
async def toggle_like(
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

    likes = post.get("likes", [])
    if user_id in likes:
        await request.app.db["social.posts"].update_one(
            {"_id": ObjectId(post_id)},
            {"$pull": {"likes": user_id}, "$inc": {"like_count": -1}},
        )
        liked = False
    else:
        await request.app.db["social.posts"].update_one(
            {"_id": ObjectId(post_id)},
            {"$push": {"likes": user_id}, "$inc": {"like_count": 1}},
        )
        liked = True

    updated = await request.app.db["social.posts"].find_one(
        {"_id": ObjectId(post_id)},
        {"like_count": 1, "likes": 1},
    )

    return {
        "ok": 1,
        "liked": liked,
        "like_count": updated.get("like_count", 0),
    }


@router.post("/posts/{post_id}/dislike")
async def toggle_dislike(
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

    dislikes = post.get("dislikes", [])
    if user_id in dislikes:
        await request.app.db["social.posts"].update_one(
            {"_id": ObjectId(post_id)},
            {"$pull": {"dislikes": user_id}, "$inc": {"dislike_count": -1}},
        )
        disliked = False
    else:
        await request.app.db["social.posts"].update_one(
            {"_id": ObjectId(post_id)},
            {"$push": {"dislikes": user_id}, "$inc": {"dislike_count": 1}},
        )
        disliked = True

    updated = await request.app.db["social.posts"].find_one(
        {"_id": ObjectId(post_id)},
        {"dislike_count": 1, "dislikes": 1},
    )

    return {
        "ok": 1,
        "disliked": disliked,
        "dislike_count": updated.get("dislike_count", 0),
    }


@router.post("/posts/{post_id}/view")
async def increment_post_view(
    request: Request,
    post_id: str,
    payload: dict = Depends(verify_token),
):
    try:
        result = await request.app.db["social.posts"].update_one(
            {"_id": ObjectId(post_id)},
            {"$inc": {"views": 1}},
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")

    updated = await request.app.db["social.posts"].find_one(
        {"_id": ObjectId(post_id)},
        {"views": 1},
    )

    return {"ok": 1, "views": updated.get("views", 0)}


class CreateCustomPostRequest(BaseModel):
    title: str
    description: str
    link: str
    thumbnail_url: Optional[str] = None
    writing_time: Optional[int] = None


@router.post("/posts/custom/thumbnail")
async def upload_custom_thumbnail(
    request: Request,
    payload: dict = Depends(verify_token),
    file: UploadFile = File(...),
):
    contents = await file.read()
    if len(contents) > 128 * 1024:
        raise HTTPException(status_code=400, detail="File must be 128KB or smaller")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    b64 = base64.b64encode(contents).decode("utf-8")
    mime = file.content_type or "image/png"
    data_uri = f"data:{mime};base64,{b64}"
    return {"ok": 1, "thumbnail_url": data_uri}


@router.post("/posts/custom")
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
    if not body.link.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link must be a valid URL")

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)

    post_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    post = {
        "_id": post_id,
        "user_id": user_id,
        "title": body.title,
        "description": body.description,
        "link": body.link,
        "thumbnail_url": body.thumbnail_url,
        "writing_time": body.writing_time,
        "likes": [],
        "like_count": 0,
        "views": 0,
        "ip": ip,
        "created_at": now,
    }
    await request.app.db["posts.custom"].insert_one(post)

    post["_id"] = post_id
    post["created_at"] = now.isoformat()
    post.pop("likes", None)

    return {"ok": 1, "post": post}


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
        await request.app.db["posts.custom"].update_one(
            {"_id": post_id},
            {"$pull": {"likes": user_id}, "$inc": {"like_count": -1}},
        )
        liked = False
    else:
        await request.app.db["posts.custom"].update_one(
            {"_id": post_id},
            {"$push": {"likes": user_id}, "$inc": {"like_count": 1}},
        )
        liked = True

    updated = await request.app.db["posts.custom"].find_one(
        {"_id": post_id},
        {"like_count": 1, "likes": 1},
    )

    return {
        "ok": 1,
        "liked": liked,
        "like_count": updated.get("like_count", 0),
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

    updated = await request.app.db["posts.custom"].find_one(
        {"_id": post_id},
        {"views": 1},
    )

    return {"ok": 1, "views": updated.get("views", 0)}
