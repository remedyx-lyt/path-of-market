"""单机进程内任务；事件带父关系。有记录器时，事件、消息与报告同时写入 Java SessionStore 的会话 JSONL（M2-1）。"""

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from app.services.agent_runner import AgentRunner, now
from app.services.session_recorder import SessionRecorder
from app.tools.registry import get_research_tools


@dataclass
class ResearchJob:
    request: object
    task_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "queued"
    phase: str = "queued"  # 研究阶段：methods → research → writing → tables → review → done（活动流显示用）
    started_at: str = field(default_factory=now)
    finished_at: str | None = None
    events: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    coverage: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model_calls: int = 0
    report: dict | None = None
    error: dict | None = None
    cancel_requested: bool = False
    task: object = field(default=None, repr=False)
    recorder: object = field(default=None, repr=False)  # SessionRecorder；单元测试直接构造的任务没有
    parent_task_id: str | None = None

    def emit(self, event_type, message, **details):
        event = {
                "id": str(uuid4()),
                "parentId": self.events[-1]["id"] if self.events else None,
                "type": event_type,
                "timestamp": now(),
                "sessionId": self.session_id,
                "runId": self.task_id,
                "message": message,
                **details,
            }
        self.events.append(event)
        if self.recorder:
            self.recorder.add("event", data=event)

    def set_phase(self, phase, message):
        """切换研究阶段并记一条事件，网页据此显示阶段进度。"""
        self.phase = phase
        self.emit("phase_changed", message, phase=phase)

    def snapshot(self):
        return {
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "status": self.status,
            "phase": self.phase,
            "target": self.request.target,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "progress": self.events[-1]["message"] if self.events else "等待开始",
            # 活动流需要完整过程；一次研究通常几百条，设上限防止异常膨胀。
            "events": self.events[-3000:],
            "eventCount": len(self.events),
            "modelCalls": self.model_calls,
            "usage": self.usage,
            "toolCalls": self.tool_calls,
            "sources": self.sources,
            "coverage": self.coverage,
            "report": self.report,
            "error": self.error,
            "storage": "session_jsonl" if self.recorder else "process_memory",
            "persistence": self.recorder.status() if self.recorder else None,
            "parentTaskId": self.parent_task_id,
        }


class JobStore:
    def __init__(self):
        self.jobs = {}

    def start(self, request, settings, *, recovery=None):
        if recovery:
            previous = next((j for j in self.jobs.values() if j.parent_task_id == recovery["taskId"]), None)
            if previous:
                return previous
        if any(j.status in {"queued", "running"} for j in self.jobs.values()):
            return None
        while len(self.jobs) >= 8:
            self.jobs.pop(next(iter(self.jobs)))
        job = ResearchJob(request)
        job.parent_task_id = recovery["taskId"] if recovery else None
        job.recorder = SessionRecorder(job.session_id, job.task_id)
        job.recorder.header(request.model_dump(mode="json", by_alias=True))
        if recovery:
            job.recorder.add("continuation", parentTaskId=recovery["taskId"], parentSessionId=recovery["sessionId"],
                             previousModelCalls=recovery.get("modelCalls", 0), previousUsage=recovery.get("usage", {}))
        runner = AgentRunner(job, get_research_tools(), settings, **({"recovery": recovery} if recovery else {}))
        job.recorder.start()
        job.emit("user_message", "研究任务已创建")
        self.jobs[job.task_id] = job
        job.task = asyncio.create_task(runner.run())
        return job

    def cancel(self, job):
        if job.status in {"queued", "running"}:
            job.cancel_requested = True
            job.task.cancel()
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = now()
                job.emit("run_cancelled", "研究任务已取消")
        return job


job_store = JobStore()
