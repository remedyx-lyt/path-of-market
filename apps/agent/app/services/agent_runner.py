"""模型选工具的循环 + 文档完整分批阅读流程；参考 Pi 和 DeepSeek 工具协议。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from hashlib import sha256
import time
from uuid import uuid4

from app.core.agent_prompts import READ_SYSTEM, REVIEW_SYSTEM, initial_messages
from app.core.config import ModelServiceError
from app.schemas.agent import AgentContent, AgentReadArguments, ReadingNote
from app.services.model_client import complete_turn
from app.tools.contracts import FindArguments, ToolError
from app.tools.market import MarketArguments
from app.tools.documents import write_json


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 18
    max_model_calls: int = 72
    max_tokens: int = 1_200_000
    max_seconds: float = 1200
    max_context_characters: int = 160000
    report_tokens: int = 6500
    read_characters: int = 26000


class BudgetStop(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def declarations():
    specs = [
        ("find_documents", "从公司/会计年度/截止日找官方完整报告，支持年报、半年报、一季报和三季报；不需要上传。", FindArguments),
        ("read_document", "完整读取选定 PDF（full 默认），内部下载、分批阅读并返回带页码要点和覆盖；page/search 仅复查。", AgentReadArguments),
        ("get_market_data", "获取股票区间日线，返回不复权实际价格和后复权计算的变化/回撤/波动/月度表现。", MarketArguments),
    ]
    return [{"type": "function", "function": {"name": name, "description": description,
            "parameters": schema.model_json_schema(by_alias=True)}} for name, description, schema in specs]


class AgentRunner:
    def __init__(self, job, tools, settings, *, limits=None, completion=None):
        self.job, self.tools, self.settings = job, tools, settings
        self.limits = limits or RunLimits()
        self.completion = completion or complete_turn
        self.began = time.monotonic()
        self.messages = initial_messages(job.request)
        self.notes = {}
        self.sources = {}
        self.coverage = {}
        self.market_data = None
        self.steps = 0
        self.action_counts = {}
        self.current_period_checked = False
        self.required_current = None
        self.current_period_gap = None
        self.discovered = {}

    def check_budget(self):
        if self.job.cancel_requested:
            raise asyncio.CancelledError
        if time.monotonic() - self.began >= self.limits.max_seconds:
            raise BudgetStop("time_budget")
        if self.job.model_calls >= self.limits.max_model_calls:
            raise BudgetStop("model_call_budget")
        if self.job.usage.get("total_tokens", 0) >= self.limits.max_tokens:
            raise BudgetStop("token_budget")

    async def model(self, messages, *, tool_specs=None, reading=False):
        self.check_budget()
        if len(json.dumps(messages, ensure_ascii=False)) > self.limits.max_context_characters:
            raise BudgetStop("context_budget")
        self.job.model_calls += 1
        self.job.emit("model_started", "阅读原文" if reading else "判断下一步研究动作", modelCall=self.job.model_calls)
        output_tokens = min(1800, self.settings.max_tokens) if reading else self.limits.report_tokens
        # 累计预算以供应商实际用量记账，下一调用前检查；单次也有明确输出/时间上限。
        message, usage = await self.completion(self.settings, messages, tools=tool_specs,
                                               max_tokens=output_tokens, json_mode=not bool(tool_specs))
        for key, value in usage.items():
            self.job.usage[key] = self.job.usage.get(key, 0) + value
        if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            self.job.usage["total_tokens"] = self.job.usage.get("total_tokens", 0) + usage["prompt_tokens"] + usage["completion_tokens"]
        self.job.emit("model_finished", "模型调用完成", modelCall=self.job.model_calls)
        return message

    async def raw_tool(self, name, arguments):
        self.check_budget()
        result = await asyncio.to_thread(self.tools.execute, name, arguments)
        if result["status"] != "completed":
            error = result["error"]
            raise ToolError(error["code"], error["message"], error.get("details"))
        return result["data"]

    def source(self, metadata):
        identifier = metadata["documentId"]
        if identifier not in self.sources:
            self.sources[identifier] = {"sourceId": identifier, "kind": "document", "title": metadata["title"],
                "url": metadata["sourceUrl"], "publishedAt": metadata["publishedAt"], "pageCount": metadata["pageCount"],
                "fiscalYear": metadata["fiscalYear"], "reportType": metadata.get("reportType", "annual")}
            self.coverage[identifier] = {"sourceId": identifier, "pageCount": metadata["pageCount"],
                "returnedCharacters": 0, "processedCharacters": 0, "processedPages": [], "emptyTextPages": [],
                "textComplete": False, "batches": 0}
        self.job.sources = list(self.sources.values())
        self.job.coverage = list(self.coverage.values())
        return identifier

    async def read(self, arguments):
        args = AgentReadArguments.model_validate(arguments)
        metadata = await asyncio.to_thread(self.tools.store.metadata, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料披露时间晚于研究截止日。")
        downloaded = await self.raw_tool("fetch_document", {"documentId": args.document_id})
        identifier = self.source(downloaded["document"])
        if args.mode != "full":
            if not self.coverage[identifier]["textComplete"]:
                raise ToolError("FULL_READ_REQUIRED", "此资料尚未完成通读。请使用 mode=full，程序会从上次成功处理的位置接续；单页或关键词不能替代。")
            if args.mode == "page":
                return await self.raw_tool("read_document", {"documentId": identifier, "page": args.page})
            if not args.query.strip():
                raise ToolError("INVALID_TOOL_ARGUMENTS", "关键词回查需要 query。")
            return await self.raw_tool("search_document", {"documentId": identifier, "query": args.query})
        if self.coverage[identifier]["textComplete"]:
            return {"sourceId": identifier, "notes": self.notes[identifier], "coverage": self.coverage[identifier], "cacheHit": True}
        # 失败后的补读从已处理游标接续；不把先前只返回但模型失败的批次算成已读。
        cursor = self.coverage[identifier].get("nextCursor", {"startPage": 1, "offset": 0})
        self.notes.setdefault(identifier, [])
        while cursor is not None:
            self.check_budget()
            batch = await self.raw_tool("read_document_batch", {"documentId": identifier, **cursor,
                "maxPages": 20, "maxCharacters": self.limits.read_characters})
            progress = self.coverage[identifier]
            progress["returnedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            self.job.emit("reading_batch", f"{metadata['title']}：阅读第 {batch['pages'][0]['page']}–{batch['pages'][-1]['page']} 页",
                          sourceId=identifier, firstPage=batch["pages"][0]["page"], lastPage=batch["pages"][-1]["page"])
            reading_task = {"question": self.job.request.question, "sourceId": identifier,
                            "title": metadata["title"], "pages": batch["pages"]}
            reading_messages = [{"role": "system", "content": READ_SYSTEM},
                {"role": "user", "content": json.dumps(reading_task, ensure_ascii=False)}]
            # 这是派生阅读缓存，不是会话持久化。必须命中原文件/原文/问题/模型/提示版本。
            cache_key = sha256(json.dumps({"messages": reading_messages, "model": self.settings.model,
                "sha256": downloaded["document"]["sha256"]}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            cache_path = self.tools.store.root / "reading-notes" / (cache_key + ".json")
            note, origin = None, None
            allowed = {p["page"] for p in batch["pages"]}
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    candidate = ReadingNote.model_validate(cached["note"])
                    if all(set(f.pages) <= allowed for f in candidate.facts):
                        note, origin = candidate, cached.get("runId")
                except (ValueError, KeyError, TypeError, OSError):
                    pass
            for attempt in range(2 if note is None else 0):
                message = await self.model(reading_messages, reading=True)
                try:
                    candidate = ReadingNote.model_validate_json(message["content"])
                    if any(not set(fact.pages) <= allowed for fact in candidate.facts):
                        raise ValueError("引用了当前批次之外的物理页码")
                    note = candidate
                    write_json(cache_path, {"note": note.model_dump(), "runId": self.job.task_id, "processedAt": now(),
                                           "sourceId": identifier, "model": self.settings.model})
                    break
                except ValueError as error:
                    if attempt == 1:
                        raise ToolError("READING_NOTE_INVALID", "本批阅读记录未通过校验；继续 full 可接续重试，本批尚未计入覆盖。",
                            {"allowedPages": sorted(allowed), "nextCursor": cursor}) from None
                    # 只修复一次，不能把结构失败当成全文已读；不把验证异常里的原文/堆栈塞入结果。
                    reading_messages.extend([message, {"role": "user", "content":
                        "上次记录未通过校验。请修正为 summary 字符串、最多8个 facts（每个 text 字符串和 pages 整数数组）、最多6个 gaps 字符串。"
                        + "只能引用这些物理页码：" + json.dumps(sorted(allowed)) + "。原文中其他引用页码不能当作本批来源。"}])
            if origin:
                self.job.emit("reading_cache_reused", "复用同一原文与问题的已验证阅读记录", sourceId=identifier, originRunId=origin)
            self.notes[identifier].append(note.model_dump())
            progress["processedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            progress["processedPages"] = sorted(set(progress["processedPages"]) | {p["page"] for p in batch["pages"] if p["pageComplete"]})
            progress["emptyTextPages"] = sorted(set(progress["emptyTextPages"]) | {p["page"] for p in batch["pages"] if p["textStatus"] != "extracted"})
            progress["batches"] += 1
            cursor = batch["nextCursor"]
            progress["nextCursor"] = cursor
            progress["textComplete"] = cursor is None and len(progress["processedPages"]) == progress["pageCount"] and not progress["emptyTextPages"]
            self.job.emit("reading_processed", f"{metadata['title']}：已处理 {len(progress['processedPages'])}/{progress['pageCount']} 页文本",
                          sourceId=identifier)
        return {"sourceId": identifier, "notes": self.notes[identifier], "coverage": self.coverage[identifier],
                "limitations": ["已处理 PDF 可提取文字，未进行图片视觉理解或扫描 OCR。"]}

    async def dispatch(self, name, arguments):
        if name == "find_documents":
            args = FindArguments.model_validate(arguments)
            if args.as_of_date != self.job.request.as_of_date.isoformat():
                raise ToolError("CUTOFF_MISMATCH", "查询应使用任务的研究截止日期。")
            result = await self.raw_tool(name, args.model_dump(by_alias=True))
            if self.job.request.include_current_period and not self.current_period_checked:
                self.current_period_checked = True
                year = self.job.request.as_of_date.year
                supplement_args = {"company": args.company, "years": [year], "asOfDate": args.as_of_date,
                                   "reportTypes": ["q1", "interim", "q3"]}
                self.job.emit("current_period_lookup", f"核对 {year} 年已披露的最新定期报告")
                try:
                    supplement = await self.raw_tool(name, supplement_args)
                    latest = [d for d in supplement["documents"] if d["preferred"]]
                    if latest:
                        self.required_current = max(latest, key=lambda d: d["publishedAt"])
                    else:
                        self.current_period_gap = f"当前来源未找到截至 {args.as_of_date} 已披露的 {year} 年季报/半年报。"
                    merged = {d["documentId"]: d for d in result["documents"] + supplement["documents"]}
                    result["documents"] = list(merged.values())
                    result["currentPeriodQuery"] = {"arguments": supplement_args, "queryComplete": supplement["queryComplete"],
                                                     "requiredLatestDocument": self.required_current}
                except ToolError as error:
                    self.current_period_gap = "当年最新报告查询未完成：" + error.message
                if self.current_period_gap:
                    result["gaps"].append(self.current_period_gap)
            self.discovered.update({d["documentId"]: d for d in result["documents"]})
            return result
        if name == "read_document":
            return await self.read(arguments)
        if name == "get_market_data":
            args = MarketArguments.model_validate(arguments)
            if args.end_date > self.job.request.as_of_date.isoformat():
                raise ToolError("AFTER_RESEARCH_CUTOFF", "行情结束日期晚于研究截止日。")
            data = await self.raw_tool(name, args.model_dump(by_alias=True))
            self.market_data = data
            identifier = "market-" + data["company"]["code"]
            self.sources[identifier] = {"sourceId": identifier, "kind": "market", "title": data["company"]["name"] + "历史日线（" + data["provider"] + "）",
                "url": data["sourceUrls"][0], "publishedAt": data["actualEnd"], "retrievedAt": data["retrievedAt"]}
            self.job.sources = list(self.sources.values())
            return {k: v for k, v in data.items() if k != "series"} | {"sourceId": identifier}
        raise ToolError("UNKNOWN_TOOL", "此工具未向研究模型开放。")

    def context(self):
        # 全文由每批模型完整处理，主循环使用阅读记录；旧工具大结果用来源入口与摘要投影。
        messages = [dict(m) for m in self.messages]
        for message in messages:
            if message.get("role") == "tool" and len(message.get("content", "")) > 50000:
                body = json.loads(message["content"])
                if body.get("data", {}).get("notes"):
                    body["data"] = {"sourceId": body["data"]["sourceId"], "coverage": body["data"]["coverage"],
                                    "notes": body["data"]["notes"]}
                    message["content"] = json.dumps(body, ensure_ascii=False)
        return messages

    def validate_content(self, message):
        content = AgentContent.model_validate_json(message["content"])
        if not self.sources:
            raise ValueError("尚未取得证据")
        if not self.coverage or any(not c["textComplete"] for c in self.coverage.values()):
            raise ValueError("选定报告尚未完整处理可提取文字，请继续 full 阅读或明确停止缺口")
        if self.job.request.include_market and self.market_data is None:
            raise ValueError("本任务要求行情分析，尚未取得行情")
        if self.job.request.include_current_period and not self.current_period_checked:
            raise ValueError("尚未查找截止年度最新已披露的定期报告")
        if self.required_current and not self.coverage.get(self.required_current["documentId"], {}).get("textComplete"):
            raise ValueError("当年最新已披露报告尚未通读，请以 mode=full 阅读 " + self.required_current["documentId"] + "：" + self.required_current["title"])
        citations = [c for section in content.sections for c in section.citations]
        if not citations:
            raise ValueError("最终章节需要引用实际来源")
        for citation in citations:
            source = self.sources.get(citation.source_id)
            if source is None or source["kind"] == "document" and (citation.page is None or citation.page not in self.coverage[citation.source_id]["processedPages"]):
                raise ValueError("引用必须指向本次实际处理的来源和页码")
        return content

    async def review(self, content):
        self.job.emit("report_review", "核对报告文字、资料范围与行情计算口径")
        payload = {"candidate": content.model_dump(by_alias=True), "asOfDate": self.job.request.as_of_date.isoformat(),
                   "discoveredDocuments": list(self.discovered.values()), "processedSources": list(self.sources.values()),
                   "coverage": list(self.coverage.values()),
                   "market": {k: v for k, v in (self.market_data or {}).items() if k != "series"}}
        message = await self.model([{"role": "system", "content": REVIEW_SYSTEM},
                                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        return self.validate_content(message)

    def report(self, content=None, reason="research_completed"):
        partial = reason != "research_completed"
        if content is None:
            sections = [{"heading": "本次完成的工作", "content": f"执行 {self.steps} 轮研究动作，模型调用 {self.job.model_calls} 次。请结合来源与阅读覆盖查看已完成范围。", "citations": []},
                        {"heading": "未完成与停止原因", "content": f"停止原因：{reason}。保留已获取的来源、行情和阅读覆盖；未完成完整报告，不应视作最终研究结论。", "citations": []}]
            for identifier, notes in self.notes.items():
                if notes:
                    sections.append({"heading": self.sources[identifier]["title"] + "：已读部分记录",
                                     "content": "\n".join(n["summary"] for n in notes), "citations": []})
            content = {"title": self.job.request.target + "研究（未完成）", "summary": "研究已停止，以下仅保留实际完成范围与资料。", "sections": sections}
        else:
            content = content.model_dump(by_alias=True)
        limitations = ["本阶段只处理 PDF 可提取文字，图片、扫描 OCR 和复杂表格结构尚未完整识别。",
                       "会话和任务目前保存在运行进程内，重启后不能恢复；持久化按 M2 实施。"]
        if self.market_data:
            limitations += self.market_data["limitations"]
        if self.current_period_gap:
            limitations.append(self.current_period_gap)
        if partial:
            limitations.insert(0, "本次研究未完成：" + reason)
        return {**self.job.request.model_dump(mode="json", by_alias=True), **content,
                "mode": "agent", "isMock": False, "evidenceStatus": "partial" if partial else "retrieved",
                "sources": list(self.sources.values()), "toolCalls": self.job.tool_calls,
                "coverage": list(self.coverage.values()), "marketData": self.market_data,
                "limitations": limitations, "run": {"taskId": self.job.task_id, "sessionId": self.job.session_id,
                    "status": "partial" if partial else "completed", "startedAt": self.job.started_at, "finishedAt": now(),
                    "stopReason": reason, "model": self.settings.model, "modelCalls": self.job.model_calls,
                    "usage": self.job.usage, "steps": self.steps}}

    async def run(self):
        self.job.status = "running"
        self.job.emit("run_started", "开始研究；模型将选择需要的报告和行情")
        invalid_finals = 0
        try:
            async with asyncio.timeout(self.limits.max_seconds):
                for self.steps in range(1, self.limits.max_steps + 1):
                    self.check_budget()
                    assistant = await self.model(self.context(), tool_specs=declarations())
                    self.messages.append(assistant)
                    self.job.emit("assistant_message", "模型提出研究动作" if assistant.get("tool_calls") else "模型提交研究报告")
                    calls = assistant.get("tool_calls") or []
                    if not calls:
                        try:
                            content = self.validate_content(assistant)
                            content = await self.review(content)
                            self.job.report = self.report(content)
                            self.job.status = "completed"
                            self.job.emit("run_completed", "研究完成，报告与证据已返回")
                            return
                        except ValueError as error:
                            invalid_finals += 1
                            if invalid_finals >= 3:
                                raise BudgetStop("incomplete_evidence_or_report")
                            self.messages.append({"role": "user", "content": "报告尚未通过程序核查：" + str(error)[:500] + "。请继续取得证据或修正 JSON 和引用。"})
                            continue
                    for call in calls:
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
                            data = await self.dispatch(name, arguments)
                            result = {"status": "completed", "data": data}
                            record["status"] = "completed"
                        except (ValueError, ToolError) as error:
                            code = error.code if isinstance(error, ToolError) else "INVALID_TOOL_ARGUMENTS"
                            result = {"status": "failed", "error": {"code": code,
                                      "message": error.message if isinstance(error, ToolError) else "参数未通过工具校验。",
                                      "details": error.details if isinstance(error, ToolError) else {}}}
                            record.update(status="failed", errorCode=code)
                        record["finishedAt"] = now()
                        self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                              "content": json.dumps(result, ensure_ascii=False)})
                        self.job.emit("tool_finished", name + (" 完成" if record["status"] == "completed" else " 未完成"),
                                      toolCallId=call["id"], status=record["status"])
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
            self.job.status = "failed"
            self.job.error = {"code": "RESEARCH_FAILED", "message": "研究执行失败，已保留完成范围，请检查后重试。"}
            self.job.report = self.report(reason="execution_error")
            self.job.emit("run_failed", "研究执行失败")
        finally:
            self.job.finished_at = now()
            for record in self.job.tool_calls:
                if record["status"] == "running":
                    record.update(status="interrupted", finishedAt=now())
