"""离线测试公共夹具：复用 scripts/check-tools.py 的巨潮/PDF 假数据，模型用脚本化假实现，不调用真实模型或网络。"""

from dataclasses import replace
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/agent"))

from pypdf import PdfReader, PdfWriter  # noqa: E402

from app.core.agent_prompts import METHOD_SYSTEM, READ_SYSTEM, REVIEW_SYSTEM, TABLE_RULES  # noqa: E402
from app.core.config import ModelSettings  # noqa: E402
from app.schemas.agent import AgentResearchRequest  # noqa: E402
from app.services.agent_runner import AgentRunner, RunLimits  # noqa: E402
from app.services.research_jobs import ResearchJob  # noqa: E402
from app.tools.cninfo import CninfoProvider  # noqa: E402
from app.tools.market import compute_metrics  # noqa: E402
from app.tools.registry import ResearchTools  # noqa: E402

_spec = importlib.util.spec_from_file_location("tool_fixtures", ROOT / "scripts/check-tools.py")
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)

SETTINGS = ModelSettings("isolated-test-key-only", "http://127.0.0.1:1", "isolated-test", 1, 1800)
DOC_ID = "cninfo-1234567890"
BASE_REQUEST = {
    "target": "同花顺",
    "question": "研究最近两年的经营变化与行情。",
    "asOfDate": "2026-10-23",
    "includeMarket": True,
    "includeCurrentPeriod": False,
    "includeFinancials": False,
}
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}


class FakeMarket:
    def history(self, company, start, end):
        series = [
            {"date": f"2024-01-0{i + 2}", "open": raw, "close": raw, "high": raw, "low": raw, "volume": 100.0, "adjustedClose": adj}
            for i, (raw, adj) in enumerate([(100, 100), (50, 100), (55, 110)])
        ]
        return {
            "company": company,
            "requestedStart": start,
            "requestedEnd": end,
            "series": series,
            "metrics": compute_metrics(series),
            "provider": "isolated",
            "currency": "CNY",
            "actualStart": series[0]["date"],
            "actualEnd": series[-1]["date"],
            "retrievedAt": "2026-10-23T00:00:00Z",
            "sourceUrls": ["https://example.com/raw", "https://example.com/hfq"],
            "limitations": ["隔离测试数据，不用于投资研究。"],
        }


def make_tools(root):
    transport = fixtures.FakeTransport()
    reader = PdfReader(BytesIO(transport.data))
    writer = PdfWriter()
    for page in list(reader.pages)[:2]:  # 第三页无文字，会阻止“全文已读”，这里只保留两页
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    transport.data = output.getvalue()
    return ResearchTools(Path(root), CninfoProvider(transport), FakeMarket())


def section(heading, content, *, topics=(), omens=(), page=1, market=False):
    citation = {"sourceId": "market-300033", "page": None} if market else {"sourceId": DOC_ID, "page": page}
    return {"heading": heading, "content": content, "topics": list(topics), "omens": list(omens), "citations": [citation]}


def report(sections=None, omen_coverage=None):
    return {
        "title": "隔离研究报告",
        "summary": "依据实际工具流程验证。",
        "sections": sections
        or [section("经营证据", "原文记录需结合单位与年度解释。"), section("行情口径", "实际价格与复权序列不同。", market=True)],
        "omenCoverage": omen_coverage or [],
    }


def tool_call(step, index, name, args):
    return {"id": f"call_{step}_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


DEFAULT_SCRIPT = [
    [
        ("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"}),
        ("get_market_data", {"company": "同花顺", "startDate": "2024-01-01", "endDate": "2026-10-23"}),
    ],
    [("read_document", {"documentId": DOC_ID, "mode": "full"})],
    "final",
]


class FakeModel:
    """按请求类型应答：方法计划 / 阅读 / 主循环决策 / 写作 / 复核。记录每次调用便于断言。"""

    def __init__(self, *, script=None, final=None, plan=None, review=None, ready=False, tables=None):
        self.script = list(script or DEFAULT_SCRIPT)
        self.final = final or report()
        self.plan = plan
        self.review = review if review is not None else {"unchanged": True}
        self.ready = ready
        self.tables = tables if tables is not None else [{"tables": []}]  # 每次数据表请求依次返回
        self.calls = []  # (kind, max_tokens, messages, kwargs)

    def kind(self, messages, kwargs):
        last = str(messages[-1].get("content", ""))
        if last.startswith("WRITE_REPORT_SECTION\n"):
            return "section"
        if last.startswith("WRITE_REPORT_METADATA\n"):
            return "metadata"
        if kwargs.get("tools") and kwargs.get("tool_choice", "auto") != "none":
            return "decision"
        system = messages[0]["content"]
        if system == METHOD_SYSTEM:
            return "plan"
        if system == REVIEW_SYSTEM:
            return "review"
        if system == READ_SYSTEM:
            return "reading"
        if str(messages[-1].get("content", "")).startswith(TABLE_RULES[:20]):
            return "tables"
        return "compose"

    def default_plan(self, task):
        reference = task["references"][0]["reference"]
        checks = [
            {"topic": "business", "question": "经营变化", "evidenceNeeded": "年报", "figureIdea": "无", "methodReference": reference}
        ] * 3
        for omen in task["omenSpecs"]:
            checks += [
                {
                    "topic": "risks",
                    "question": q,
                    "evidenceNeeded": "原文",
                    "figureIdea": "无",
                    "methodReference": reference,
                    "omen": omen["id"],
                }
                for q in omen["keyQuestions"][:2]
            ]
        return {"focus": "隔离计划", "checks": checks, "unavailable": []}

    async def __call__(self, settings, messages, **kwargs):
        kind = self.kind(messages, kwargs)
        self.calls.append((kind, kwargs.get("max_tokens"), messages, kwargs))
        if kind == "plan":
            task = json.loads(messages[1]["content"])
            plan = self.plan(task, len([c for c in self.calls if c[0] == "plan"])) if callable(self.plan) else self.default_plan(task)
            return {"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)}, USAGE
        if kind == "reading":
            task = json.loads(messages[1]["content"])
            note = {
                "summary": "已检查本批所有原文。",
                "facts": [{"text": "本批含研究费用数字。", "pages": [task["pages"][0]["page"]]}],
                "gaps": [],
            }
            return {"role": "assistant", "content": json.dumps(note, ensure_ascii=False)}, USAGE
        if kind == "review":
            return {"role": "assistant", "content": json.dumps(self.review, ensure_ascii=False)}, USAGE
        if kind == "tables":
            reply = self.tables[min(self.count("tables"), len(self.tables)) - 1]
            return {"role": "assistant", "content": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)}, USAGE
        if kind == "compose":
            return {"role": "assistant", "content": json.dumps(self.final, ensure_ascii=False)}, USAGE
        if kind == "section":
            task = json.JSONDecoder().raw_decode(messages[-1]["content"].split("\n", 1)[1])[0]
            return {"role": "assistant", "content": json.dumps(self.final["sections"][task["sectionIndex"]], ensure_ascii=False)}, USAGE
        if kind == "metadata":
            return {"role": "assistant", "content": json.dumps({k: self.final.get(k, []) for k in ["summary", "omenCoverage"]}, ensure_ascii=False)}, USAGE
        step = len([c for c in self.calls if c[0] == "decision"])
        action = self.script[min(step, len(self.script)) - 1]
        if action == "final":
            content = {"ready": True} if self.ready else self.final
            return {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)}, USAGE
        return {"role": "assistant", "content": None, "tool_calls": [tool_call(step, i, n, a) for i, (n, a) in enumerate(action)]}, USAGE

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


class RunnerFixture:
    """为每个测试准备独立临时目录与工具。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tools = make_tools(self.tmp.name)

    def runner(self, model=None, *, limits=None, **request):
        job = ResearchJob(AgentResearchRequest(**{**BASE_REQUEST, **request}))
        runner = AgentRunner(job, self.tools, SETTINGS, limits=replace(RunLimits(), **(limits or {})), completion=model or FakeModel())
        return job, runner
