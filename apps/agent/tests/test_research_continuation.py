"""预算预留、进程重启后的检查点接续与旧 JSONL 恢复；均使用隔离模型。"""

from copy import deepcopy
from dataclasses import replace
import json
import unittest

from support import DOC_ID, SETTINGS, USAGE, FakeModel, RunnerFixture, tool_call
from app.services.agent_runner import AgentRunner, BudgetStop, RunLimits
from app.services.research_jobs import ResearchJob
from app.services.research_recovery import current_messages, legacy_recovery, load_recovery, pending_calls
from app.core.config import ModelServiceError
from app.services.runner_report import normalize_table


class Continuation(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_failure_before_method_plan_restores_unfinished_planning(self):
        class AccountFailure(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                raise ModelServiceError("MODEL_AUTH_FAILED", "account", 502)

        parent, first = self.runner(AccountFailure())
        await first.run()
        self.assertEqual(parent.status, "failed")
        self.assertIsNone(first.method_usage)
        child, model = ResearchJob(parent.request), FakeModel(ready=True)
        resumed = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=load_recovery(self.tools, parent.task_id))
        await resumed.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(model.count("plan"), 1)

    async def test_chapter_failure_resumes_only_failed_chapter_after_restart(self):
        class FailSecond(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "section":
                    task = json.JSONDecoder().raw_decode(messages[-1]["content"].split("\n", 1)[1])[0]
                    if task["sectionIndex"] == 1:
                        raise ModelServiceError("MODEL_TIMEOUT", "temporary", 504)
                return await super().__call__(settings, messages, **kwargs)

        parent, first = self.runner(FailSecond(ready=True))
        await first.run()
        self.assertEqual(parent.status, "failed")
        self.assertEqual(len(first.writing_state["sections"]), 1)
        self.assertEqual(first.writing_state["lastFailure"]["unit"], "第2节")
        saved = deepcopy(first.writing_state["sections"][0])
        self.assertEqual(parent.report["sections"][0], saved)
        recovery = load_recovery(self.tools, parent.task_id)
        child, model = ResearchJob(parent.request), FakeModel(ready=True)
        resumed = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery)
        await resumed.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(model.count("reading"), 0)
        self.assertEqual(model.count("compose"), 0)
        self.assertEqual(model.count("section"), 1)
        self.assertIn("上次在当前部分失败", next(c[2][-1]["content"] for c in model.calls if c[0] == "section"))
        self.assertEqual(resumed.writing_state["sections"][0], saved)

    async def test_budget_interrupt_after_chapters_resumes_metadata_without_rewriting(self):
        parent, first = self.runner(FakeModel(ready=True), limits={"max_model_calls": 8})
        await first.run()
        self.assertEqual(parent.status, "partial")
        self.assertEqual(len(first.writing_state["sections"]), 2)
        self.assertIsNone(first.writing_state["metadata"])
        child, model = ResearchJob(parent.request), FakeModel(ready=True)
        resumed = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=load_recovery(self.tools, parent.task_id))
        await resumed.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(model.count("section"), 0)
        self.assertEqual(model.count("compose"), 0)
        self.assertEqual(model.count("metadata"), 1)

    async def test_wrong_chapter_page_keeps_source_without_rewrite(self):
        # 2026-10-26 用户决定引用不强制到页：页码对不上只去掉页码，章节照常保存。
        wrong = FakeModel(ready=True)
        wrong.final["sections"][0]["citations"][0]["page"] = 999
        job, runner = self.runner(wrong)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertIsNone(runner.writing_state["sections"][0]["citations"][0]["page"])
        self.assertFalse(any(e["type"] == "writing_unit_failed" for e in job.events))

    async def test_unknown_chapter_source_is_not_saved_as_success(self):
        bad = FakeModel(ready=True)
        bad.final["sections"][0]["citations"][0]["sourceId"] = "cninfo-9999999999"
        job, runner = self.runner(bad)
        await runner.run()
        self.assertEqual(job.status, "failed")
        self.assertEqual(runner.writing_state["sections"], [])
        self.assertTrue(any(e["type"] == "writing_unit_failed" for e in job.events))

    async def stopped(self):
        job, runner = self.runner(FakeModel(ready=True), limits={"max_model_calls": 4})
        await runner.run()
        self.assertEqual(job.status, "partial")
        self.assertTrue(runner.coverage[DOC_ID]["textComplete"])
        return job, runner

    async def test_restart_uses_checkpoint_without_repeating_reading_or_methods(self):
        parent, previous = await self.stopped()
        recovery = load_recovery(self.tools, parent.task_id)
        model = FakeModel(script=["final"], ready=True)
        child = ResearchJob(parent.request, parent_task_id=parent.task_id)
        runner = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery)
        await runner.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(model.count("plan"), 0)
        self.assertEqual(model.count("reading"), 0)
        self.assertEqual(model.count("decision"), 0)
        self.assertEqual(runner.coverage, previous.coverage)
        self.assertEqual(runner.notes, previous.notes)
        self.assertEqual(parent.status, "partial")
        self.assertTrue(any(e["type"] == "run_resumed" for e in child.events))

    async def test_pending_tool_group_only_runs_missing_result(self):
        parent, _ = await self.stopped()
        recovery = load_recovery(self.tools, parent.task_id)
        calls = [tool_call(99, i, "read_document", {"documentId": DOC_ID, "mode": "page", "page": 1}) for i in range(2)]
        recovery["messages"] += [{"role": "assistant", "content": "", "tool_calls": calls},
                                  {"role": "tool", "tool_call_id": calls[0]["id"], "content": '{"status":"completed","data":{}}'}]
        child = ResearchJob(parent.request)
        model = FakeModel(script=["final"], ready=True)
        runner = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery)
        await runner.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual([c["toolCallId"] for c in child.tool_calls], [calls[1]["id"]])
        self.assertEqual(pending_calls(runner.messages), [])

    async def test_complete_evidence_resumes_writing_without_wasting_decision_budget(self):
        parent, _ = await self.stopped()
        recovery = load_recovery(self.tools, parent.task_id)
        model = FakeModel(script=[[("read_document", {"documentId": DOC_ID, "mode": "full"})]])
        child = ResearchJob(parent.request)
        limits = replace(RunLimits(), max_model_calls=24, report_reserve_calls=12, max_steps=30)
        runner = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery, limits=limits)
        await runner.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertTrue(any(e["type"] == "resume_ready_to_write" for e in child.events))
        self.assertEqual(model.count("decision"), 0)
        self.assertLessEqual(child.model_calls, 24)
        self.assertGreater(model.count("compose"), 0)

    async def test_truncated_decision_after_full_reading_enters_section_writer(self):
        class Truncated(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "decision" and self.count("decision") == 2:
                    error = ModelServiceError("MODEL_INVALID_RESPONSE", "truncated", 502)
                    error.finish_reason, error.usage = "length", USAGE
                    raise error
                return await super().__call__(settings, messages, **kwargs)

        model = Truncated(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertGreater(model.count("section"), 0)
        self.assertTrue(any(e["type"] == "decision_to_writing" for e in job.events))
        self.assertTrue(any(e["type"] == "model_failed" and e.get("finishReason") == "length" for e in job.events))

    async def test_transient_decision_retries_without_duplicate_tool_execution(self):
        class Temporary(FakeModel):
            failed = False

            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "decision" and not self.failed:
                    self.failed = True
                    raise ModelServiceError("MODEL_TIMEOUT", "temporary", 504)
                return await super().__call__(settings, messages, **kwargs)

        model = Temporary(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(sum(e["type"] == "decision_retry" for e in job.events), 1)
        self.assertEqual(len(job.tool_calls), 3)
        self.assertEqual(model.count("reading"), 1)

    async def test_account_error_does_not_retry_or_start_writer(self):
        class Account(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "decision":
                    raise ModelServiceError("MODEL_AUTH_FAILED", "account", 502)
                return await super().__call__(settings, messages, **kwargs)

        model = Account(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "failed")
        self.assertFalse(any(e["type"] == "decision_retry" for e in job.events))
        self.assertEqual(model.count("compose"), 0)

    async def test_local_tools_still_work_at_model_call_limit(self):
        parent, runner = await self.stopped()
        self.assertEqual(parent.model_calls, runner.limits.max_model_calls)
        with self.assertRaises(BudgetStop):
            await runner.model([{"role": "user", "content": "x"}])
        data = await runner.raw_tool("read_document", {"documentId": DOC_ID, "page": 1})
        self.assertEqual(data["page"], 1)

    async def test_legacy_session_recovers_notes_and_actual_coverage(self):
        parent, runner = await self.stopped()
        entries = [{"type": "session", "id": parent.session_id, "runId": parent.task_id,
                    "request": parent.request.model_dump(mode="json", by_alias=True)}]
        for i, message in enumerate(runner.messages):
            entries.append({"type": "message", "id": str(i), "parentId": str(i - 1) if i else None, "message": message})
        entries += [{"type": "report", "id": "report", "parentId": str(len(runner.messages) - 1), "report": parent.report},
                    {"type": "run_state", "id": "state", "parentId": "report", "status": "partial", "modelCalls": parent.model_calls}]
        recovery = legacy_recovery(entries, parent.task_id)
        self.assertEqual(recovery["state"]["coverage"], runner.coverage)
        self.assertEqual(recovery["state"]["notes"], runner.notes)
        broken = deepcopy(entries)
        for entry in broken:
            if entry.get("type") == "message" and entry["message"].get("role") == "tool":
                entry["message"]["content"] = '{"status":"completed","data":{}}'
        with self.assertRaises(ModelServiceError):
            legacy_recovery(broken, parent.task_id)


class RecoveryStructure(unittest.TestCase):
    def test_current_branch_and_context_edits(self):
        entries = [{"type": "session", "id": "s"},
                   {"type": "message", "id": "a", "parentId": None, "message": {"content": "root"}},
                   {"type": "message", "id": "b", "parentId": "a", "message": {"content": "other branch"}},
                   {"type": "message", "id": "c", "parentId": "a", "message": {"content": "draft"}},
                   {"type": "context_edit", "id": "d", "parentId": "c", "targetId": "c"}]
        self.assertEqual(current_messages(entries), [{"content": "root"}])
        entries[-1]["parentId"] = "d"
        with self.assertRaises(ModelServiceError):
            current_messages(entries)

    def test_chart_column_names_and_bad_configuration_keep_valid_table(self):
        table = {"title": "数据", "columns": ["收入", "利润"], "rows": [{"label": "2025", "cells": [1, 2]}],
                 "chart": "bar", "chartColumns": ["收入", "1"]}
        fixes = []
        result = normalize_table(table, 0, fixes)
        self.assertEqual(result["chartColumns"], [0, 1])
        result["chartColumns"] = ["不存在", -1, 99]
        self.assertEqual(normalize_table(result, 0, fixes)["chart"], "none")
        self.assertEqual(len(result["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
