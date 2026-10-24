"""研究 Agent 主循环：模型选工具 → 程序校验执行 → 结果回传 → 补查或写报告。参考 Pi 与 DeepSeek 工具协议。

AgentRunner 由几部分组成，各自拥有一块运行状态：
- runner_reading.ReadingMixin：来源登记、完整分批阅读、按页/关键词回查
- runner_evidence.EvidenceMixin：原页视觉核对、正文取数、财务/业务底稿
- runner_methods.MethodMixin：按问题与预兆选择原版方法并形成研究计划
- runner_omens.OmenMixin：预兆规格进入上下文、写作要求与覆盖自检（M1-4）
- runner_report.ReportMixin：报告写作、程序核查、复核与最终结构
本文件只保留循环本身：预算、模型调用、工具分派、上下文组装。
"""

import asyncio
from dataclasses import dataclass, replace
import json
import logging
import time

from pydantic import ValidationError

from app.core.agent_prompts import initial_messages
from app.core.config import ModelServiceError
from app.core.research_skills import SkillArguments, load_research_skill, read_reference
from app.schemas.agent import AgentReadArguments
from app.schemas.financial import ExtractArguments, InspectArguments
from app.services.model_client import complete_turn
from app.services.runner_evidence import EvidenceMixin
from app.services.runner_methods import MethodMixin
from app.services.runner_omens import OmenMixin
from app.services.runner_reading import ReadingMixin
from app.services.runner_report import ReportMixin, compact_financial, strip_quotes
from app.services.runtime import BudgetStop, RunLimits, now
from app.tools.contracts import FindArguments, ToolError
from app.tools.documents import write_json
from app.tools.market import MarketArguments

__all__ = ["AgentRunner", "BudgetStop", "RunLimits", "declarations", "now"]

logger = logging.getLogger("path_of_market.agent")

TOOL_SPECS = (
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


def declarations():
    return [
        {"type": "function", "function": {"name": name, "description": description, "parameters": schema.model_json_schema(by_alias=True)}}
        for name, description, schema in TOOL_SPECS
    ]


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
        projected = json.dumps(body, ensure_ascii=False)
        pages = page_texts(data)
        long_pages = [p for p in pages if len(p["text"]) > 700]
        for page in long_pages:
            page["text"] = page["text"][:700]
            page["contextProjection"] = "历史回查原文的有限摘录；完整页仍可通过read_document回查。"
        excerpt = json.dumps(body, ensure_ascii=False) if long_pages else projected
        return cls(content, projected, excerpt, bool(pages))


class AgentRunner(ReadingMixin, EvidenceMixin, MethodMixin, OmenMixin, ReportMixin):
    def __init__(self, job, tools, settings, *, limits=None, completion=None):
        self.job, self.tools, self.settings = job, tools, settings
        self.limits = limits or RunLimits()
        self.completion = completion or complete_turn
        self.began = time.monotonic()
        self.messages = initial_messages(job.request)
        self.skill = load_research_skill()
        self.steps = 0
        self.invalid_finals = 0
        self.review_outcome = None
        self.context_wrapup = False  # 上下文接近上限后不再取证，直接写作
        self.wrapup_gaps = []  # 收尾写作时无法再补的证据缺口，写入报告局限
        self.action_counts = {}
        # 工具消息的上下文投影缓存（tool_call_id → ToolView）
        self.tool_views = {}
        # 阅读（runner_reading）
        self.notes, self.sources, self.coverage = {}, {}, {}
        # 资料发现与当期报告
        self.discovered = {}
        self.current_period_checked = False
        self.required_current = None
        self.current_period_gap = None
        self.market_data = None
        # 数值证据（runner_evidence）
        self.visual_readings, self.extraction_readings = [], []
        self.financial_points, self.financial_gaps = [], []
        self.segment_points, self.business_gaps = [], []
        self.financial_checked, self.detail_checked = set(), set()
        # 方法计划（runner_methods）
        self.method_usage = None

    @property
    def uses_real_provider(self):
        return self.completion is complete_turn

    def declarations(self):
        return declarations()

    # ---- 预算与模型调用 -------------------------------------------------

    def check_budget(self):
        if self.job.cancel_requested:
            raise asyncio.CancelledError
        if time.monotonic() - self.began >= self.limits.max_seconds:
            raise BudgetStop("time_budget")
        if self.job.model_calls >= self.limits.max_model_calls:
            raise BudgetStop("model_call_budget")
        if self.job.usage.get("total_tokens", 0) >= self.limits.max_tokens:
            raise BudgetStop("token_budget")

    def record_usage(self, usage):
        for key, value in usage.items():
            self.job.usage[key] = self.job.usage.get(key, 0) + value
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            self.job.usage["total_tokens"] = self.job.usage.get("total_tokens", 0) + usage["prompt_tokens"] + usage["completion_tokens"]

    async def model(self, messages, *, tool_specs=None, reading=False, visual=False, report=False, write_only=False):
        """write_only=True：发送同一组工具定义但禁止调用（tool_choice=none）并要求 JSON，让写作请求与研究轮次共享缓存前缀。"""
        self.check_budget()
        if context_characters(messages) > self.limits.max_context_characters:
            raise BudgetStop("context_budget")
        self.job.model_calls += 1
        self.job.emit(
            "model_started",
            "查看PDF原页图像" if visual else "阅读原文" if reading else "判断下一步研究动作",
            modelCall=self.job.model_calls,
        )
        # 多预兆报告允许更长：每个预兆追加输出预算，不为篇幅牺牲预兆分析。
        report_tokens = self.limits.report_tokens + 2500 * len(self.job.request.omens)
        output_tokens = min(1800, self.settings.max_tokens) if reading else report_tokens if report else 6500
        # 累计预算以供应商实际用量记账，下一调用前检查；单次也有明确输出/时间上限。
        # 写作/复核输出整篇报告，使用单独的等待上限；研究轮次仍用较短上限。
        settings = replace(self.settings, timeout_seconds=self.settings.report_timeout_seconds) if report else self.settings
        try:
            options = {"tool_choice": "none", "json_mode": True} if write_only else {"json_mode": not bool(tool_specs)}
            message, usage = await self.completion(settings, messages, tools=tool_specs, max_tokens=output_tokens, **options)
        except ModelServiceError as error:
            self.record_usage(getattr(error, "usage", {}))
            raise
        self.record_usage(usage)
        self.job.emit("model_finished", "模型调用完成", modelCall=self.job.model_calls, usage=usage)
        return message

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
        result = await self.raw_tool("find_documents", args.model_dump(by_alias=True))
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
        return [g for g in dict.fromkeys(self.financial_gaps + self.business_gaps + self.financial_data()["gaps"]) if "冲突" in g]

    def tool_view(self, message):
        """取工具消息的投影；同一条消息只解析一次（内容变化时重建）。"""
        view = self.tool_views.get(message["tool_call_id"])
        if view is None or view.content != message["content"]:
            view = self.tool_views[message["tool_call_id"]] = ToolView.build(message["content"])
        return view

    def context(self):
        """主循环每轮请求的消息。self.messages 保留完整工具结果；这里只做有来源的有限投影。

        为了前缀缓存：历史消息的投影只取决于消息本身（与轮次无关），当前底稿和剩余轮数放在最后。
        """
        views = [self.tool_view(m) if m.get("role") == "tool" else None for m in self.messages]
        # 最近两次按页回查保留原文；更早结果保留来源和有限摘录，完整内容仍可回查。
        recent_pages = set([i for i, v in enumerate(views) if v and v.has_pages][-2:])
        messages = []
        for i, (message, view) in enumerate(zip(self.messages, views)):
            if view is None:
                messages.append(dict(message))
            else:
                content = view.projected if not view.has_pages or i in recent_pages else view.excerpt
                messages.append({**message, "content": content})
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
            messages.append({"role": "user", "content": json.dumps(state, ensure_ascii=False)})
        messages.append(
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
        )
        return messages

    # ---- 主循环 ---------------------------------------------------------

    def start_context_wrapup(self):
        """决策上下文接近上限：停止取证、转入写作，而不是等越过上限后只留部分结果。完整历史压缩按 M2-5 实施。"""
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
        try:
            if json.loads(assistant.get("content") or "{}") == {"ready": True}:
                assistant = await self.compose()
            content = self.validate_content(assistant)
            content = await self.review(content)
            self.job.report = self.report(content)
            self.job.status = "completed"
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
            self.job.emit("report_validation_failed", "报告需修正：" + diagnostics[:300])
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
        self.job.emit("tool_started", "执行工具：" + name, toolCallId=call["id"], name=name)
        try:
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError
            signature = name + json.dumps(arguments, sort_keys=True, ensure_ascii=False)
            prior = self.action_counts.get(signature, 0)
            self.action_counts[signature] = prior + 1
            # full 允许带覆盖进展的接续；其他同参动作反复执行不增加证据。
            if prior >= 2 and not (name == "read_document" and arguments.get("mode", "full") == "full"):
                raise ToolError("REPEATED_ACTION", "同一动作已多次返回，请使用已有结果或改查，避免重复循环。")
            record["arguments"] = arguments
            result = {"status": "completed", "data": await self.dispatch(name, arguments)}
            record["status"] = "completed"
        except (ValueError, ToolError) as error:
            code = error.code if isinstance(error, ToolError) else "INVALID_TOOL_ARGUMENTS"
            details = error.details if isinstance(error, ToolError) else {}
            if isinstance(error, ValidationError):
                # 告诉模型哪里不合规（字段与规则，不回显输入），避免同一错误参数反复重试。
                details = {"problems": [".".join(map(str, e["loc"])) + ": " + e["msg"] for e in error.errors()[:5]]}
            result = {
                "status": "failed",
                "error": {
                    "code": code,
                    "message": error.message if isinstance(error, ToolError) else "参数未通过工具校验。",
                    "details": details,
                },
            }
            record.update(status="failed", errorCode=code)
        record["finishedAt"] = now()
        self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
        self.job.emit(
            "tool_finished",
            name + (" 完成" if record["status"] == "completed" else " 未完成"),
            toolCallId=call["id"],
            status=record["status"],
        )

    async def run(self):
        self.job.status = "running"
        self.job.emit("run_started", "开始研究；模型将选择需要的报告和行情")
        try:
            async with asyncio.timeout(self.limits.max_seconds):
                await self.prepare_methods()
                for step in range(1, self.limits.max_steps + 1):
                    self.steps = step
                    self.check_budget()
                    messages = self.context()
                    if not self.context_wrapup and context_characters(messages) > (
                        self.limits.max_context_characters - self.limits.context_reserve_characters
                    ):
                        self.start_context_wrapup()
                    # 收尾写作：不再让模型选工具，用已取得的证据直接撰写（核查不通过时带着诊断再写）。
                    assistant = await self.compose() if self.context_wrapup else await self.model(messages, tool_specs=self.declarations())
                    self.messages.append(assistant)
                    calls = assistant.get("tool_calls") or []
                    self.job.emit("assistant_message", "模型提出研究动作" if calls else "模型提交研究报告")
                    if not calls:
                        if await self.finish(assistant):
                            return
                        continue
                    for call in calls:
                        await self.run_tool_call(call)
                raise BudgetStop("step_budget")
        except (BudgetStop, TimeoutError) as error:
            reason = str(error) or "time_budget"
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
