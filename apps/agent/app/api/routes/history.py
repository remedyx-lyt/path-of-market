"""网页读取历史会话、报告分支和用户记忆的入口。"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Response
from fastapi.responses import JSONResponse

from app.storage import get_storage
from app.storage.memory import MemoryConflict

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok", "service": "server"}


@router.get("/research/sessions")
def recent_sessions(limit: int = 20):
    return {"sessions": get_storage().sessions.recent(limit)}


@router.get("/research/jobs/{task_id}/discussion")
def discussion(task_id: UUID):
    result = get_storage().sessions.discussion(str(task_id))
    return result if result is not None else Response(status_code=404)


def memory_error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@router.get("/research/memory")
def user_memory(query: str = "", limit: int = 20, excludeRoot: str = ""):
    try:
        return get_storage().snapshot(query, limit, excludeRoot)
    except OSError:
        return memory_error(503, "MEMORY_UNAVAILABLE", "记忆文件暂不可读。")


@router.post("/research/memory")
def edit_memory(body: Any = Body(...)):
    if not isinstance(body, dict):
        return memory_error(400, "INVALID_MEMORY", "记忆修改须为 JSON 对象。")
    try:
        return get_storage().edit(body)
    except MemoryConflict as error:
        return memory_error(409, "MEMORY_CONFLICT", str(error))
    except ValueError as error:
        return memory_error(400, "INVALID_MEMORY", str(error))
    except OSError:
        return memory_error(503, "MEMORY_UNAVAILABLE", "记忆暂不可用，原文件保留。")
