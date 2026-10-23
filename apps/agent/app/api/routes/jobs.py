"""先创建任务，再轮询进度；避免用同步长 HTTP 等待完整通读。"""

import asyncio
from datetime import date
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.core.config import ModelServiceError, load_model_settings
from app.schemas.agent import AgentResearchRequest
from app.services.research_jobs import job_store

router = APIRouter(prefix="/research/jobs", tags=["研究 Agent"])


def missing():
    return JSONResponse(status_code=404, content={"error": {"code": "RESEARCH_NOT_FOUND", "message": "任务不存在或服务已重启，请重新开始。"}})


@router.post("", status_code=202)
async def create_job(request: AgentResearchRequest):
    try:
        if request.as_of_date > date.today():
            return JSONResponse(status_code=422, content={"detail": [{"loc": ["body", "asOfDate"], "type": "value_error", "msg": "研究截止日不能晚于今天"}]})
        settings = load_model_settings()
    except ModelServiceError as error:
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message}})
    job = job_store.start(request, settings)
    if job is None:
        return JSONResponse(status_code=409, content={"error": {"code": "RESEARCH_BUSY", "message": "已有研究正在运行，请等待完成或先停止该任务。"}})
    return job.snapshot()


@router.get("/{task_id}")
async def get_job(task_id: UUID):
    job = job_store.jobs.get(str(task_id))
    return job.snapshot() if job else missing()


@router.delete("/{task_id}")
async def cancel_job(task_id: UUID):
    job = job_store.jobs.get(str(task_id))
    if job is None:
        return missing()
    job_store.cancel(job)
    await asyncio.sleep(0)
    return job.snapshot()
