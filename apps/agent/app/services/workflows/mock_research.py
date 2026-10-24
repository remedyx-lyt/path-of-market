"""只生成用于接口联通的演示结构，不生成真实财经判断。"""

from app.schemas.research import (
    MockResearchReport,
    ReportOmen,
    ReportSection,
    ResearchRequest,
)

OMEN_NAMES = {
    ReportOmen.EXALTED: "崇高预兆",
    ReportOmen.ANCIENT: "远古预兆",
    ReportOmen.OPPORTUNITY: "机遇预兆",
    ReportOmen.ABYSSAL_ECHOES: "深渊回响预兆",
}


def build_mock_report(request: ResearchRequest) -> MockResearchReport:
    """保留输入，返回固定的演示章节，供后端和网页验证数据传递。"""
    omen_names = "、".join(OMEN_NAMES[omen] for omen in request.omens) or "未选择"
    user_style = request.user_style or "未指定"

    return MockResearchReport(
        target=request.target,
        question=request.question,
        user_style=request.user_style,
        omens=request.omens,
        title=f"{request.target}｜演示研究报告",
        summary="这是用于验证接口的演示报告，尚未读取真实资料、查询行情或调用大模型。",
        sections=[
            ReportSection(
                heading="研究任务",
                content=f"研究对象：{request.target}\n研究问题：{request.question}",
            ),
            ReportSection(
                heading="研究偏好与视角",
                content=(f"研究偏好：{user_style}\n启用预兆：{omen_names}\n当前只展示收到的配置，尚未执行真实研究策略。"),
            ),
            ReportSection(
                heading="后续资料与验证",
                content=("后续阶段将接入报告、公告和行情等资料工具。本次没有真实证据或工具调用，不能用于判断公司或市场情况。"),
            ),
        ],
    )
