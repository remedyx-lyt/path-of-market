"""写作结构规范化不吞掉矛盾/截断内容；失败回复可本地恢复，不重复付费。"""
import unittest

from support import RunnerFixture, USAGE
from app.core.config import ModelServiceError
from app.services.runner_writing import json_body


class WritingJSON(unittest.TestCase):
    def test_single_fenced_object(self):
        self.assertEqual(json_body('```json\n{"summary":"摘要"}\n```'), {"summary": "摘要"})

    def test_disjoint_complete_objects_merge_without_changing_values(self):
        self.assertEqual(json_body('{"summary":"摘要"}\n{"omenCoverage":[]}'), {"summary": "摘要", "omenCoverage": []})

    def test_conflicting_objects_truncated_tail_and_narrative_rejected(self):
        for raw in ['{"summary":"一"}{"summary":"二"}', '{"summary":"一"}{"omenCoverage":',
                    '{"summary":"一"}解释', '{"summary":"一"}[]']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                json_body(raw)


class WritingRecovery(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_saved_response_is_revalidated_locally_before_new_model_call(self):
        async def no_call(*args, **kwargs):
            raise AssertionError("完整回复本地可恢复，不应调用模型")

        job, runner = self.runner(no_call)
        runner.writing_state = {"lastFailure": {"unit": "摘要", "problems": ["JSON: Extra data"],
                               "response": '{"summary":"摘要"}{"omenCoverage":[]}'}}
        result = await runner.writing_json("prompt", lambda b: b["summary"], label="摘要")
        self.assertEqual(result, "摘要")
        self.assertEqual(job.model_calls, 0)
        self.assertTrue(any(e["type"] == "writing_unit_recovered" for e in job.events))

    async def test_failed_response_is_saved_for_diagnosis_and_future_repair(self):
        async def invalid(*args, **kwargs):
            return {"role": "assistant", "content": '{"summary":"一"}{"summary":"二"}'}, USAGE

        _, runner = self.runner(invalid)
        runner.writing_state = {"sections": []}
        with self.assertRaises(ModelServiceError):
            await runner.writing_json("prompt", lambda b: b, label="摘要")
        failure = runner.writing_state["lastFailure"]
        self.assertEqual(failure["response"], '{"summary":"一"}{"summary":"二"}')
        self.assertFalse(failure["responseTruncated"])
        self.assertEqual(runner.job.model_calls, 2)


if __name__ == "__main__":
    unittest.main()
