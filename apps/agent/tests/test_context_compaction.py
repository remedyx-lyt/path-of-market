"""M2-5：摘要/完整历史分离、整组工具消息、预算和失败、持久化与原记录回查。无真实模型调用。"""
from copy import deepcopy
import json
import unittest

from support import RunnerFixture, SETTINGS, USAGE, DOC_ID, tool_call
from app.core.config import ModelServiceError
from app.services.agent_runner import AgentRunner
from app.services.context_compaction import COMPACTION_SYSTEM, ContextMessages, size, safe_cuts
from app.services.research_jobs import ResearchJob
from app.services.research_recovery import load_recovery, current_messages
from app.services.session_recorder import RecordedMessages, SessionRecorder


class SummaryModel:
    def __init__(self, mode="ok"):
        self.calls, self.mode = [], mode

    async def __call__(self, settings, messages, **kwargs):
        self.calls.append((deepcopy(messages), kwargs))
        if messages[0]["content"] != COMPACTION_SYSTEM:
            return {"role": "assistant", "content": '{"ready":true}'}, USAGE
        if self.mode == "timeout":
            raise ModelServiceError("MODEL_TIMEOUT", "temporary", 504)
        if self.mode == "auth":
            raise ModelServiceError("MODEL_AUTH_FAILED", "account", 503)
        if self.mode == "invalid":
            return {"role": "assistant", "content": "bad-json"}, USAGE
        result = {"goal": "保持原研究目标", "constraints": ["区分事实与假设，沿用原截止日"],
                  "completed": ["已读资料在程序中保留"], "decisions": ["需要精确数字时回查笔记"],
                  "openQuestions": ["继续核对现金流"], "evidence": [{"sourceId": DOC_ID, "page": 1}]}
        if self.mode == "wrong_page":
            result["evidence"][0]["page"] = 999
        return {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}, USAGE


class Compaction(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    def make_runner(self, model=None):
        model = model or SummaryModel()
        job, runner = self.runner(model, limits={"max_context_characters": 60000,
                                  "context_reserve_characters": 8000, "compaction_keep_characters": 6000,
                                  "compaction_chunk_characters": 24000})
        runner.sources[DOC_ID] = {"sourceId": DOC_ID, "kind": "document", "title": "原始研究资料", "pageCount": 2,
                                 "url": "https://example.com/report.pdf", "publishedAt": "2025-01-01"}
        runner.coverage[DOC_ID] = {"sourceId": DOC_ID, "pageCount": 2, "processedPages": [1, 2], "textComplete": True,
                                  "processedCharacters": 100, "batches": 1, "emptyTextPages": []}
        runner.notes[DOC_ID] = [{"summary": "完整批次笔记", "facts": [{"text": "2024年研发投入3.14亿元，口径未独立核验", "pages": [1]}], "gaps": []}]
        return job, runner, model

    def grow(self, runner, *, pairs=False):
        for i in range(10):
            runner.messages.append({"role": "user", "content": f"历史问题{i}：" + "甲" * 6000})
            if pairs:
                call = tool_call(i, 0, "read_document", {"mode": "page", "page": 1, "documentId": DOC_ID})
                runner.messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                runner.messages.append({"role": "tool", "tool_call_id": call["id"], "content": '{"status":"completed","data":{"text":"已读原文","page":1}}'})
            else:
                runner.messages.append({"role": "assistant", "content": "历史答复"})
        runner.messages.append({"role": "user", "content": "最新问题：不要忘记风险与反方。"})

    async def test_small_context_never_calls_summary(self):
        _, runner, model = self.make_runner()
        before = runner.context()
        after = await runner.prepare_context(before)
        self.assertEqual(after, before)
        self.assertFalse(model.calls)

    async def test_history_shrinks_without_mutating_evidence_or_raw_messages(self):
        job, runner, model = self.make_runner()
        self.grow(runner)
        raw, notes, coverage = deepcopy(list(runner.messages)), deepcopy(runner.notes), deepcopy(runner.coverage)
        before = runner.context() + [{"role": "user", "content": "本次写作指令"}]
        after = await runner.prepare_context(before)
        self.assertLess(size(after), size(before) * 0.7)
        self.assertEqual(after[-1]["content"], "本次写作指令")
        self.assertIn("最新问题", json.dumps(after, ensure_ascii=False))
        self.assertEqual(list(runner.messages), raw)
        self.assertEqual(runner.notes, notes)
        self.assertEqual(runner.coverage, coverage)
        self.assertEqual(job.model_calls, len(model.calls))
        self.assertTrue(any(e["type"] == "compaction_completed" for e in job.events))

    async def test_tool_groups_remain_paired_after_projection(self):
        _, runner, _ = self.make_runner()
        self.grow(runner, pairs=True)
        after = await runner.prepare_context(runner.context())
        requested = {c["id"] for m in after for c in m.get("tool_calls", [])}
        answered = {m["tool_call_id"] for m in after if m["role"] == "tool"}
        self.assertEqual(requested, answered)
        dangling = [{"role": "assistant", "tool_calls": [tool_call(90, 0, "x", {})]}, {"role": "user", "content": "中断"}]
        self.assertEqual(safe_cuts(dangling, 0), [])

    async def test_independent_reading_call_is_never_summarized(self):
        _, runner, model = self.make_runner()
        self.grow(runner)
        reading = [{"role": "system", "content": "READ_SYSTEM"}, {"role": "user", "content": "原文" * 100}]
        self.assertEqual(await runner.prepare_context(reading), reading)
        self.assertFalse(model.calls)

    async def test_recall_is_exact_and_does_not_call_model_or_increase_coverage(self):
        job, runner, model = self.make_runner()
        before = deepcopy(runner.coverage)
        result = await runner.dispatch("recall_research_context", {"kind": "reading_notes", "sourceId": DOC_ID})
        self.assertEqual(result["recalledNotes"], runner.notes[DOC_ID])
        self.assertIn("3.14亿元", str(result))
        self.assertEqual(job.model_calls, 0)
        self.assertEqual(runner.coverage, before)
        self.assertFalse(model.calls)
        from app.tools.contracts import ToolError
        with self.assertRaises(ToolError):
            await runner.dispatch("recall_research_context", {"kind": "reading_notes", "sourceId": "另一分支"})

    async def test_failed_summary_rolls_back_and_does_not_thrash(self):
        for mode in ("timeout", "invalid", "wrong_page"):
            with self.subTest(mode=mode):
                _, runner, model = self.make_runner(SummaryModel(mode))
                self.grow(runner)
                before = runner.context()
                after = await runner.prepare_context(before)
                self.assertEqual(after, before)
                self.assertIsNone(runner.compaction_state)
                count = len(model.calls)
                self.assertEqual(count, 2)
                await runner.prepare_context(before)
                self.assertEqual(len(model.calls), count)

    async def test_account_error_propagates_without_changing_history(self):
        _, runner, _ = self.make_runner(SummaryModel("auth"))
        self.grow(runner)
        before = deepcopy(list(runner.messages))
        with self.assertRaises(ModelServiceError):
            await runner.prepare_context(runner.context())
        self.assertEqual(list(runner.messages), before)
        self.assertIsNone(runner.compaction_state)

    async def test_checkpoint_restores_summary_without_another_model_call(self):
        _, runner, _ = self.make_runner()
        self.grow(runner)
        first = await runner.prepare_context(runner.context())
        recovery = load_recovery(self.tools, runner.job.task_id)
        model = SummaryModel()
        restored = AgentRunner(ResearchJob(runner.job.request), self.tools, SETTINGS, limits=runner.limits, completion=model, recovery=recovery)
        second = await restored.prepare_context(restored.context())
        self.assertEqual(first, second)
        self.assertFalse(model.calls)
        self.assertEqual(restored.compaction_count, 1)

    async def test_serialized_boundaries_and_original_messages_are_preserved(self):
        job, runner, _ = self.make_runner()
        recorder = SessionRecorder(job.session_id, job.task_id)
        recorder.header(job.request.model_dump(mode="json", by_alias=True))
        job.recorder = recorder
        runner.messages = RecordedMessages(runner.messages, recorder)
        self.grow(runner)
        before = deepcopy(list(runner.messages))
        await runner.prepare_context(runner.context())
        entries = recorder.pending
        compact = next(e for e in entries if e["type"] == "compaction")
        self.assertIsNotNone(compact["firstKeptEntryId"])
        self.assertEqual(current_messages(entries), before)
        self.assertTrue(all(b["parentId"] == a["id"] for a, b in zip(entries[1:], entries[2:])))

    async def test_second_summary_includes_previous_summary_and_new_history(self):
        _, runner, model = self.make_runner()
        self.grow(runner)
        await runner.prepare_context(runner.context())
        count = len(model.calls)
        runner.messages += []
        self.grow(runner)
        await runner.prepare_context(runner.context())
        self.assertEqual(runner.compaction_count, 2)
        later_inputs = [json.loads(messages[1]["content"]) for messages, _ in model.calls[count:]]
        self.assertTrue(later_inputs[0]["previousSummary"])

    async def test_oversized_pinned_report_does_not_get_summarized_or_loop_forever(self):
        job, runner, model = self.make_runner()
        context = runner.context() + [{"role": "user", "content": "当前报告" * 30000}]
        result = await runner.prepare_context(context)
        self.assertEqual(result[-1], context[-1])
        self.assertFalse(model.calls)
        self.assertTrue(any(e["type"] == "compaction_skipped" for e in job.events))
