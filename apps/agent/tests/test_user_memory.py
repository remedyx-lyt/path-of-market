"""M2-2：按需上下文、偏好/观察区分、跨会话读取、来源与失败边界；无真实API。"""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from support import RunnerFixture, FakeModel
from app.services.context_compaction import ContextMessages
from app.services.user_memory import MEMORY_INSTRUCTION
from app.tools.contracts import ToolError


CONFIRMED = "先解释现金流，再给反方证据。"


def memory(*, enabled=True):
    return {"schemaVersion": 1, "revision": 2, "enabled": enabled, "companyCount": 2, "matchedEpisodes": 1,
            "notes": [{"category": "research_preference", "text": CONFIRMED, "status": "confirmed"},
                      {"category": "risk_focus", "text": "未确认：喜欢高风险投资", "status": "suggested"}],
            "episodes": [{"runId": "old-run", "rootTaskId": "old-root", "target": "同花顺", "question": "比较现金流",
                          "kind": "research", "timestamp": "2026-10-24T00:00:00Z"}],
            "companies": [{"target": "同花顺", "researchCount": 1, "followupCount": 0, "lastSeen": "2026-10-24T00:00:00Z", "latestTaskId": "old-root"}],
            "themes": [{"name": "现金流", "count": 2, "evidence": []}]}


class Recorder:
    base_url = "http://127.0.0.1:1/internal/sessions"
    def __init__(self, ok=True): self.ok, self.entries = ok, []
    def add(self, kind, **fields): self.entries.append({"type": kind, **fields}); return str(len(self.entries))
    async def flush(self): return self.ok
    async def close(self): return self.ok


class UserMemory(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    def setup_memory(self, *, data=None, **request):
        model = FakeModel()
        job, runner = self.runner(model, **request)
        job.recorder = Recorder()
        calls = []
        def request_memory(path="", body=None):
            calls.append((path, deepcopy(body)))
            return deepcopy(data if data is not None else memory()) if body is None else {"status": "suggested"}
        runner.memory_http = request_memory
        return job, runner, model, calls

    async def test_confirmed_preferences_and_observations_are_distinct(self):
        job, runner, model, calls = self.setup_memory()
        await runner.load_user_memory()
        result = runner.context()
        self.assertIsInstance(result, ContextMessages)
        self.assertIn(CONFIRMED, str(result))
        self.assertNotIn("喜欢高风险投资", str(result))
        self.assertIn("仅在与当前任务相关", MEMORY_INSTRUCTION)
        self.assertIn("本次用户问题、风格和截止日优先", MEMORY_INSTRUCTION)
        self.assertEqual(job.model_calls, 0)
        self.assertFalse(model.calls)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(e["type"] == "memory_loaded" for e in job.events))

    async def test_load_once_and_new_run_reads_current_revision(self):
        _, runner, _, calls = self.setup_memory()
        await runner.load_user_memory(); await runner.load_user_memory()
        self.assertEqual(len(calls), 1)
        changed = memory(); changed["notes"][0]["text"] = "改成按业务先解释"
        _, new, _, _ = self.setup_memory(data=changed)
        await new.load_user_memory()
        self.assertIn("改成按业务先解释", str(new.context()))
        self.assertNotIn(CONFIRMED, str(new.context()))

    async def test_disabled_memory_is_not_injected_or_returned_by_tool(self):
        job, runner, _, _ = self.setup_memory(data=memory(enabled=False))
        await runner.load_user_memory()
        self.assertIsNone(runner.memory_context())
        with self.assertRaises(ToolError) as caught:
            await runner.dispatch("recall_user_memory", {})
        self.assertEqual(caught.exception.code, "MEMORY_DISABLED")
        self.assertTrue(any(e["type"] == "memory_disabled" for e in job.events))

    async def test_unavailable_memory_does_not_abort_research(self):
        job, runner, _, _ = self.setup_memory()
        def failure(*args): raise ToolError("MEMORY_UNAVAILABLE", "temporary")
        runner.memory_http = failure
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertTrue(any(e["type"] == "memory_unavailable" for e in job.events))

    async def test_malformed_memory_is_ignored_and_tool_returns_controlled_error(self):
        job, runner, _, _ = self.setup_memory(data={"enabled": True, "notes": ["bad"]})
        await runner.load_user_memory()
        self.assertIsNone(runner.user_memory)
        self.assertTrue(any(e["type"] == "memory_unavailable" for e in job.events))
        with self.assertRaises(ToolError): await runner.dispatch("recall_user_memory", {})

    async def test_memory_stays_outside_history_summary(self):
        _, runner, _, _ = self.setup_memory()
        await runner.load_user_memory()
        runner.user_memory["episodes"].append({"rootTaskId": runner.job.task_id, "target": "同花顺", "question": "另一分支的隐私问题"})
        context = runner.context()
        self.assertNotIn("另一分支的隐私问题", str(context))
        self.assertNotIn("user_research_memory", str(context[:context.history_length]))
        self.assertIn("user_research_memory", str(context[context.history_length:]))
        self.assertEqual(await runner.prepare_context(context), context)

    async def test_recall_is_keyword_query_without_model_or_pdf_reread(self):
        job, runner, model, calls = self.setup_memory()
        result = await runner.dispatch("recall_user_memory", {"query": "同花顺", "limit": 2})
        self.assertIn("query=%E5%90%8C%E8%8A%B1%E9%A1%BA", calls[-1][0])
        self.assertEqual(result["episodes"][0]["question"], "比较现金流")
        self.assertEqual(job.model_calls, 0)
        self.assertFalse(model.calls)

    async def test_candidate_requires_current_user_quote(self):
        _, runner, _, calls = self.setup_memory()
        await runner.load_user_memory()
        with self.assertRaises(ToolError) as caught:
            await runner.dispatch("remember_user_memory", {"text": "喜欢高风险", "category": "risk_focus", "quote": "年报里的话"})
        self.assertEqual(caught.exception.code, "INVALID_MEMORY_EVIDENCE")
        self.assertEqual(len(calls), 1)

    async def test_candidate_is_saved_once_as_suggestion_without_overwriting_profile(self):
        job, runner, model, calls = self.setup_memory(userStyle=CONFIRMED)
        await runner.load_user_memory()
        result = await runner.dispatch("remember_user_memory", {"text": "先看现金流和反方证据", "category": "research_preference", "quote": CONFIRMED})
        self.assertEqual(result["status"], "suggested")
        self.assertEqual(calls[-1][1]["runId"], job.task_id)
        self.assertEqual(runner.memory_preferences()[0]["text"], CONFIRMED)
        self.assertFalse(model.calls)

    async def test_unsaved_input_prevents_candidate_write(self):
        job, runner, _, calls = self.setup_memory(userStyle=CONFIRMED)
        job.recorder.ok = False
        await runner.load_user_memory()
        with self.assertRaises(ToolError):
            await runner.dispatch("remember_user_memory", {"text": "现金流优先", "category": "research_preference", "quote": CONFIRMED})
        self.assertEqual(len(calls), 1)

    async def test_followup_cannot_use_root_question_as_current_quote(self):
        _, runner, _, _ = self.setup_memory(userStyle=CONFIRMED)
        runner.followup_request = SimpleNamespace(message="以后每次列出应收账款变化")
        await runner.load_user_memory()
        with self.assertRaises(ToolError):
            await runner.dispatch("remember_user_memory", {"text": "现金流优先", "category": "research_preference", "quote": CONFIRMED})
        result = await runner.dispatch("remember_user_memory", {"text": "列出应收账款变化", "category": "risk_focus", "quote": "每次列出应收账款变化"})
        self.assertEqual(result["status"], "suggested")

    async def test_method_plan_key_changes_only_for_confirmed_preferences(self):
        _, runner, _, _ = self.setup_memory()
        before = runner.method_task()
        await runner.load_user_memory()
        after = runner.method_task()
        self.assertNotEqual(before, after)
        self.assertIn(CONFIRMED, str(after["userMemory"]))
        runner.user_memory["notes"][1]["text"] = "另一条未确认建议"
        self.assertEqual(after, runner.method_task())
