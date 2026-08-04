from fastapi import APIRouter, Request, Depends, HTTPException
import uuid
import re
from datetime import datetime, timezone
from . import verify_token

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
