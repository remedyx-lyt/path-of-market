"""M2-4：当前父链上的报告对话，复用研究工具/证据，追加修订版本，不改旧行。

采用 Pi 的树形会话与运行消息/模型上下文分离；本项目的章节补丁、截止日和证据校验为业务适配。
"""
import asyncio
from copy import deepcopy
import json
import logging
import os
import re
import time
from uuid import UUID
from urllib.request import urlopen

from app.core.config import ModelServiceError
from app.schemas.agent import AgentResearchRequest
from app.schemas.agent import Citation
from app.schemas.discussion import FollowupAnswer
from app.services.agent_runner import AgentRunner, context_characters
from app.services.discussion_context import answer_history, partial_answer, report_view, saved_supplement, select_history
from app.services.research_recovery import checkpoint_path, legacy_recovery, load_recovery, pending_calls, recovery_error
from app.services.runtime import BudgetStop, RunLimits, now
from app.services.reading_coverage import reading_complete
from app.services.session_recorder import DEFAULT_URL, RecordedMessages, SessionRecorder

logger = logging.getLogger("path_of_market.discussion")


class SupplementRequired(ValueError):
    """缺少本次补查证据，需要继续工具循环，不是格式修正。"""


def load_entries(task_id):
    base = (os.environ.get("SESSION_STORE_URL") or DEFAULT_URL).rstrip("/")
    try:
        with urlopen(f"{base}/runs/{UUID(task_id)}", timeout=10) as response:
            return json.load(response)["entries"]
    except (OSError, ValueError, KeyError):
        raise recovery_error("无法读取已保存的研究会话，未启动模型调用。") from None


def branch(entries, leaf):
    nodes = {e["id"]: e for e in entries if e.get("type") != "session"}
    chain, seen = [], set()
    while leaf:
        if leaf in seen or leaf not in nodes:
            raise recovery_error("所选对话节点不存在或父链损坏。")
        seen.add(leaf)
        node = nodes[leaf]
        chain.append(node)
        leaf = node.get("parentId")
    return list(reversed(chain))


def prepare_followup(tools, task_id, request):
    entries = load_entries(task_id)
    # 请求重发（含 HTTP 超时后重试）复用同一个任务；重启后也不重复计费。
    existing = next((e for e in entries if e.get("type") == "followup" and e.get("requestId") == str(request.request_id)), None)
    if existing:
        return {"existingTaskId": existing["runId"]}
    chain = branch(entries, str(request.parent_id))
    leaf = chain[-1]
    if leaf["type"] not in {"report", "chat_turn", "followup"}:
        raise recovery_error("请选择一个报告版本或已保存的对话节点。")
    reports = [e for e in chain if e["type"] == "report"]
    if not reports or reports[-1]["report"]["run"]["status"] != "completed":
        raise recovery_error("请先完成或接续研究，再围绕完整报告对话。")
    version = reports[-1]
    try:
        if checkpoint_path(tools, leaf["runId"]).exists():
            recovery = load_recovery(tools, leaf["runId"], allow_completed=True)
        else:
            # JSONL降级也只用所选父链，绝不能读同文件另一个分支的最后一份报告/摘要。
            recovery = legacy_recovery([entries[0], *chain], entries[0]["runId"], allow_completed=True)
            recovery["taskId"] = leaf["runId"]
    except ModelServiceError:
        if leaf["type"] != "followup":
            raise
        # 请求刚落盘便退出时没有新证据检查点，退到这次请求所基于的完整报告。
        recovery = load_recovery(tools, version["runId"], allow_completed=True)
    request_data = entries[0]["request"]
    return {"entries": entries, "recovery": recovery, "request": AgentResearchRequest.model_validate(request_data),
            "base": version, "sessionId": entries[0]["id"],
            "rootTaskId": entries[0]["runId"], "nextVersion": max(e.get("reportVersion", 0) for e in entries) + 1}


class DiscussionRunner(AgentRunner):
    def __init__(self, job, tools, settings, prepared, followup_request, *, completion=None, limits=None):
        # 构造时先恢复证据，再附记录器；历史上下文不再重复写入 JSONL。
        super().__init__(job, tools, settings, recovery={**prepared["recovery"], "messages": []},
                         completion=completion, limits=limits or RunLimits(max_steps=8, max_model_calls=72,
                         report_reserve_calls=4, report_reserve_tokens=40000, max_tokens=1_000_000, max_seconds=900))
        self.prepared, self.followup_request = prepared, followup_request
        self.base = deepcopy(prepared["base"]["report"])
        self.report_candidate, self.report_stage, self.writing_state = None, None, None
        self.action_counts = {}  # 重复动作限制按本次追问计，不沿用上一轮次数
        job.recorder = SessionRecorder(job.session_id, job.task_id)
        job.recorder.last_id = str(followup_request.parent_id)
        job.recorder.add("followup", rootTaskId=prepared["rootTaskId"], requestId=str(followup_request.request_id),
                         parentTurnId=str(followup_request.parent_id), baseVersionId=prepared["base"]["id"],
                         userMessage=followup_request.message, action=followup_request.action)
        for event in job.events:  # 证据恢复发生在记录器附着前，也应进入持久化回放。
            job.recorder.add("event", data=event)
        job.recorder.start()
        chain = branch(prepared["entries"], str(followup_request.parent_id))
        leaf = chain[-1]
        same_failed_question = (leaf.get("type") in {"chat_turn", "followup"} and leaf.get("status") != "completed"
                                and leaf.get("userMessage") == followup_request.message)
        if not same_failed_question or self.discussion_source_baseline is None:
            # 失败重试沿用原问题基线；旧检查点首次迁移可复用已补查的资料。
            self.discussion_source_baseline = sorted({s["sourceId"] for s in self.base.get("sources", [])}
                | (set() if same_failed_question else set(self.sources)))
        history, ids, migrated = select_history(prepared["recovery"], chain, self.context_prefix_length)
        if migrated:
            self.compaction_state = None  # 原研究摘要的索引边界不再对应聊天历史。
        self.discussion_context_version = 1 if migrated or self.discussion_context_version == 1 else 0
        self.messages = RecordedMessages(history, job.recorder, record_initial=False, entry_ids=ids)
        job.emit("discussion_context_selected", "已载入当前报告、对话父链与已读证据索引；原研究流水按需回查",
                 originalMessages=len(prepared["recovery"]["messages"]), selectedMessages=len(history), migrated=migrated)
        self.record_compaction(restored=True)
        self.messages.append({"role": "user", "content": followup_request.message})
        self.wrapup_reason = None
        self.answer_stream = ""

    async def model(self, messages, **options):
        # 保留原总预算。提前估算下一次输入/输出及两次收尾，避免大请求跨过预留线。
        # 字符估算偏保守，不是供应商tokenizer；最终用量仍按供应商实际返回记账。
        if not options.get("compacting"):
            messages = await self.prepare_context(messages, report=options.get("report", False))
        if not options.get("report"):
            if time.monotonic() - self.began >= self.limits.max_seconds - min(90, self.limits.max_seconds / 5):
                raise BudgetStop("research_time_budget")
            estimated = context_characters(messages) + len(json.dumps(options.get("tool_specs") or []))
            output = self.settings.reading_max_tokens if options.get("reading") else 6500
            final_output = 10000 if self.followup_request.action == "ask" else self.limits.report_tokens + 2500 * len(self.job.request.omens)
            reserve = min(self.limits.max_tokens // 3, max(self.limits.report_reserve_tokens, 2 * (min(estimated, 60000) + final_output)))
            if self.job.usage.get("total_tokens", 0) + estimated + output + reserve > self.limits.max_tokens:
                raise BudgetStop("research_token_budget")
        return await super().model(messages, **options)

    def projected_history(self):
        history = super().projected_history()
        if getattr(self, "answer_mode", False):
            blocked = {sid for sid, source in self.sources.items() if source["kind"] == "web"
                       and not self.safe_citation(Citation(sourceId=sid, page=None))}
            return answer_history(history, blocked)
        return history

    def reply_context(self, *, final=False):
        self.answer_mode = final
        instruction = (
            "你在报告旁回答追问。先用已有资料；需要时调用已提供的研究工具，包括MCP公开搜索/通读网页，不能声称用了未提供的工具。"
            "本轮任务是回答追问，不是重新生成或复核完整研究报告；原研究请求只作背景。"
            "选定新资料仍需full通读；PDF引用实际物理页，通读网页引用page=null且发布日期不晚于截止日。证据不足明确说明，事实推断分开。"
            "最终按以下JSON schema回答；不要输出整份原报告。ask只回答，sectionEdits为空、summary为null；"
            "即使用户说直接文字给我，也将文字放入answer字段，由聊天框直接展示；不要返回裸Markdown。"
            "用户要求补查时，必须解释新资料带来的补充/修正，并引用新读资料；没有有效新增资料时明确补查未完成，不能复述旧报告冒充完成。"
            "仅检索到但未通读、或日期不合格的资料，只列标题及待核问题；不抄其数字、不作背景论据、不列入补充结论，更不能声称读了券商全文。"
            "revise按请求局部修改，sectionEdits.index是原报告0起章节序号，等于章节数时追加一节；"
            "只提交修改章节的标题/正文/引用，程序保留该章原表格与图；不能声称已修改数据表或图。"
            "若用户要求更新图表数据，说明本轮仅支持正文修订并可补查依据。无须修改或不能满足时解释原因，补丁为空。"
            f"当前操作：{self.followup_request.action}。schema：" + json.dumps(FollowupAnswer.model_json_schema(by_alias=True), ensure_ascii=False)
        )
        if final:
            instruction += "取证到此结束，仅用现有证据回答，列明未完成补查；此次禁止调用工具。不得为未完整阅读或日期不合格资料补造引用。"
        # 当前报告与本次问题放在历史之外，压缩不改变章节序号、正式正文或最新用户要求。
        active = {"type": "active_report", "report": report_view(self.base),
                  "instruction": "当前讨论的是这份报告；沿用其截止日。原始笔记可按来源目录回查。"}
        context = self.context(include_instruction=False)
        return context + [{"role": "user", "content": json.dumps(active, ensure_ascii=False)},
                    {"role": "user", "content": json.dumps(saved_supplement(self), ensure_ascii=False)},
                    {"role": "user", "content": instruction + "\n本次用户问题：" + self.followup_request.message}]

    def wants_supplement(self):
        for clause in re.split(r"[，,。；;！!\n]", self.followup_request.message):
            if re.search(r"(?:不用|不要|无需|不必|不需要|别).{0,3}(?:补查|再查|查阅|搜索|检索|搜)", clause):
                continue
            if re.search(r"上次|上轮|之前|已读|已经", clause) and not re.search(r"再查|重新查|继续查|多查", clause):
                continue
            if re.search(r"补查|多查|再查|查阅|搜索|检索|搜一下", clause):
                return True
        return False

    def validate_answer(self, assistant, *, final=False):
        answer = FollowupAnswer.model_validate_json(assistant.get("content") or "")
        citations = answer.citations + [c for edit in answer.section_edits for c in edit.citations]
        invalid = [c.model_dump(by_alias=True) for c in citations if not self.safe_citation(c)]
        if invalid:
            raise ValueError("以下引用不合格（未读/页码无效/网页日期未知或过截止日），请移除相应事实或补证，不要重复提交：" + json.dumps(invalid, ensure_ascii=False))
        if self.wants_supplement():
            eligible = self.eligible_supplement()
            if not eligible and not final:
                raise SupplementRequired("本次尚未阅读新的合格资料。用户要求再查，不能拿上次补查冒充本轮；请搜索并通读新资料后回答。找不到时明确未完成。")
            if eligible and not eligible.intersection(c.source_id for c in citations):
                raise ValueError("补查回答未引用任何新读资料；请利用discussion_supplement中的有效新资料说明增量，并给出引用。")
        if self.followup_request.action == "ask" and (answer.section_edits or answer.summary is not None):
            raise ValueError("追问模式不能修改报告，请将sectionEdits置空、summary置null")
        indices = [e.index for e in answer.section_edits]
        if len(set(indices)) != len(indices) or any(i > len(self.base["sections"]) for i in indices):
            raise ValueError("章节序号重复或越界")
        if len(self.base["sections"]) == 12 and 12 in indices:
            raise ValueError("报告已有12节，请修改现有章节而非新增")
        if (answer.section_edits or answer.summary is not None) and any(not reading_complete(c) for c in self.coverage.values()):
            raise ValueError("新选资料尚未完整阅读；请继续full阅读，或只回复未完成范围并将修改置空")
        return answer

    async def next_turn(self, final):
        for retry in range(3):
            self.answer_stream = ""
            self.job.followup = None
            try:
                return await self.model(self.reply_context(final=final), tool_specs=None if final else self.declarations(),
                                        report=final, output_limit=10000 if final and self.followup_request.action == "ask" else None,
                                        on_text=self.stream_answer)
            except ModelServiceError as error:
                if retry == 2 or error.code not in {"MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_UPSTREAM_ERROR"}:
                    raise
                self.job.emit("writing_unit_retry", "本次对话调用暂时失败，在当前节点重试；已读资料保留", errorCode=error.code)
                await asyncio.sleep(0.2 * (retry + 1))

    def stream_answer(self, delta):
        self.answer_stream += delta
        text = partial_answer(self.answer_stream)
        if text:
            self.job.followup = {"answer": text, "citations": [], "draft": True}

    def safe_citation(self, citation):
        return self.check_citation(citation)

    def eligible_supplement(self):
        original = set(self.discussion_source_baseline or [])
        return {sid for sid, s in self.sources.items() if sid not in original and (
            s["kind"] == "web" and self.safe_citation(Citation(sourceId=sid, page=None))
            or s["kind"] == "document" and reading_complete(self.coverage.get(sid))
            and any(self.safe_citation(Citation(sourceId=sid, page=p)) for p in self.coverage.get(sid, {}).get("processedPages", [])))}

    def start_reply_wrapup(self, reason):
        self.wrapup_reason = reason
        # 中途触及取证预留时也补齐工具协议；成功阅读的笔记/游标均已独立保存。
        for call in pending_calls(self.messages):
            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({
                "status": "deferred", "reason": reason, "instruction": "停止新增取证，用已完成阅读的证据回答，并说明未完成范围。"}, ensure_ascii=False)})
        for record in self.job.tool_calls:
            if record["status"] == "running":
                record.update(status="interrupted", finishedAt=now())
        self.job.emit("discussion_wrapup", "补查接近边界，保留已读资料并转入回答，未完成范围会明确说明", reason=reason)
        self.job.set_phase("writing", "阶段：整理追问答案")
        self.checkpoint()

    def revised_report(self, answer):
        result = deepcopy(self.base)
        for edit in answer.section_edits:
            patch = {"heading": edit.heading, "content": edit.content,
                     "citations": [c.model_dump(by_alias=True) for c in edit.citations]}
            if edit.index == len(result["sections"]):
                result["sections"].append(patch)
                if result.get("figurePlan") is not None:
                    result["figurePlan"].append({"sectionIndex": edit.index, "financialChartIds": [], "businessDatasetIds": [], "diagram": None, "gap": None})
            else:
                result["sections"][edit.index].update(patch)
        if answer.summary is not None:
            result["summary"] = answer.summary
        result["sources"] = list(self.sources.values())
        result["coverage"] = list(self.coverage.values())
        result["toolCalls"] = deepcopy(self.base.get("toolCalls", [])) + deepcopy(self.job.tool_calls)
        result["visualReadings"] = deepcopy(self.visual_readings)
        result["extractionReadings"] = deepcopy(self.extraction_readings)
        if result.get("methodUsage"):
            result["methodUsage"] = deepcopy(self.method_usage or result["methodUsage"])
            result["methodUsage"]["reviewed"] = False
        for item in result.get("omenCoverage", []):
            item["verification"] = "继承前版覆盖记录；本次仅校验修订引用，未再次整体复核。"
        result["run"] = {**result["run"], "taskId": self.job.task_id, "sessionId": self.job.session_id,
                         "startedAt": self.job.started_at, "finishedAt": now(), "model": self.settings.model,
                         "modelCalls": self.job.model_calls, "usage": dict(self.job.usage), "steps": self.steps,
                         "stopReason": "report_revised", "reviewOutcome": "局部正文修订：引用页码校验通过，未独立重审原报告"}
        result["limitations"] = list(dict.fromkeys(result["limitations"] + ["本版本仅修改指定正文/摘要；原图表与数据表保留，未重新核验整篇报告。 "]))
        return result

    async def run(self):
        self.job.status = "running"
        self.job.set_phase("research", "阶段：围绕报告追问或补查")
        answer, version_id = None, None
        try:
            async with asyncio.timeout(self.limits.max_seconds):
                await self.load_user_memory()
                chain = branch(self.prepared["entries"], str(self.followup_request.parent_id))
                leaf = chain[-1]
                # 预算失败后的同一问题已有补查全文：直接用保存的笔记收尾，不重启搜索。
                force_final = bool(leaf.get("type") == "chat_turn" and leaf.get("status") == "failed"
                    and leaf.get("userMessage") == self.followup_request.message and self.eligible_supplement()
                    and any(k in json.dumps(leaf.get("error") or {}) for k in ("token_budget", "call_budget")))
                if force_final:
                    self.start_reply_wrapup("saved_supplement_ready")
                invalid_answers = 0
                missing_supplement = 0
                for attempt in range(self.limits.max_steps + 4):
                    final = force_final or self.steps >= self.limits.max_steps or attempt >= self.limits.max_steps
                    try:
                        assistant = await self.next_turn(final)
                    except BudgetStop as error:
                        if final or str(error) not in {"research_token_budget", "research_call_budget", "research_time_budget", "context_budget"}:
                            raise
                        self.start_reply_wrapup(str(error))
                        force_final = True
                        continue
                    self.messages.append(assistant)
                    calls = assistant.get("tool_calls") or []
                    if calls:
                        if final:
                            raise ValueError("收尾回复仍请求工具")
                        self.steps += 1
                        try:
                            for call in calls:
                                await self.run_tool_call(call)
                        except BudgetStop as error:
                            if str(error) not in {"research_token_budget", "research_call_budget", "research_time_budget", "context_budget"}:
                                raise
                            self.start_reply_wrapup(str(error))
                            force_final = True
                        continue
                    try:
                        answer = self.validate_answer(assistant, final=final)
                        break
                    except ValueError as error:
                        self.job.followup = None  # 校验不合格的流式草稿立即撤回。
                        self.messages.pop()
                        self.job.emit("report_validation_failed", "对话回复校验未通过，正在修正格式或引用", diagnostics=str(error)[:1800])
                        if isinstance(error, SupplementRequired):
                            missing_supplement += 1
                            force_final = final or missing_supplement >= 2
                            self.messages.append({"role": "user", "content": str(error) if not force_final else
                                "本次补查尚未取得新证据，结束新增取证。仅回答已有资料能支持的部分，明确本次补查未完成，不冒充已查到。"})
                            continue
                        invalid_answers += 1
                        if invalid_answers >= 3:
                            raise ModelServiceError("MODEL_INVALID_RESPONSE", "对话回复经两次修正仍未通过格式/引用校验，已读证据保留。", 502) from None
                        self.messages.append({"role": "user", "content": "请修正回复：" + str(error)[:1600]})
                        force_final = final or not isinstance(error, SupplementRequired)
                if answer is None:
                    raise ModelServiceError("MODEL_INVALID_RESPONSE", "对话回复未通过校验，原报告保留。", 502)
                unread = [self.sources[sid]["title"] for sid, coverage in self.coverage.items() if not reading_complete(coverage)]
                if unread:
                    answer.answer += "\n\n【未完成资料】以下新选资料仍未完整阅读：" + "、".join(unread) + "。相关补查未完成，不作为完整研究结论。"
                used = sorted(self.eligible_supplement().intersection(c.source_id for c in answer.citations))
                if self.wants_supplement() and not used:
                    answer.answer = "【补查未完成】本轮尚未获得可引用的新增公开资料；以下仅为已有资料范围内的回答，不能视为已完成此次补查。\n\n" + answer.answer
                self.job.emit("discussion_evidence_used", "追问回复已核对引用与已读范围", newSourceIds=used,
                              citedSourceIds=sorted({c.source_id for c in answer.citations}))
                self.job.followup = {"answer": answer.answer, "citations": [c.model_dump(by_alias=True) for c in answer.citations]}
                if self.followup_request.action == "revise" and (answer.section_edits or answer.summary is not None):
                    self.job.report = self.revised_report(answer)
                    version_id = self.job.recorder.add("report", reportId=self.job.task_id,
                        reportVersion=self.prepared["nextVersion"], parentVersionId=self.prepared["base"]["id"], report=self.job.report,
                        changedSections=[e.index for e in answer.section_edits], summaryChanged=answer.summary is not None)
                self.job.status = "completed"
                self.job.set_phase("done", "阶段：对话完成" if not version_id else "阶段：新报告版本已保存")
        except asyncio.CancelledError:
            self.job.status = "cancelled"
            self.job.error = {"code": "RESEARCH_CANCELLED", "message": "本次对话已停止，原报告保留。"}
            self.job.emit("run_cancelled", self.job.error["message"])
        except (ModelServiceError, BudgetStop, TimeoutError, ValueError) as error:
            self.job.status = "failed"
            self.job.error = {"code": getattr(error, "code", "RESEARCH_FAILED"),
                              "message": getattr(error, "message", "本次对话未完成，原报告保留；可从上一节点重试。原因：" + str(error)[:120])}
            self.job.emit("run_failed", self.job.error["message"])
        except Exception:
            logger.exception("discussion %s failed", self.job.task_id)
            self.job.status = "failed"
            self.job.error = {"code": "RESEARCH_FAILED", "message": "对话执行失败，原报告和已完成对话保留。"}
            self.job.emit("run_failed", self.job.error["message"])
        finally:
            if self.job.status != "completed":
                self.job.followup = None
            for call in pending_calls(self.messages):
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"status": "failed", "error": self.job.error})})
            for record in self.job.tool_calls:
                if record["status"] == "running":
                    record.update(status="interrupted", finishedAt=now())
            self.job.finished_at = now()
            self.checkpoint()
            recorder = self.job.recorder
            turn_id = recorder.add("chat_turn", rootTaskId=self.prepared["rootTaskId"], parentTurnId=str(self.followup_request.parent_id),
                baseVersionId=self.prepared["base"]["id"], versionId=version_id, action=self.followup_request.action,
                userMessage=self.followup_request.message, answer=answer.answer if answer and self.job.status == "completed" else "",
                citations=self.job.followup["citations"] if self.job.followup else [], sources=list(self.sources.values()),
                status=self.job.status, error=self.job.error)
            self.job.followup = {**(self.job.followup or {}), "turnId": turn_id, "versionId": version_id}
            recorder.add("run_state", status=self.job.status, finishedAt=self.job.finished_at, modelCalls=self.job.model_calls,
                         usage=self.job.usage, error=self.job.error)
            await recorder.close()
