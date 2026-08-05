from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
import re
from datetime import datetime, timezone
from . import verify_token, limiter, rate_limit_ip, rate_limit_user

router = APIRouter()

ALLOWED_NAME = re.compile(r"^[^/\\:*?\"<>|]{1,100}$")


def sanitize_name(name: str) -> str:
    cleaned = name.strip()
    if not ALLOWED_NAME.match(cleaned):
        raise HTTPException(
            status_code=400,
            detail="Name can't contain / \\ : * ? \" < > | and must be 1-100 characters",
        )
    return cleaned


def ensure_markdown(name: str) -> str:
    if "." not in name.split("/")[-1]:
        name = f"{name}.md"
    return name


async def get_note(db, user_id: str, note_id: str) -> dict | None:
    return await db["notes.docs"].find_one({"note_id": note_id, "user_id": user_id})


async def get_children(db, user_id: str, parent_id: str | None):
    query = {"user_id": user_id}
    if parent_id is None:
        query["parent_id"] = None
    else:
        query["parent_id"] = parent_id
    return await db["notes.docs"].find(query).to_list(length=None)


async def sibling_name_taken(db, user_id: str, parent_id: str | None, name: str, exclude_id: str | None = None) -> bool:
    siblings = await get_children(db, user_id, parent_id)
    for s in siblings:
        if s.get("name", "").lower() == name.lower():
            if exclude_id and s.get("note_id") == exclude_id:
                continue
            return True
    return False


async def collect_descendant_ids(db, user_id: str, note_id: str) -> list[str]:
    all_notes = await db["notes.docs"].find({"user_id": user_id}).to_list(length=None)
    by_parent: dict[str | None, list[dict]] = {}
    for n in all_notes:
        by_parent.setdefault(n.get("parent_id"), []).append(n)

    ids: list[str] = []
    stack = [note_id]
    while stack:
        current = stack.pop()
        ids.append(current)
        for child in by_parent.get(current, []):
            stack.append(child.get("note_id"))
    return ids


@router.get("")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_notes(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    cursor = request.app.db["notes.docs"].find({"user_id": user_id})
    notes = await cursor.to_list(length=None)

    response = []
    for n in notes:
        response.append({
            "note_id": n.get("note_id"),
            "type": n.get("type"),
            "parent_id": n.get("parent_id"),
            "name": n.get("name"),
            "created_at": n.get("created_at"),
            "updated_at": n.get("updated_at"),
        })
    response.sort(key=lambda n: (n.get("type") != "folder", n.get("name", "").lower()))
    return response


@router.post("/folders")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("40/hour", key_func=rate_limit_user)
async def create_folder(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    name = sanitize_name(body.get("name", ""))
    parent_id = body.get("parent_id") or None

    if parent_id:
        parent = await get_note(request.app.db, user_id, parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found or unauthorized")
        if parent.get("type") != "folder":
            raise HTTPException(status_code=400, detail="Files can't contain folders")

    if await sibling_name_taken(request.app.db, user_id, parent_id, name):
        raise HTTPException(status_code=400, detail="A folder with that name already exists here")

    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    new_note = {
        "user_id": user_id,
        "note_id": note_id,
        "type": "folder",
        "parent_id": parent_id,
        "name": name,
        "created_at": now,
        "updated_at": now,
    }

    await request.app.db["notes.docs"].insert_one(new_note)
    new_note.pop("_id", None)
    return {"status": "success", "note": new_note}


@router.patch("/folders")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def rename_folder(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")
    name = sanitize_name(body.get("name", ""))

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Folder not found or unauthorized")
    if note.get("type") != "folder":
        raise HTTPException(status_code=400, detail="Not a folder")

    if await sibling_name_taken(request.app.db, user_id, note.get("parent_id"), name, exclude_id=note_id):
        raise HTTPException(status_code=400, detail="A folder with that name already exists here")

    await request.app.db["notes.docs"].update_one(
        {"note_id": note_id},
        {"$set": {"name": name, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "success"}


@router.delete("/folders")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("40/hour", key_func=rate_limit_user)
async def delete_folder(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Folder not found or unauthorized")
    if note.get("type") != "folder":
        raise HTTPException(status_code=400, detail="Not a folder")

    ids = await collect_descendant_ids(request.app.db, user_id, note_id)
    await request.app.db["notes.docs"].delete_many({"note_id": {"$in": ids}, "user_id": user_id})
    return {"status": "success"}


@router.post("/files")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def create_file(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    name = ensure_markdown(sanitize_name(body.get("name", "")))
    parent_id = body.get("parent_id") or None

    if parent_id:
        parent = await get_note(request.app.db, user_id, parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found or unauthorized")
        if parent.get("type") != "folder":
            raise HTTPException(status_code=400, detail="Files can't live inside files")

    if await sibling_name_taken(request.app.db, user_id, parent_id, name):
        raise HTTPException(status_code=400, detail="A file with that name already exists here")

    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    new_note = {
        "user_id": user_id,
        "note_id": note_id,
        "type": "file",
        "parent_id": parent_id,
        "name": name,
        "content": body.get("content", ""),
        "created_at": now,
        "updated_at": now,
    }

    await request.app.db["notes.docs"].insert_one(new_note)
    new_note.pop("_id", None)
    return {"status": "success", "note": new_note}


@router.get("/files")
@limiter.limit("60/minute", key_func=rate_limit_ip)
async def get_file(request: Request, payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    note_id = request.query_params.get("note_id")

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="File not found or unauthorized")
    if note.get("type") != "file":
        raise HTTPException(status_code=400, detail="Not a file")

    return {
        "note_id": note.get("note_id"),
        "type": note.get("type"),
        "parent_id": note.get("parent_id"),
        "name": note.get("name"),
        "content": note.get("content", ""),
        "created_at": note.get("created_at"),
        "updated_at": note.get("updated_at"),
    }


@router.patch("/files")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def update_file(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="File not found or unauthorized")
    if note.get("type") != "file":
        raise HTTPException(status_code=400, detail="Not a file")

    update_data = {}
    if "name" in body:
        name = ensure_markdown(sanitize_name(body["name"]))
        if await sibling_name_taken(request.app.db, user_id, note.get("parent_id"), name, exclude_id=note_id):
            raise HTTPException(status_code=400, detail="A file with that name already exists here")
        update_data["name"] = name
    if "content" in body:
        update_data["content"] = body["content"]

    if update_data:
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await request.app.db["notes.docs"].update_one(
            {"note_id": note_id},
            {"$set": update_data},
        )

    return {"status": "success"}


@router.delete("/files")
@limiter.limit("20/minute", key_func=rate_limit_ip)
@limiter.limit("40/hour", key_func=rate_limit_user)
async def delete_file(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="File not found or unauthorized")
    if note.get("type") != "file":
        raise HTTPException(status_code=400, detail="Not a file")

    await request.app.db["notes.docs"].delete_one({"note_id": note_id})
    return {"status": "success"}


async def collect_descendant_docs(db, user_id: str, note_id: str) -> list[dict]:
    all_notes = await db["notes.docs"].find({"user_id": user_id}).to_list(length=None)
    by_parent: dict[str | None, list[dict]] = {}
    for n in all_notes:
        by_parent.setdefault(n.get("parent_id"), []).append(n)

    docs: list[dict] = []
    stack = [note_id]
    while stack:
        current = stack.pop()
        for child in by_parent.get(current, []):
            docs.append(child)
            stack.append(child.get("note_id"))
    return docs


async def validate_target_parent(db, user_id: str, parent_id: str | None) -> None:
    if parent_id is None:
        return
    parent = await get_note(db, user_id, parent_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Destination folder not found or unauthorized")
    if parent.get("type") != "folder":
        raise HTTPException(status_code=400, detail="Destination must be a folder")


def unique_copy_name(name: str, taken: set[str]) -> str:
    base, ext = name.rsplit(".", 1) if "." in name else (name, "")
    candidate = name
    i = 1
    while candidate.lower() in taken:
        suffix = f" copy"
        if i > 1:
            suffix = f" copy {i}"
        candidate = f"{base}{suffix}" + (f".{ext}" if ext else "")
        i += 1
    return candidate


@router.post("/copy")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def copy_note(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")
    target_parent_id = body.get("target_parent_id") or None

    source = await get_note(request.app.db, user_id, note_id)
    if not source:
        raise HTTPException(status_code=404, detail="Note not found or unauthorized")

    await validate_target_parent(request.app.db, user_id, target_parent_id)

    if target_parent_id == note_id or target_parent_id in [
        d.get("note_id") for d in await collect_descendant_docs(request.app.db, user_id, note_id)
    ]:
        raise HTTPException(status_code=400, detail="Can't copy a folder into itself")

    siblings = await get_children(request.app.db, user_id, target_parent_id)
    taken = {s.get("name", "").lower() for s in siblings}

    new_name = unique_copy_name(source.get("name", ""), taken)

    now = datetime.now(timezone.utc).isoformat()
    id_map = {note_id: str(uuid.uuid4())}

    new_root = dict(source)
    new_root["note_id"] = id_map[note_id]
    new_root["parent_id"] = target_parent_id
    new_root["name"] = new_name
    new_root["created_at"] = now
    new_root["updated_at"] = now
    new_root.pop("_id", None)
    await request.app.db["notes.docs"].insert_one(new_root)

    for child in await collect_descendant_docs(request.app.db, user_id, note_id):
        new_child = dict(child)
        new_child["note_id"] = str(uuid.uuid4())
        new_child["parent_id"] = id_map.get(child.get("parent_id"))
        new_child["created_at"] = now
        new_child["updated_at"] = now
        new_child.pop("_id", None)
        await request.app.db["notes.docs"].insert_one(new_child)
        id_map[child.get("note_id")] = new_child["note_id"]

    return {"status": "success", "note_id": id_map[note_id]}


@router.post("/move")
@limiter.limit("30/minute", key_func=rate_limit_ip)
@limiter.limit("60/hour", key_func=rate_limit_user)
async def move_note(request: Request, payload: dict = Depends(verify_token)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = payload.get("sub")
    note_id = body.get("note_id")
    target_parent_id = body.get("target_parent_id") or None

    note = await get_note(request.app.db, user_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found or unauthorized")

    if note.get("parent_id") == target_parent_id:
        return {"status": "success", "moved": False}

    await validate_target_parent(request.app.db, user_id, target_parent_id)

    if note.get("type") == "folder":
        if target_parent_id == note_id or target_parent_id in [
            d.get("note_id") for d in await collect_descendant_docs(request.app.db, user_id, note_id)
        ]:
            raise HTTPException(status_code=400, detail="Can't move a folder into itself")

    if await sibling_name_taken(request.app.db, user_id, target_parent_id, note.get("name", "")):
        raise HTTPException(status_code=400, detail="A note with that name already exists in the destination")

    await request.app.db["notes.docs"].update_one(
        {"note_id": note_id},
        {"$set": {"parent_id": target_parent_id, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"status": "success", "moved": True}
