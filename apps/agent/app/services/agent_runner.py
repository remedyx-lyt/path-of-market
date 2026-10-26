"""研究 Agent 主循环：模型选工具 → 程序校验执行 → 结果回传 → 补查或写报告。参考 Pi 与 DeepSeek 工具协议。

AgentRunner 由几部分组成，各自拥有一块运行状态：
- runner_reading.ReadingMixin：来源登记、完整分批阅读、按页/关键词回查
- runner_evidence.EvidenceMixin：原页视觉核对、正文取数、财务/业务底稿
- runner_methods.MethodMixin：按问题与预兆选择原版方法并形成研究计划
- runner_omens.OmenMixin：预兆规格进入上下文、写作要求与覆盖自检（M1-4）
- runner_writing.WritingMixin：大纲、逐节生成/保存、失败单元恢复与摘要
- runner_report.ReportMixin：程序核查、数据表、复核与最终结构
本文件只保留循环本身：预算、模型调用、工具分派、上下文组装。
"""

import asyncio
from dataclasses import dataclass, replace
import json
import logging
import re
import time

from pydantic import ValidationError

from app.core.agent_prompts import initial_messages
from app.core.config import ModelServiceError
from app.core.research_skills import SkillArguments, load_research_skill, read_reference
from app.schemas.agent import AgentReadArguments
from app.schemas.financial import ExtractArguments, InspectArguments
from app.services.model_client import complete_turn
from app.services.context_compaction import CompactionMixin, ContextMessages, RecallArguments
from app.services.user_memory import UserMemoryMixin, RecallUserMemoryArguments, RememberUserMemoryArguments
from app.services.runner_evidence import EvidenceMixin
from app.services.runner_methods import MethodMixin
from app.services.runner_omens import OmenMixin
from app.services.runner_reading import ReadingMixin
from app.services.runner_web import WebMixin
from app.services.runner_history import HistoryMixin
from app.core.research_history import history_count
from app.tools.public_web import PublicSearchArguments, WebReadArguments
from app.services.runner_report import ReportMixin, compact_financial, strip_quotes
from app.services.runner_writing import WritingMixin
from app.services.runtime import BudgetStop, RunLimits, now
from app.services.reading_coverage import reading_complete
from app.services.session_recorder import RecordedMessages
from app.services.research_recovery import pending_calls, restore_runner, save_checkpoint
from app.tools.contracts import FindArguments, ToolError
from app.tools.documents import write_json
from app.tools.market import MarketArguments

__all__ = ["AgentRunner", "BudgetStop", "RunLimits", "declarations", "now"]

logger = logging.getLogger("path_of_market.agent")

TOOL_SPECS = (
    ("search_public_information", "通过MCP查公开信息，优先一手来源，自动按任务截止日过滤；摘要只发现，选中的网页仍须完整阅读。", PublicSearchArguments),
    ("read_web_document", "通过MCP获取已搜索到的网页完整正文并分批通读，保存游标/覆盖；full可接续，search只回查已通读原文。网页引用page=null；未知发布日期不能支持截止日事实。", WebReadArguments),
    ("recall_user_memory", "按公司名/关键词回查跨会话研究经历与已确认偏好；历史用户问题不是公司事实证据。", RecallUserMemoryArguments),
    ("remember_user_memory", "将本次用户表达的长期研究偏好存为待确认建议，必须附逐字用户原话；不能根据年报/模型回复推断画像或覆盖用户确认偏好。", RememberUserMemoryArguments),
    ("recall_research_context", "回查本分支完整文字/视觉阅读笔记或报告正文，不重新付费通读。reading_notes/visual_notes用sourceId/batch，report_section用sectionIndex。", RecallArguments),
    ("find_documents", "从公司/会计年度/截止日找官方完整报告，支持年报、半年报、一季报和三季报；不需要上传。", FindArguments),
    (
        "read_document",
        "完整读取选定 PDF（full 默认），内部下载、分批阅读并返回带页码要点和覆盖；page（可用 pages 一次1至5页）/search 仅复查。",
        AgentReadArguments,
    ),
    ("get_market_data", "获取股票区间日线，返回不复权实际价格和后复权计算的变化/回撤/波动/月度表现。", MarketArguments),
    (
        "inspect_document_pages",
        "实际查看已发现PDF的1至3个物理页图片，理解图表/表格/扫描页并保留页码；不代替全本文字阅读。",
        InspectArguments,
    ),
    (
        "read_research_skill",
        "读取项目保留的Anthropic原版金融研究方法；catalog列目录，按需分页读取，不执行其脚本或专属工具。",
        SkillArguments,
    ),
    (
        "extract_report_data",
        "从已通读PDF的1至4个物理页提取有原文依据的业务分部收入、研发、成本及资产负债数据，程序计算占比与趋势。",
        ExtractArguments,
    ),
)


TOOL_LABELS = {
    "search_public_information": "MCP搜索公开资料",
    "read_web_document": "MCP通读网页",
    "recall_user_memory": "回查用户研究记忆",
    "remember_user_memory": "记录偏好建议",
    "recall_research_context": "回查研究记录",
    "find_documents": "查找报告",
    "read_document": "阅读资料",
    "get_market_data": "查询行情",
    "inspect_document_pages": "查看PDF原页",
    "read_research_skill": "读取研究方法",
    "extract_report_data": "提取数据",
}


def declarations():
    return [
        {"type": "function", "function": {"name": name, "description": description, "parameters": schema.model_json_schema(by_alias=True)}}
        for name, description, schema in TOOL_SPECS
    ]


PHASE_PURPOSE = {"methods": "形成研究计划", "writing": "撰写正文", "tables": "整理数据表", "review": "复核报告"}

READY = re.compile(r'\{\s*"ready"\s*:\s*true\s*\}')


def wants_to_write(content):
    """决策阶段表示“证据够了，可以写报告”。除标准的 {"ready":true} 外，真实运行中出现过：文字说明后附 {"ready":true}，
    或 {"ready":true,...} 带其他字段。这些都转入写作，而不是当成一份格式错误的报告（会白白消耗一次重写机会）。"""
    try:
        body = json.loads(content or "")
    except ValueError:
        return bool(READY.search(content or ""))
    return isinstance(body, dict) and body.get("ready") is True and "sections" not in body


def context_characters(messages):
    """请求消息的文字长度。图片字节单独由渲染器限制，不能把base64当文字上下文；图片仍计入供应商实际用量。"""
    projected = [
        {
            **m,
            "content": [{"type": "image_url"} if p.get("type") == "image_url" else p for p in m["content"]]
            if isinstance(m.get("content"), list)
            else m.get("content"),
        }
        for m in messages
    ]
    return len(json.dumps(projected, ensure_ascii=False))


def page_texts(data):
    """按结构找出回查原文页：单页结果带 text，或多页结果的 pages 列表。通读笔记的 facts.text 不算原文页。"""
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("text"), str):
        return [data]
    pages = data.get("pages")
    if isinstance(pages, list):
        return [p for p in pages if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return []


@dataclass(frozen=True)
class ToolView:
    """一条工具消息的上下文投影。每条消息只解析一次，之后每轮直接复用，投影只取决于消息本身。"""

    content: str  # 原始完整结果（self.messages 中保存的文本），用于确认缓存仍对应这条消息
    projected: str  # 主循环投影：去掉整份底稿、通读笔记取有限要点
    excerpt: str  # 较早回查的版本：原文页超过 700 字截为摘录；无可截内容时与 projected 相同
    has_pages: bool  # 是否为带原文页的回查结果（按结构判断）

    @classmethod
    def build(cls, content):
        body = json.loads(content)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return cls(content, content, content, False)
        data.pop("financialData", None)
        data.pop("businessData", None)
        if data.get("notes"):
            data["notes"] = [
                {
                    "summary": n["summary"][:240],
                    "facts": [{"text": f["text"][:320], "pages": f["pages"]} for f in n["facts"][:2]],
                    "gaps": n["gaps"],
                }
                for n in data["notes"]
            ]
            data["contextProjection"] = "主循环为有限要点投影；完整批次记录保留，其他细节可按页回查。"
        if data.get('visualNotes'):
            data['visualNotes'] = [{**note, 'summary': note['summary'][:600]} for note in data['visualNotes']]
        projected = json.dumps(body, ensure_ascii=False)
        pages = page_texts(data)
        long_pages = [p for p in pages if len(p["text"]) > 700]
        for page in long_pages:
            page["text"] = page["text"][:700]
            page["contextProjection"] = "历史回查原文的有限摘录；完整页仍可通过read_document回查。"
        excerpt = json.dumps(body, ensure_ascii=False) if long_pages else projected
        return cls(content, projected, excerpt, bool(pages))


class AgentRunner(UserMemoryMixin, CompactionMixin, HistoryMixin, WebMixin, ReadingMixin, EvidenceMixin, MethodMixin, OmenMixin, WritingMixin, ReportMixin):
    def __init__(self, job, tools, settings, *, limits=None, completion=None, recovery=None):
        self.job, self.tools, self.settings = job, tools, settings
        self.limits = limits or RunLimits.for_history(history_count(job.request))
        self.completion = completion or complete_turn
        self.began = time.monotonic()
        self.recovery = recovery
        self.context_prefix_length = len(initial_messages(job.request))
        self.compaction_state = None
        self.compaction_count = 0
        self.discussion_context_version = 0
        self.discussion_source_baseline = None
        self.compaction_attempts = 0
        self.compaction_failed_at = None
        self.user_memory = None
        self.memory_loaded = False
        self.messages = recovery["messages"] if recovery else initial_messages(job.request)
        if job.recorder:  # 会话持久化：每条消息（含完整工具结果）同时记入 JSONL
            self.messages = RecordedMessages(self.messages, job.recorder)
        self.skill = load_research_skill()
        self.steps = 0
        self.invalid_finals = 0
        self.review_outcome = None
        self.context_wrapup = False  # 上下文接近上限后不再取证，直接写作
        self.wrapup_gaps = []  # 收尾写作时无法再补的证据缺口，写入报告局限
        self.table_gaps = []  # 必做数据表未能生成的说明，写入报告局限
        self.action_counts = {}
        # 工具消息的上下文投影缓存（tool_call_id → ToolView）
        self.tool_views = {}
        # 阅读（runner_reading）
        self.notes, self.sources, self.coverage = {}, {}, {}
        # 资料发现与当期报告
        self.discovered = {}
        self.web_discovered = {}
        self.history_checked, self.required_annual, self.history_gap = False, {}, None
        self.current_period_checked = False
        self.required_current = None
        self.current_period_gap = None
        self.market_data = None
        self.database_info = None  # 结构化财务报表（AKShare）取数状态：None 未尝试
        # 数值证据（runner_evidence）
        self.visual_readings, self.extraction_readings = [], []
        self.financial_points, self.financial_gaps = [], []
        self.restored_financial = None  # 旧会话已保存的派生同比；不反推缺失的历史原值
        self.segment_points, self.business_gaps = [], []
        self.financial_checked, self.detail_checked = set(), set()
        self.document_cache = {}  # sourceId → 逐页文字，供表格核对与经营数据页定位
        # 方法计划（runner_methods）
        self.method_usage = None
        self.report_candidate = None
        self.report_stage = None
        self.writing_state = None
        self.writer_tools_rejected = False
        if recovery:
            restore_runner(self, recovery)
            self.record_compaction(restored=True)

    def checkpoint(self):
        try:
            save_checkpoint(self)
        except OSError:
            logger.exception("checkpoint write failed for %s", self.job.task_id)
            self.job.emit("checkpoint_failed", "执行检查点写入失败；已提交的会话记录仍保留")

    @property
    def uses_real_provider(self):
        return self.completion is complete_turn

    def declarations(self):
        enabled = self.mcp_enabled
        return [d for d in declarations() if enabled or d["function"]["name"] not in {"search_public_information", "read_web_document"}]

    @property
    def mcp_enabled(self):
        service = getattr(self.tools, "public_web", None)
        return bool(service and service.gateway.settings.enabled)

    # ---- 预算与模型调用 -------------------------------------------------

    def check_budget(self, *, model_call=False, report=False):
        if self.job.cancel_requested:
            raise asyncio.CancelledError
        if time.monotonic() - self.began >= self.limits.max_seconds:
            raise BudgetStop("time_budget")
        # 本地回查/缓存读取不消耗模型调用，不能因为达到模型上限就禁止它们。
        if not model_call:
            return
        if self.job.model_calls >= self.limits.max_model_calls:
            raise BudgetStop("model_call_budget")
        if self.job.usage.get("total_tokens", 0) >= self.limits.max_tokens:
            raise BudgetStop("token_budget")
        reserve = min(self.limits.report_reserve_calls, max(0, self.limits.max_model_calls - 12))
        if not report and reserve and self.job.model_calls >= self.limits.max_model_calls - reserve:
            raise BudgetStop("research_call_budget")
        token_reserve = min(self.limits.report_reserve_tokens, self.limits.max_tokens // 10)
        if not report and self.job.usage.get("total_tokens", 0) >= self.limits.max_tokens - token_reserve:
            raise BudgetStop("research_token_budget")

    def record_usage(self, usage):
        for key, value in usage.items():
            self.job.usage[key] = self.job.usage.get(key, 0) + value
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            self.job.usage["total_tokens"] = self.job.usage.get("total_tokens", 0) + usage["prompt_tokens"] + usage["completion_tokens"]

    def model_purpose(self, *, tool_specs, reading, visual, write_only):
        """活动流里这次模型调用做什么：由调用方式和当前阶段决定。"""
        if visual:
            return "查看PDF原页"
        if reading:
            return "阅读原文"
        if tool_specs and not write_only:
            return "决定下一步"
        return PHASE_PURPOSE.get(self.job.phase, "提取数据")

    async def model(self, messages, *, tool_specs=None, reading=False, visual=False, report=False, write_only=False, on_text=None, output_limit=None, compacting=False, tool_choice=None):
        """write_only=True：发送同一组工具定义但禁止调用（tool_choice=none）并要求 JSON，让写作请求与研究轮次共享缓存前缀。
        on_text：流式输出时逐段收到模型文字（写作阶段据此显示“正在写：××”）。"""
        if not compacting:
            messages = await self.prepare_context(messages, report=report)
        self.check_budget(model_call=True, report=report)
        if context_characters(messages) > self.limits.max_context_characters:
            raise BudgetStop("context_budget")
        self.job.model_calls += 1
        purpose = "整理上下文摘要" if compacting else self.model_purpose(tool_specs=tool_specs, reading=reading, visual=visual, write_only=write_only)
        started = time.monotonic()
        # 多预兆报告允许更长：每个预兆追加输出预算，不为篇幅牺牲预兆分析。
        report_tokens = self.limits.report_tokens + 2500 * len(self.job.request.omens)
        output_tokens = self.settings.reading_max_tokens if reading else report_tokens if report else 6500
        if output_limit is not None:
            output_tokens = min(output_tokens, output_limit)
        self.job.emit("model_started", purpose, modelCall=self.job.model_calls, purpose=purpose, outputTokenLimit=output_tokens)
        # 累计预算以供应商实际用量记账，下一调用前检查；单次也有明确输出/时间上限。
        # 写作/复核输出整篇报告，使用单独的等待上限；研究轮次仍用较短上限。
        settings = replace(self.settings, timeout_seconds=self.settings.report_timeout_seconds) if report else self.settings
        try:
            options = {"tool_choice": "none", "json_mode": True} if write_only else {"json_mode": not bool(tool_specs)}
            if tool_choice is not None and not write_only:
                options["tool_choice"] = tool_choice
            if on_text:
                options["on_text"] = on_text
            message, usage = await self.completion(settings, messages, tools=tool_specs, max_tokens=output_tokens, **options)
        except ModelServiceError as error:
            usage = getattr(error, "usage", {})
            self.record_usage(usage)
            reason = getattr(error, "finish_reason", None)
            detail = "输出达到上限" if reason == "length" else error.message
            self.job.emit(
                "model_failed", f"{purpose}未完成：{detail}", modelCall=self.job.model_calls, purpose=purpose,
                errorCode=error.code, finishReason=reason, usage=usage, outputTokenLimit=output_tokens,
                durationMs=round((time.monotonic() - started) * 1000),
            )
            raise
        self.record_usage(usage)
        self.job.emit(
            "model_finished",
            f"{purpose}完成",
            modelCall=self.job.model_calls,
            purpose=purpose,
            usage=usage,
            durationMs=round((time.monotonic() - started) * 1000),
        )
        return message

    async def decision_turn(self, messages):
        """决策失败不丢证据：只重试完整消息，资料齐备时交给已有分节写作器。"""
        recoverable = {"MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_UPSTREAM_ERROR"}
        for attempt in range(3):
            try:
                return await self.model(messages, tool_specs=self.declarations())
            except ModelServiceError as error:
                if error.code not in recoverable:
                    raise
                if error.code == "MODEL_INVALID_RESPONSE" and self.can_budget_finish():
                    self.job.emit("decision_to_writing", "决策回复未完整，但必需证据已读齐：转入分节写作", errorCode=error.code)
                    return {"role": "assistant", "content": '{"ready":true}'}
                if attempt == 2:
                    raise
                self.job.emit("decision_retry", "决策回复未完成：保留证据重试，不执行不完整工具消息", attempt=attempt + 1, errorCode=error.code)
                messages = messages + [{"role": "user", "content":
                    "上一条决策回复未完整或暂时失败，没有执行其中任何工具。请仅返回必要的少量完整工具调用；"
                    '证据足够时仅返回 {"ready":true}。决策阶段不要写长报告，正文由后续分节写作完成。'}]

    async def raw_tool(self, name, arguments):
        self.check_budget()
        result = await asyncio.to_thread(self.tools.execute, name, arguments)
        if result["status"] != "completed":
            error = result["error"]
            raise ToolError(error["code"], error["message"], error.get("details"))
        return result["data"]

    # ---- 工具分派 -------------------------------------------------------

    async def dispatch(self, name, arguments):
        handlers = {
            "search_public_information": self.search_public_information,
            "read_web_document": self.read_web_document,
            "recall_user_memory": self.recall_user_memory,
            "remember_user_memory": self.remember_user_memory,
            "recall_research_context": self.recall_research_context,
            "find_documents": self.find_documents,
            "read_document": self.read,
            "get_market_data": self.market,
            "inspect_document_pages": self.inspect,
            "read_research_skill": self.read_skill,
            "extract_report_data": self.extract,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError("UNKNOWN_TOOL", "此工具未向研究模型开放。")
        return await handler(arguments)

    async def read_skill(self, arguments):
        result = await asyncio.to_thread(read_reference, arguments)
        if self.method_usage is not None and "reference" in result and result["reference"] not in self.method_usage["onDemandReads"]:
            self.method_usage["onDemandReads"].append(result["reference"])
            self.job.emit("skill_read", "按需读取研究方法：" + result["reference"].split("/skills/")[-1])
        return result

    async def find_documents(self, arguments):
        args = FindArguments.model_validate(arguments)
        if args.as_of_date != self.job.request.as_of_date.isoformat():
            raise ToolError("CUTOFF_MISMATCH", "查询应使用任务的研究截止日期。")
        args = await self.history_documents(args)
        result = await self.raw_tool("find_documents", args.model_dump(by_alias=True))
        self.register_history(args, result)
        if self.job.request.include_current_period and not self.current_period_checked:
            await self.add_current_period(args, result)
        self.discovered.update({d["documentId"]: d for d in result["documents"]})
        return result

    async def add_current_period(self, args, result):
        """默认补查截止年度最新已披露的季报/半年报，防止只读往年年报而遗漏当期。"""
        self.current_period_checked = True
        year = self.job.request.as_of_date.year
        supplement_args = {"company": args.company, "years": [year], "asOfDate": args.as_of_date, "reportTypes": ["q1", "interim", "q3"]}
        self.job.emit("current_period_lookup", f"核对 {year} 年已披露的最新定期报告")
        try:
            supplement = await self.raw_tool("find_documents", supplement_args)
            latest = [d for d in supplement["documents"] if d["preferred"]]
            if latest:
                self.required_current = max(latest, key=lambda d: d["publishedAt"])
            else:
                self.current_period_gap = f"当前来源未找到截至 {args.as_of_date} 已披露的 {year} 年季报/半年报。"
            merged = {d["documentId"]: d for d in result["documents"] + supplement["documents"]}
            result["documents"] = list(merged.values())
            result["currentPeriodQuery"] = {
                "arguments": supplement_args,
                "queryComplete": supplement["queryComplete"],
                "requiredLatestDocument": self.required_current,
            }
        except ToolError as error:
            self.current_period_gap = "当年最新报告查询未完成：" + error.message
        if self.current_period_gap:
            result["gaps"].append(self.current_period_gap)

    async def market(self, arguments):
        args = MarketArguments.model_validate(arguments)
        if args.end_date > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "行情结束日期晚于研究截止日。")
        data = await self.raw_tool("get_market_data", args.model_dump(by_alias=True))
        self.market_data = data
        identifier = "market-" + data["company"]["code"]
        self.sources[identifier] = {
            "sourceId": identifier,
            "kind": "market",
            "title": data["company"]["name"] + "历史日线（" + data["provider"] + "）",
            "url": data["sourceUrls"][0],
            "publishedAt": data["actualEnd"],
            "retrievedAt": data["retrievedAt"],
        }
        self.job.sources = list(self.sources.values())
        return {k: v for k, v in data.items() if k != "series"} | {"sourceId": identifier}

    # ---- 上下文组装 -----------------------------------------------------

    def conflicts(self):
        # 用底稿整理后的缺口：结构化数据（AKShare）已覆盖的年报取数提示不再算作“未解决的来源冲突”。
        return [g for g in dict.fromkeys(self.financial_data()["gaps"] + self.business_data()["gaps"]) if "冲突" in g]

    def tool_view(self, message):
        """取工具消息的投影；同一条消息只解析一次（内容变化时重建）。"""
        view = self.tool_views.get(message["tool_call_id"])
        if view is None or view.content != message["content"]:
            view = self.tool_views[message["tool_call_id"]] = ToolView.build(message["content"])
        return view

    def context(self, *, include_instruction=True):
        """主循环每轮请求的消息。self.messages 保留完整工具结果；这里只做有来源的有限投影。

        为了前缀缓存：历史消息的投影只取决于消息本身（与轮次无关），当前底稿和剩余轮数放在最后。
        """
        messages = ContextMessages(self.projected_history())
        if memory := self.memory_context():
            messages += [{"role": "user", "content": json.dumps(memory, ensure_ascii=False)}]
        # 机器保存的来源/覆盖/计划不交给摘要模型改写；每次请求都带准确索引。
        source_index = [{"sourceId": sid, "title": s["title"], "kind": s["kind"], "pageCount": s.get("pageCount"),
                         "textComplete": self.coverage.get(sid, {}).get("textComplete"), "readingComplete": reading_complete(self.coverage.get(sid)),
                         "noteBatches": len(self.notes.get(sid, [])), "visualNoteBatches": sum(r['sourceId'] == sid for r in self.visual_readings),
                         "publishedAt": s.get("publishedAt"), "citationEligible": s.get("citationEligible", True),
                         "coverageUnit": self.coverage.get(sid, {}).get("unit", "page")}
                        for sid, s in self.sources.items()]
        messages += [{"role": "user", "content": json.dumps({"type": "research_context_index", "sources": source_index,
                     "methodPlan": (self.method_usage or {}).get("plan"), "annualHistory": self.annual_context(),
                     "instruction": "完整阅读记录和精确底稿仍在程序中。需要历史细节用recall_research_context；摘要不是新证据。"}, ensure_ascii=False)}]
        if self.financial_points or self.financial_gaps or self.segment_points:
            state = {
                "type": "current_research_state",
                "financialData": compact_financial(self.financial_data()),
                "businessData": strip_quotes(self.business_data()),
                "visualCoverage": [{"sourceId": r["sourceId"], "pages": r["pages"]} for r in self.visual_readings],
                "note": "这是唯一当前底稿。主动选择能说明问题的图，章节chartIds/businessIds引用这里的ID；不按配额凑图。",
            }
            conflicts = self.conflicts()
            if conflicts:
                state["conflicts"] = conflicts
                state["conflictInstruction"] = "存在来源冲突：先查看原页或补查；仍无法确认则在报告中并列说明并列入局限，不自行选值。"
            operating = self.operating_pages()
            if operating:
                state["operatingDataPages"] = [{"sourceId": sid, "pages": pages} for sid, pages in operating.items()]
                state["operatingInstruction"] = "这些页有产能/产量/销量/库存数据，报告必须用 tables 列出；写作前可用 mode=page 回查原数。"
            messages += [{"role": "user", "content": json.dumps(state, ensure_ascii=False)}]
        if not include_instruction:
            return messages
        messages += [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "remainingDecisionSteps": max(0, self.limits.max_steps - self.steps),
                        "instruction": "优先用已取得的证据形成报告；只有会改变结论的缺口再补查，不为方法菜单穷尽所有指标。剩余轮数不足时明确局限并提交已有证据支持的最终报告。",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        return messages

    # ---- 主循环 ---------------------------------------------------------

    def start_context_wrapup(self):
        """摘要仍不足以腾出空间时停止取证、转入写作；原记录和证据保持不变。"""
        self.context_wrapup = True
        self.job.emit("context_wrapup", "上下文接近上限：停止取证，用已取得的证据撰写报告")
        self.messages.append(
            {
                "role": "user",
                "content": "上下文已接近上限，取证到此结束：只用已取得的证据写报告，在相关章节正文中说明哪些问题未能继续补查（局限清单由程序生成，不要新增 limitations 字段）。",
            }
        )

    async def finish(self, assistant):
        """模型未调用工具：ready 则进入写作，否则视为报告；通过核查返回 True，未通过则把问题回给模型。"""
        if not self.context_wrapup and (gaps := self.pending_evidence()):
            diagnostic = '证据尚未就绪，不开始写作。'+'；'.join(gaps)
            self.job.emit('evidence_pending', diagnostic[:600])
            self.messages.append({'role': 'user', 'content': diagnostic})
            # 这是正常的取证反馈，不算“报告格式失败”；总轮次/时间/用量边界仍有效。
            return False
        try:
            if wants_to_write(assistant.get("content")):
                assistant = await self.compose()
            tables_done = self.report_stage == "tables"
            content = self.validate_content(assistant)
            self.report_candidate = content.model_dump(mode="json", by_alias=True)
            self.checkpoint()
            if not tables_done:
                content = await self.add_tables(content)
                self.report_stage = "tables"
            elif self.recovery:
                content = self.recover_saved_tables(content)
            self.report_candidate = content.model_dump(mode="json", by_alias=True)
            self.checkpoint()
            content = await self.review(content)
            self.job.report = self.report(content)
            self.job.status = "completed"
            self.job.set_phase("done", "阶段：完成")
            self.job.emit("run_completed", "研究完成，报告与证据已返回")
            return True
        except ValueError as error:
            diagnostics = (
                "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in error.errors()[:5])
                if hasattr(error, "errors")
                else str(error)[:700]
            )
            write_json(
                self.tools.store.root / "invalid-reports" / f"{self.job.task_id}-{self.steps}.json",
                {"candidate": assistant.get("content"), "diagnostics": diagnostics},
            )
            # 错误草稿不反复堆入主上下文；事实与完整来源仍保留。
            self.messages.pop()
            self.invalid_finals += 1
            self.report_candidate = None
            self.report_stage = None
            self.job.emit("report_validation_failed", "报告需修正：" + diagnostics[:300])
            self.job.set_phase("research", "阶段：按核查意见修改或补查")
            if self.invalid_finals >= 3:
                raise BudgetStop("incomplete_evidence_or_report")
            self.messages.append(
                {"role": "user", "content": "报告尚未通过程序核查：" + diagnostics + "。请修正 JSON/引用或仅补关键证据，不重复穷尽取数。"}
            )
            return False

    async def run_tool_call(self, call):
        self.check_budget()
        name = call["function"]["name"]
        record = {"toolCallId": call["id"], "name": name, "status": "running", "startedAt": now()}
        self.job.tool_calls.append(record)
        label, summary, started = TOOL_LABELS.get(name, name), self.describe_call(name, call["function"]["arguments"]), time.monotonic()
        self.job.emit("tool_started", f"{label}：{summary}" if summary else label, toolCallId=call["id"], name=name, label=label, summary=summary)
        try:
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError
            signature = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            prior = self.action_counts.get(signature, 0)
            self.action_counts[signature] = prior + 1
            # full 允许带覆盖进展的接续；其他同参动作反复执行不增加证据。
            if prior >= 2 and not (name in {"read_document", "read_web_document"} and arguments.get("mode", "full") == "full"):
                raise ToolError("REPEATED_ACTION", "同一动作已多次返回，请使用已有结果或改查，避免重复循环。")
            record["arguments"] = arguments
            result = {"status": "completed", "data": await self.dispatch(name, arguments)}
            record["status"] = "completed"
        except (ValueError, ToolError, ModelServiceError) as error:
            if isinstance(error, ModelServiceError) and error.code not in {
                "MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_UPSTREAM_ERROR"
            }:
                raise
            code = error.code if isinstance(error, (ToolError, ModelServiceError)) else "INVALID_TOOL_ARGUMENTS"
            details = error.details if isinstance(error, ToolError) else {}
            if isinstance(error, ValidationError):
                # 告诉模型哪里不合规（字段与规则，不回显输入），避免同一错误参数反复重试。
                details = {"problems": [".".join(map(str, e["loc"])) + ": " + e["msg"] for e in error.errors()[:5]]}
            result = {
                "status": "failed",
                "error": {
                    "code": code,
                    "message": error.message if isinstance(error, (ToolError, ModelServiceError)) else "参数未通过工具校验。",
                    "details": details,
                },
            }
            record.update(status="failed", errorCode=code)
        record["finishedAt"] = now()
        self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
        outcome = self.describe_result(name, result)
        self.job.emit(
            "tool_finished",
            f"{label}{'完成' if record['status'] == 'completed' else '未完成'}：{outcome}",
            toolCallId=call["id"],
            name=name,
            label=label,
            status=record["status"],
            result=outcome,
            durationMs=round((time.monotonic() - started) * 1000),
        )
        self.checkpoint()

    def document_title(self, identifier):
        document = self.sources.get(identifier) or self.discovered.get(identifier) or self.web_discovered.get(identifier) or {}
        return document.get("title") or identifier

    def describe_call(self, name, raw_arguments):
        """活动流里的可读参数，如“通读 2025年年度报告”“回查 第13、25页”。参数不合法时返回空。"""
        try:
            a = json.loads(raw_arguments)
        except ValueError:
            return ""
        if not isinstance(a, dict):
            return ""
        pages = lambda value: "、".join(map(str, value)) if isinstance(value, list) else str(value)
        doc = self.document_title(a.get("documentId", ""))
        if name == "search_public_information":
            return a.get("query", "")
        if name == "read_web_document":
            return ("通读 " if a.get("mode", "full") == "full" else "回查 ") + self.document_title(a.get("sourceId", ""))
        if name == "recall_user_memory":
            return a.get("query") or "最近研究经历与确认偏好"
        if name == "remember_user_memory":
            return "保存带用户原话的待确认建议"
        if name == "recall_research_context":
            return f"阅读记录 {self.document_title(a.get('sourceId', ''))} 第{a.get('batch', 0) + 1}批" if a.get("kind") == "reading_notes" else f"已保存报告第{a.get('sectionIndex', 0) + 1}节"
        if name == "find_documents":
            return f"{a.get('company', '')} {pages(a.get('years', []))}年 {pages(a.get('reportTypes', ['年报']))}".strip()
        if name == "read_document":
            mode = a.get("mode", "full")
            if mode == "full":
                return f"通读 {doc}"
            if mode == "search":
                return f"在 {doc} 中查找“{a.get('query', '')}”"
            return f"回查 {doc} 第{pages(a.get('pages') or [a.get('page')])}页"
        if name == "get_market_data":
            return f"{a.get('company', '')} {a.get('startDate', '')} 至 {a.get('endDate', '')}"
        if name in {"inspect_document_pages", "extract_report_data"}:
            return f"{doc} 第{pages(a.get('pages', []))}页"
        if name == "read_research_skill":
            return str(a.get("reference", "")).split("/skills/")[-1]
        return ""

    def describe_result(self, name, result):
        if result["status"] != "completed":
            return result["error"]["message"]
        data = result["data"]
        if name == "search_public_information":
            return f"发现{len(data.get('results', []))}份候选资料（未读）"
        if name == "read_web_document":
            progress = data.get("coverage")
            return f"网页已读{progress['processedCharacters']}字" if progress else f"回查{len(data.get('matches', []))}处原文"
        if name == "recall_user_memory":
            return f"返回{len(data.get('episodes', []))}条研究经历"
        if name == "remember_user_memory":
            return "建议已记录，等待用户确认" if data.get("status") == "suggested" else "已有记录，未重复新增"
        if name == "recall_research_context":
            return "返回已保存的完整阅读笔记" if "recalledNotes" in data else "返回已保存的章节正文"
        if name == "find_documents":
            return f"找到 {len(data.get('documents', []))} 份报告"
        if name == "read_document":
            coverage = data.get("coverage")
            if coverage:
                return f"已处理 {len(coverage['processedPages'])}/{coverage['pageCount']} 页" + ("（复用已读记录）" if data.get("cacheHit") else "")
            if "matches" in data:
                return f"找到 {len(data['matches'])} 处"
            return f"返回 {len(data['pages']) if isinstance(data.get('pages'), list) else 1} 页原文"
        if name == "get_market_data":
            return f"{data.get('metrics', {}).get('tradingDays', '?')} 个交易日"
        if name == "extract_report_data":
            return f"核对 {data.get('verifiedPointCount', 0)} 个财务值、{data.get('segmentPointCount', 0)} 个业务收入值"
        if name == "inspect_document_pages":
            return f"查看 {len(data.get('observations', []))} 页"
        if name == "read_research_skill":
            return f"{len(data.get('files', [])) or len(data.get('content', ''))} " + ("个文件" if "files" in data else "字")
        return "完成"

    async def run(self):
        self.job.status = "running"
        self.job.emit("run_started", "开始研究；模型将选择需要的报告和行情")
        try:
            async with asyncio.timeout(self.limits.max_seconds):
                await self.load_user_memory()
                if not self.recovery or self.method_usage is None:
                    self.job.set_phase("methods", "阶段：阅读研究方法、形成研究计划")
                    await self.prepare_methods()
                    self.checkpoint()
                self.job.set_phase("research", "阶段：取证——查找、阅读与回查资料")
                if self.recovery:
                    # 原任务可能停在一组工具调用的中间；先配齐缺失结果，再继续模型决策。
                    for call in pending_calls(self.messages):
                        await self.run_tool_call(call)
                    await self.refresh_missing_history()
                    self.messages.append({"role": "user", "content": "继续完成原研究。已保存的阅读、方法与底稿继续有效，不要重新通读已完成资料；仅补必要证据（如行情），然后撰写报告。"})
                    if (self.report_candidate or self.writing_state) and self.pending_evidence():
                        self.job.emit('writing_deferred', '旧草稿形成时核心资料未读齐：保留旧版本，先补读，再重新组织正文')
                        self.report_candidate, self.writing_state, self.report_stage = None, None, None
                        self.checkpoint()
                    if self.report_candidate or self.writing_state:
                        assistant = ({"role": "assistant", "content": json.dumps(self.report_candidate, ensure_ascii=False)}
                                     if self.report_candidate else await self.compose())
                        self.messages.append(assistant)
                        if await self.finish(assistant):
                            return
                    elif self.can_budget_finish():
                        self.job.emit("resume_ready_to_write", "证据已完整恢复：直接继续分节写作，不重新通读")
                        assistant = await self.compose()
                        self.messages.append(assistant)
                        if await self.finish(assistant):
                            return
                for step in range(1, self.limits.max_steps + 1):
                    self.steps = step
                    self.check_budget()
                    messages = await self.prepare_context(self.context())
                    if not self.context_wrapup and context_characters(messages) > (
                        self.limits.max_context_characters - self.limits.context_reserve_characters
                    ):
                        self.start_context_wrapup()
                    if self.context_wrapup and self.pending_materials():
                        raise BudgetStop('context_budget_incomplete_evidence')
                    # 收尾写作：不再让模型选工具，用已取得的证据直接撰写（核查不通过时带着诊断再写）。
                    assistant = await self.compose() if self.context_wrapup else await self.decision_turn(messages)
                    self.messages.append(assistant)
                    calls = assistant.get("tool_calls") or []
                    names = [TOOL_LABELS.get(c["function"]["name"], c["function"]["name"]) for c in calls]
                    self.job.emit(
                        "assistant_message", "模型决定：" + "、".join(names) if calls else "模型认为证据已够，进入写作", tools=names
                    )
                    if not calls:
                        if await self.finish(assistant):
                            return
                        continue
                    for call in calls:
                        await self.run_tool_call(call)
                raise BudgetStop("step_budget")
        except (BudgetStop, TimeoutError) as error:
            reason = str(error) or "time_budget"
            # 取证预算提前触发，写作预算仍可用；有完整基本证据时主动收尾，而非一律返回空报告。
            if reason in {"research_call_budget", "research_token_budget", "step_budget"} and self.can_budget_finish():
                try:
                    for call in pending_calls(self.messages):
                        self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({
                            "status": "failed", "error": {"code": "RESEARCH_BUDGET_RESERVED", "message": "取证预算已用完，保留调用空间撰写报告。"}})})
                    self.context_wrapup = True
                    self.job.emit("budget_wrapup", "取证预算接近上限，使用预留调用空间完成正文、表格和复核", reason=reason)
                    for _ in range(2):
                        assistant = await self.compose()
                        self.messages.append(assistant)
                        if await self.finish(assistant):
                            return
                except (BudgetStop, ModelServiceError) as final_error:
                    reason = final_error.code if isinstance(final_error, ModelServiceError) else str(final_error)
            self.job.report = self.report(reason=reason)
            self.job.status = "partial"
            self.job.emit("run_partial", "已保留部分结果：" + reason)
        except asyncio.CancelledError:
            self.job.status = "cancelled"
            self.job.report = self.report(reason="cancelled")
            self.job.emit("run_cancelled", "研究已停止，已完成的模型调用可能已计费")
        except ModelServiceError as error:
            self.job.status = "failed"
            self.job.error = {"code": error.code, "message": error.message}
            self.job.report = self.report(reason=error.code)
            self.job.emit("run_failed", error.message)
        except Exception:
            # 堆栈写入服务日志（.runtime/logs/agent.err.log）便于排查；网页与模型只看到受控错误。
            logger.exception("research run %s failed", self.job.task_id)
            self.job.status = "failed"
            self.job.error = {"code": "RESEARCH_FAILED", "message": "研究执行失败，已保留完成范围，请检查后重试。"}
            self.job.report = self.report(reason="execution_error")
            self.job.emit("run_failed", "研究执行失败")
        finally:
            self.job.finished_at = now()
            for record in self.job.tool_calls:
                if record["status"] == "running":
                    record.update(status="interrupted", finishedAt=now())
            self.checkpoint()
            if self.job.recorder:
                await self.persist_outcome()

    def can_budget_finish(self):
        return bool(self.coverage) and not self.pending_evidence() and all(reading_complete(c) for c in self.coverage.values()) and (
            not self.job.request.include_market or self.market_data is not None
        ) and (not self.job.request.include_current_period or self.current_period_checked)

    async def persist_outcome(self):
        """研究结束（完成、部分、失败或取消）：记报告与结束状态，再把剩余条目提交给会话存储。"""
        recorder = self.job.recorder
        if self.job.report:
            recorder.add("report", reportId=self.job.task_id, reportVersion=1, report=self.job.report)
        recorder.add(
            "run_state",
            status=self.job.status,
            finishedAt=self.job.finished_at,
            modelCalls=self.job.model_calls,
            usage=self.job.usage,
            error=self.job.error,
        )
        await recorder.close()
