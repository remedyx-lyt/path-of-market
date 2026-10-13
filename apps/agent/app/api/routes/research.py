"""健康检查和演示研究接口。"""

from fastapi import APIRouter

from app.schemas.research import HealthResponse, MockResearchReport, ResearchRequest
from app.services.workflows.mock_research import build_mock_report

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["服务状态"])
def health() -> HealthResponse:
    """只确认当前应用可响应，不检查尚未接入的模型和数据源。"""
    return HealthResponse()


@router.post("/research/mock", response_model=MockResearchReport, tags=["演示研究"])
def research_mock(request: ResearchRequest) -> MockResearchReport:
    """校验输入并返回演示报告，不进行真实研究。"""
    return build_mock_report(request)
