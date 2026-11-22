"""先创建任务，再轮询进度；避免用同步长 HTTP 等待完整通读。"""

import asyncio
from datetime import date
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.core.config import load_model_settings
from app.schemas.agent import AgentResearchRequest
from app.schemas.discussion import FollowupRequest
from app.services.report_discussion import DiscussionRunner, prepare_followup, load_entries
from app.services.research_jobs import ResearchJob
from app.services.research_jobs import job_store
from app.services.research_recovery import load_recovery, recovery_error, can_retry_review
from app.storage import get_storage
from app.tools.registry import get_research_tools

router = APIRouter(prefix="/research/jobs", tags=["研究 Agent"])


@router.post("/{task_id}/chat", status_code=202)
async def followup_job(task_id: UUID, request: FollowupRequest):
    async with job_store.followup_lock:
        return await start_followup(task_id, request)


async def start_followup(task_id, request):
    try:
        tools = get_research_tools()
        prepared = await asyncio.to_thread(prepare_followup, tools, str(task_id), request)
        if "existingTaskId" in prepared:
            existing = job_store.jobs.get(prepared["existingTaskId"])
            if existing:
                return existing.snapshot()
            # 让网页按这个标识读取已落盘快照，不重新收费。
            raise recovery_error("此请求已经保存；请刷新对话记录后查看，勿重复提交。")
        settings = load_model_settings()
        # 同一次事件循环中检查并注册，避免两个 HTTP 请求同时启动模型。
        if job_store.busy():
            return JSONResponse(status_code=409, content={"error": {"code": "RESEARCH_BUSY", "message": "已有研究或对话正在运行。"}})
        if prepared["recovery"].get("model") and prepared["recovery"]["model"] != settings.model:
            raise recovery_error("模型与原研究不同，请先恢复原模型配置。")
        if prepared["recovery"].get("baseUrl") and prepared["recovery"]["baseUrl"] != settings.base_url:
            raise recovery_error("接口与原研究不同，请先恢复原接口配置。")
        job = ResearchJob(prepared["request"], session_id=prepared["sessionId"], is_followup=True)
        job.parent_task_id = str(task_id)
        runner = DiscussionRunner(job, tools, settings, prepared, request)
        job_store.register(job)
        # 先保存请求标识与父节点；落盘失败时不启动任何付费调用。
        if not await job.recorder.flush():
            await job.recorder.close(attempts=1)
            job_store.jobs.pop(job.task_id, None)
            raise recovery_error("会话存储暂不可用，未启动模型，请稍后重试。")
        job.task = asyncio.create_task(runner.run())
        return job.snapshot()
    except (ValueError, KeyError, TypeError):
        return JSONResponse(status_code=409, content={"error": {"code": "RESEARCH_NOT_RESUMABLE", "message": "保存的会话或所选分支不完整，未启动模型调用。"}})


def missing():
    return JSONResponse(
        status_code=404, content={"error": {"code": "RESEARCH_NOT_FOUND", "message": "任务不存在或服务已重启，请重新开始。"}}
    )


@router.post("", status_code=202)
async def create_job(request: AgentResearchRequest):
    if request.as_of_date > date.today():
        return JSONResponse(
            status_code=422, content={"detail": [{"loc": ["body", "asOfDate"], "type": "value_error", "msg": "研究截止日不能晚于今天"}]}
        )
    settings = load_model_settings()

    job = job_store.start(request, settings)
    if job is None:
        return JSONResponse(
            status_code=409, content={"error": {"code": "RESEARCH_BUSY", "message": "已有研究正在运行，请等待完成或先停止该任务。"}}
        )
    return job.snapshot()


@router.get("/{task_id}")
async def get_job(task_id: UUID):
    job = job_store.jobs.get(str(task_id))
    if job:
        return job.snapshot()
    snapshot = await asyncio.to_thread(get_storage().sessions.snapshot, str(task_id))
    return snapshot if snapshot is not None else missing()


@router.post("/{task_id}/continue", status_code=202)
async def continue_job(task_id: UUID):
    """新运行关联旧任务，保留旧结果；恢复操作只有用户明确提交时才开始收费调用。"""
    try:
        parent = job_store.jobs.get(str(task_id))
        if parent and parent.status in {"queued", "running"}:
            raise recovery_error("原研究仍在运行，请先查看进度。")
        existing = job_store.continuation(str(task_id))
        if existing:
            return existing.snapshot()
        settings = load_model_settings()
        recovery = await asyncio.to_thread(load_recovery, get_research_tools(), str(task_id), allow_completed=True)
        if recovery.get("status") == "completed":
            report = parent.report if parent else next((e.get("report") for e in reversed(await asyncio.to_thread(load_entries, str(task_id))) if e.get("type") == "report"), None)
            if not can_retry_review(recovery, report):
                raise recovery_error("研究已完成，无需接续。")
        if recovery.get("model") and recovery["model"] != settings.model:
            raise recovery_error("当前模型与原任务不同，请恢复原模型配置后接续。")
        if recovery.get("baseUrl") and recovery["baseUrl"] != settings.base_url:
            raise recovery_error("当前模型服务与原任务不同，请恢复原接口地址后接续。")
        request = AgentResearchRequest.model_validate(recovery["request"])
        job = job_store.start(request, settings, recovery=recovery)
        if job is None:
            return JSONResponse(status_code=409, content={"error": {"code": "RESEARCH_BUSY", "message": "已有研究正在运行。"}})
        return job.snapshot()
    except (ValueError, KeyError, TypeError):
        return JSONResponse(status_code=409, content={"error": {"code": "RESEARCH_NOT_RESUMABLE", "message": "保存的进度不完整或格式不兼容，未开始新的模型调用；可重新研究。"}})


@router.delete("/{task_id}")
async def cancel_job(task_id: UUID):
    job = job_store.jobs.get(str(task_id))
    if job is None:
        return missing()
    job_store.cancel(job)
    await asyncio.sleep(0)
    return job.snapshot()
