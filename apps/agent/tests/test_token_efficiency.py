"""省 token 的改动：前缀缓存友好、问题无关的阅读缓存、不重复回传、精简底稿、复核免重写、用量记录缓存命中。"""

import json
import unittest
from unittest.mock import patch

from support import DOC_ID, SETTINGS, USAGE, FakeModel, RunnerFixture, report

from app.core.agent_prompts import LEGACY_READ_SYSTEM
from app.services.agent_runner import ToolView
from app.services.model_client import usage_counts
from app.services.model_json import DerivedCache, stable_key


class TokenEfficiency(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_compose_reuses_research_prefix(self):
        model = FakeModel(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        decision = [c[2] for c in model.calls if c[0] == "decision"][-1]
        compose = next(c[2] for c in model.calls if c[0] == "compose")
        self.assertEqual(compose[0], decision[0])  # 同一系统提示
        stable = len(decision) - 2  # 去掉末尾的“当前底稿/剩余轮数”
        self.assertEqual(compose[:stable], decision[:stable])

    async def test_compose_sends_same_tools_but_forbids_calls(self):
        model = FakeModel(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        decision = [c[3] for c in model.calls if c[0] == "decision"][-1]
        compose = next(c[3] for c in model.calls if c[0] == "compose")
        self.assertEqual(compose["tools"], decision["tools"])
        self.assertEqual(compose["tool_choice"], "none")
        self.assertTrue(compose["json_mode"])

    async def test_compose_falls_back_when_provider_rejects_tool_choice_none(self):
        from app.core.config import ModelServiceError

        class Rejecting(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if kwargs.get("tool_choice") == "none":
                    self.calls.append(("rejected", kwargs.get("max_tokens"), messages, kwargs))
                    raise ModelServiceError("MODEL_UPSTREAM_ERROR", "bad request", 502)
                return await super().__call__(settings, messages, **kwargs)

        model = Rejecting(ready=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.count("rejected"), 1)
        self.assertEqual(model.count("compose"), 1)
        self.assertTrue(any(e["type"] == "report_drafting_fallback" for e in job.events))

    async def test_reading_notes_shared_across_questions(self):
        first_model = FakeModel()
        job, _ = self.runner(first_model, question="研究经营变化。")
        await _.run()
        self.assertGreater(first_model.count("reading"), 0)
        second_model = FakeModel()
        second, runner = self.runner(second_model, question="完全不同的问题：研究风险。")
        await runner.run()
        self.assertEqual(second.status, "completed", second.error)
        self.assertEqual(second_model.count("reading"), 0)
        self.assertTrue(any(e["type"] == "reading_cache_reused" for e in second.events))

    async def test_legacy_question_keyed_notes_are_migrated(self):
        job, runner = self.runner(question="旧问题")
        await runner.dispatch("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        fetched = self.tools.execute("fetch_document", {"documentId": DOC_ID})["data"]["document"]
        batch = self.tools.execute(
            "read_document_batch",
            {"documentId": DOC_ID, "startPage": 1, "offset": 0, "maxPages": 20, "maxCharacters": runner.limits.read_characters},
        )["data"]
        legacy_task = {"question": "旧问题", "sourceId": DOC_ID, "title": fetched["title"], "pages": batch["pages"]}
        legacy_key = stable_key(
            {
                "messages": [
                    {"role": "system", "content": LEGACY_READ_SYSTEM},
                    {"role": "user", "content": json.dumps(legacy_task, ensure_ascii=False)},
                ],
                "model": SETTINGS.model,
                "sha256": fetched["sha256"],
            }
        )
        note = {"summary": "旧笔记", "facts": [{"text": "旧事实", "pages": [1]}], "gaps": []}
        DerivedCache(self.tools.store.root / "reading-notes", "note").save(legacy_key, note, runId="old-run")
        model = FakeModel()
        runner.completion = model
        await runner.read({"documentId": DOC_ID, "mode": "full"})
        self.assertEqual(model.count("reading"), 0)
        self.assertEqual(runner.notes[DOC_ID][0]["summary"], "旧笔记")

    async def test_second_full_read_does_not_resend_notes(self):
        job, runner = self.runner()
        await runner.dispatch("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        first = await runner.read({"documentId": DOC_ID, "mode": "full"})
        second = await runner.read({"documentId": DOC_ID, "mode": "full"})
        self.assertIn("notes", first)
        self.assertNotIn("notes", second)
        self.assertTrue(second["notesAlreadyProvided"])

    async def test_multi_page_lookup_in_one_call(self):
        job, runner = self.runner()
        await runner.dispatch("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        await runner.read({"documentId": DOC_ID, "mode": "full"})
        result = await runner.read({"documentId": DOC_ID, "mode": "page", "pages": [1, 2]})
        self.assertEqual([p["page"] for p in result["pages"]], [1, 2])
        for i in range(3):
            runner.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(i),
                    "content": json.dumps(
                        {"data": {"sourceId": DOC_ID, "pages": [{"page": 1, "text": "原文" * 4000}, {"page": 2, "text": "原文" * 4000}]}}
                    ),
                }
            )
        context = runner.context()
        oldest = json.loads([m for m in context if m.get("tool_call_id") == "0"][0]["content"])
        self.assertEqual(len(oldest["data"]["pages"][0]["text"]), 700)
        self.assertEqual(len(json.loads(runner.messages[-3]["content"])["data"]["pages"][0]["text"]), 8000)

    async def test_context_parses_each_tool_message_once(self):
        _, runner = self.runner()
        for i in range(4):
            runner.messages.append({"role": "tool", "tool_call_id": str(i), "content": json.dumps({"data": {"page": 1, "text": "原文" * 4000}})})
        builds = []
        original = ToolView.build
        with patch.object(ToolView, "build", side_effect=lambda content: builds.append(1) or original(content)):
            first = runner.context()
            second = runner.context()
        self.assertEqual(len(builds), 4)  # 第二轮直接复用投影
        self.assertEqual(first, second)
        runner.messages[-1] = {**runner.messages[-1], "content": json.dumps({"data": {"page": 2, "text": "新"}})}
        runner.context()
        self.assertEqual(json.loads(runner.tool_views["3"].projected)["data"]["page"], 2)  # 内容变化时重建

    async def test_full_read_notes_do_not_count_as_page_lookups(self):
        # 以前用字符串 '"text"' 判断，通读笔记（facts.text）也被算作回查，会把真正的回查原文提前截断。
        _, runner = self.runner()
        for i in range(2):
            runner.messages.append({"role": "tool", "tool_call_id": f"p{i}", "content": json.dumps({"data": {"page": 1, "text": "原文" * 4000}})})
        note = {"summary": "要点", "facts": [{"text": "事实", "pages": [1]}], "gaps": []}
        runner.messages.append({"role": "tool", "tool_call_id": "full", "content": json.dumps({"data": {"sourceId": DOC_ID, "notes": [note]}})})
        context = {m.get("tool_call_id"): m for m in runner.context()}
        for key in ("p0", "p1"):
            self.assertEqual(len(json.loads(context[key]["content"])["data"]["text"]), 8000)

    async def test_review_unchanged_skips_full_rewrite(self):
        model = FakeModel(review={"unchanged": True})
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["run"]["reviewOutcome"], "unchanged")
        revised = report()
        revised["summary"] = "复核后的摘要"
        model = FakeModel(review=revised)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.report["summary"], "复核后的摘要")
        self.assertEqual(job.report["run"]["reviewOutcome"], "revised")

    async def test_state_message_is_compact(self):
        _, runner = self.runner()
        runner.financial_points = [
            {
                "metric": "revenue",
                "year": 2024,
                "period": "annual",
                "value": 1e9,
                "sourceId": DOC_ID,
                "page": 1,
                "rawValue": "1,000,000,000",
                "unit": "元",
                "publishedAt": "2025-03-10",
                "verification": "x",
            }
        ]
        state = runner.context()[-2]["content"]
        self.assertIn("financialData", state)
        self.assertNotIn('"evidence"', state)
        self.assertNotIn('"quote"', state)

    async def test_usage_keeps_cache_hit_and_miss(self):
        self.assertEqual(
            usage_counts({**USAGE, "other": 5, "prompt_cache_hit_tokens": -1}),
            {k: v for k, v in USAGE.items() if k != "prompt_cache_hit_tokens"},
        )
        job, runner = self.runner()
        await runner.run()
        self.assertGreater(job.report["run"]["usage"]["prompt_cache_hit_tokens"], 0)
        self.assertIn("prompt_cache_miss_tokens", job.report["run"]["usage"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
