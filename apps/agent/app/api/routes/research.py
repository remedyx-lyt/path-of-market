"""基础健康检查、演示研究与模型分析接口。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.research import HealthResponse, MockResearchReport, ResearchRequest, ModelResearchRequest, ModelResearchReport, ModelRun
from app.core.config import ModelServiceError, load_model_settings
from app.core.prompts import build_messages
from app.services.model_client import generate_content
from app.services.workflows.mock_research import build_mock_report

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["服务状态"])
def health() -> HealthResponse:
    """只确认应用可响应，不发起模型调用或检查外部数据源。"""
    return HealthResponse()


@router.post("/research/mock", response_model=MockResearchReport, tags=["演示研究"])
def research_mock(request: ResearchRequest) -> MockResearchReport:
    """校验输入并返回演示报告，不进行真实研究。"""
    return build_mock_report(request)


@router.post("/research/model", response_model=ModelResearchReport, tags=["模型研究"])
async def research_model(request: ModelResearchRequest):
    """模型生成研究思路；尚无真实资料工具或长期记忆。"""
    task_id = str(uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    states = ["created"]
    try:
        settings = load_model_settings()
        states.append("calling_model")
        content, usage = await generate_content(settings, build_messages(request))
        states.append("completed")
        return ModelResearchReport(
            **request.model_dump(),
            **content.model_dump(),
            limitations=[
                "仅调用模型生成研究思路，尚未检索真实资料或验证最新事实。",
                "偏好和预兆影响本次关注点，资料工具与长期记忆尚未接入。",
            ],
            run=ModelRun(
                task_id=task_id,
                states=states,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc).isoformat(),
                model=settings.model,
                usage=usage,
            ),
        )
    except ModelServiceError as error:
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {"code": error.code, "message": error.message},
                "run": {
                    "taskId": task_id,
                    "status": "failed",
                    "states": states + ["failed"],
                    "startedAt": started_at,
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "stopReason": error.code,
                },
            },
        )
