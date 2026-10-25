"""复核只提交精确片段；失败后只复核，保留原章节与表格。脚本模型，不调用真实API。"""
from copy import deepcopy
import unittest

from support import FakeModel, RunnerFixture, SETTINGS, report
from app.core.config import ModelServiceError
from app.services.agent_runner import AgentRunner
from app.services.research_jobs import ResearchJob
from app.services.research_recovery import can_retry_review, load_recovery


class ReviewPatches(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_wrong_number_locates_unique_exact_original_text(self):
        job, runner = self.runner(FakeModel(review={"changes": [{"sectionIndex": 2, "oldText": "原文记录", "newText": "披露记录"}]}))
        await runner.run()
        self.assertEqual(job.report["run"]["reviewOutcome"], "revised")
        self.assertIn("披露记录", job.report["sections"][0]["content"])
        self.assertTrue(any(e["type"] == "review_patch_located" for e in job.events))

    async def test_paid_reply_is_reused_locally_after_validation_improvement(self):
        from app.tools.documents import write_json
        model = FakeModel(review={"changes": [{"sectionIndex": 0, "oldText": "不存在", "newText": "替换"}]})
        parent, first = self.runner(model)
        await first.run()
        path = next((self.tools.store.root / "review-replies").glob(parent.task_id + "-*.json"))
        write_json(path, {"reply": '{"changes":[{"sectionIndex":2,"oldText":"原文记录","newText":"披露记录"}]}'})
        recovery = load_recovery(self.tools, parent.task_id, allow_completed=True)
        model = FakeModel()
        child = ResearchJob(parent.request)
        runner = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery)
        await runner.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(model.calls, [])
        self.assertIn("披露记录", child.report["sections"][0]["content"])
        self.assertTrue(any(e["type"] == "review_recovered" for e in child.events))

    async def test_short_exact_patch_preserves_citations_and_other_sections(self):
        changes = {"changes": [{"sectionIndex": 0, "oldText": "原文记录", "newText": "报告披露记录"}]}
        job, _ = self.runner(FakeModel(review=changes))
        await _.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["run"]["reviewOutcome"], "revised")
        self.assertIn("报告披露记录", job.report["sections"][0]["content"])
        self.assertEqual(job.report["sections"][1]["content"], report()["sections"][1]["content"])

    async def test_ambiguous_or_conflicting_patch_cannot_change_report(self):
        for changes in [
            [{"sectionIndex": 0, "oldText": "不存在", "newText": "替换"}],
            [{"sectionIndex": True, "oldText": "原文记录", "newText": "替换"}],
            [{"sectionIndex": 0, "field": "citations", "oldText": "原文记录", "newText": "替换"}],
        ]:
            model = FakeModel(review={"changes": changes})
            job, runner = self.runner(model)
            await runner.run()
            self.assertEqual(job.report["run"]["reviewOutcome"], "discarded")
            self.assertEqual(job.report["sections"][0]["content"], model.final["sections"][0]["content"])

    async def test_truncated_review_retries_short_patches_once(self):
        class Temporary(FakeModel):
            failed = False

            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "review" and not self.failed:
                    self.failed = True
                    error = ModelServiceError("MODEL_INVALID_RESPONSE", "length", 502)
                    error.finish_reason = "length"
                    raise error
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(Temporary())
        await runner.run()
        self.assertEqual(job.report["run"]["reviewOutcome"], "unchanged")
        self.assertEqual(sum(e["type"] == "review_retry" for e in job.events), 1)

    async def test_completed_discarded_review_restores_only_review(self):
        model = FakeModel(review={"changes": [{"sectionIndex": 0, "oldText": "无此片段", "newText": "替换"}]})
        parent, first = self.runner(model)
        await first.run()
        self.assertEqual(parent.report["run"]["reviewOutcome"], "discarded")
        recovery = load_recovery(self.tools, parent.task_id, allow_completed=True)
        self.assertTrue(can_retry_review(recovery, parent.report))
        before = deepcopy(parent.report["sections"])
        child, model = ResearchJob(parent.request), FakeModel()
        resumed = AgentRunner(child, self.tools, SETTINGS, completion=model, recovery=recovery)
        await resumed.run()
        self.assertEqual(child.status, "completed", child.error)
        self.assertEqual(child.report["sections"], before)
        self.assertEqual([c[0] for c in model.calls], ["review"])
        self.assertFalse(can_retry_review(load_recovery(self.tools, child.task_id, allow_completed=True), child.report))


if __name__ == "__main__":
    unittest.main()
