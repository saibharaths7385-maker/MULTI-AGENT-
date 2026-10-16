import asyncio
import io
import json
import re
import shutil
import threading
import time
import uuid
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend import core
from backend.auth import router as auth_router
from backend.database import q
from backend.settings import WS

router = APIRouter()
router.include_router(auth_router)
PROJECT_ID = re.compile(r"^[0-9a-f]{10}$")


class NewProject(BaseModel):
    idea: str
    name: str = ""
    constraints: str = ""


def require_project(pid):
    if not PROJECT_ID.fullmatch(pid):
        raise HTTPException(404, "Project not found")
    rows = q("select * from projects where id=?", (pid,))
    if not rows:
        raise HTTPException(404, "Project not found")
    return rows[0]


@router.get("/api/config")
def config():
    from backend.settings import MAX_FIX, MODEL, NEED_OK, SANDBOX

    return {
        "provider": core.PROVIDER,
        "model": MODEL,
        "sandbox": SANDBOX,
        "has_key": bool(core.KEY),
        "approval": NEED_OK,
        "max_fix": MAX_FIX,
    }


@router.post("/api/projects")
def create(payload: NewProject):
    if not payload.idea.strip():
        raise HTTPException(400, "idea required")
    pid = uuid.uuid4().hex[:10]
    q(
        "insert into projects(id,name,idea,constraints,status,created) values(?,?,?,?,?,?)",
        (pid, payload.name or payload.idea[:40], payload.idea, payload.constraints, "queued", time.time()),
    )
    threading.Thread(target=core.pipeline, args=(pid,), daemon=True).start()
    return {"id": pid}


@router.get("/api/projects")
def projects():
    return [
        dict(row)
        for row in q("select id,name,status,tokens,created from projects order by created desc")
    ]


@router.get("/api/projects/{pid}")
def project(pid: str):
    row = require_project(pid)
    result = dict(row)
    result["plan"] = json.loads(result["plan"]) if result["plan"] else None
    result["files"] = core.list_files(pid)
    return result


@router.get("/api/projects/{pid}/events")
async def events(pid: str, after: int = 0):
    require_project(pid)

    async def generate():
        last = after
        while True:
            rows = q("select * from events where project_id=? and id>? order by id", (pid, last))
            for row in rows:
                last = row["id"]
                yield f"data: {json.dumps(dict(row))}\n\n"
            status = q("select status from projects where id=?", (pid,))
            if not rows and (not status or status[0]["status"] in core.TERMINAL):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.6)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/projects/{pid}/file")
def file(pid: str, path: str):
    require_project(pid)
    try:
        target = (WS / pid / core.safe(path)).resolve()
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if WS.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found")
    return Response(target.read_text(errors="replace"), media_type="text/plain")


def decide(pid, approved):
    require_project(pid)
    if pid not in core.APPROVALS:
        raise HTTPException(409, "nothing awaiting approval")
    event, result = core.APPROVALS[pid]
    result["ok"] = approved
    event.set()
    return {"ok": True}


@router.post("/api/projects/{pid}/approve")
def approve(pid: str):
    return decide(pid, True)


@router.post("/api/projects/{pid}/reject")
def reject(pid: str):
    return decide(pid, False)


@router.post("/api/projects/{pid}/cancel")
def cancel(pid: str):
    require_project(pid)
    core.setst(pid, "cancelled")
    if pid in core.APPROVALS:
        decide(pid, False)
    return {"ok": True}


@router.get("/api/projects/{pid}/download")
def download(pid: str):
    require_project(pid)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in core.list_files(pid):
            archive.write(WS / pid / path, path)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={pid}.zip"},
    )


@router.delete("/api/projects/{pid}")
def delete(pid: str):
    require_project(pid)
    shutil.rmtree(WS / pid, ignore_errors=True)
    q("delete from events where project_id=?", (pid,))
    q("delete from projects where id=?", (pid,))
    return {"ok": True}
