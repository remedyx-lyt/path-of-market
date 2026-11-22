"""启动真实 FastAPI 应用。只在这个测试进程内替换模型和外部资料源。"""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/agent/tests"))

from support import DOC_ID, SETTINGS, USAGE, FakeModel, make_tools, report, section
from app.api.routes import jobs, research
from app.main import app
from app.schemas.research import ModelContent
from app.services import agent_runner, research_jobs
from app.tools import public_web
import uvicorn


def serve(port, directory, *, pause_for_cancel=True):
    public_web.PROJECT_ROOT = directory
    os.environ["MCP_WEB_ENABLED"] = "false"
    tools = make_tools(directory / "evidence")
    jobs.get_research_tools = research_jobs.get_research_tools = lambda: tools
    jobs.load_model_settings = research.load_model_settings = lambda: SETTINGS

    def record(kind):
        with (directory / "model-calls.txt").open("a", encoding="utf-8") as output:
            print(kind, file=output)

    class ResearchModel(FakeModel):
        async def __call__(self, settings, messages, **kwargs):
            kind = self.kind(messages, kwargs)
            record(kind)
            if pause_for_cancel and kind == "section" and not self.resumed:
                # 资料读完后等待公开 DELETE 请求，以便稳定重现中途取消。
                await asyncio.Event().wait()
            return await super().__call__(settings, messages, **kwargs)

    def make_runner(job, tools, settings, *, recovery=None):
        draft = report()
        if job.request.include_financials:
            draft = report([
                section("业务与业绩", "合成资料仅覆盖已读两页。", topics=["business", "performance", "research"]),
                section("财务与风险", "盈利、现金流及负债数据仍有缺口。", topics=["profitability", "cashflow", "balance_sheet", "risks"]),
                section("行情", "价格使用同一口径。", market=True),
            ])
        model = ResearchModel(ready=True, final=draft)
        model.resumed = recovery is not None
        return agent_runner.AgentRunner(job, tools, settings, completion=model, recovery=recovery)

    async def discussion(settings, messages, **kwargs):
        record("discussion")
        reply = {"answer": "离线回答。", "citations": [{"sourceId": DOC_ID, "page": 1}],
                 "sectionEdits": [], "summary": None}
        return {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)}, USAGE

    async def analysis(settings, messages):
        record("analysis")
        return ModelContent(title="离线分析", summary="用于接口验收。", sections=[
            {"heading": "问题", "content": "先看历史。"}, {"heading": "限制", "content": "仅为研究思路。"}]), USAGE

    research_jobs.AgentRunner = make_runner
    agent_runner.complete_turn = discussion
    research.generate_content = analysis
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    serve(int(sys.argv[1]), Path(sys.argv[2]), pause_for_cancel="--complete" not in sys.argv[3:])
