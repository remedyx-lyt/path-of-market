"""无缓存阅读故障回归：走真实分页/游标与模型协议，模型/数据供应商均隔离，不消耗 API 额度。"""

import json
import os
import unittest
from unittest.mock import patch

from support import DOC_ID, USAGE, FakeModel, RunnerFixture, report, section

from app.core.config import ModelServiceError, load_model_settings
from app.services.model_client import complete_turn
from app.services.session_recorder import SessionRecorder
from app.tools.contracts import ToolError


def truncated(limit=1800):
    error = ModelServiceError("MODEL_INVALID_RESPONSE", "模型输出不完整", 502)
    error.finish_reason = "length"
    error.usage = {"prompt_tokens": 100, "completion_tokens": limit, "total_tokens": 100 + limit}
    return error


class DenseModel(FakeModel):
    async def __call__(self, settings, messages, **kwargs):
        if self.kind(messages, kwargs) == "reading":
            pages = json.loads(messages[1]["content"])["pages"]
            if sum(len(p["text"]) for p in pages) > 2000:
                self.calls.append(("truncated", kwargs["max_tokens"], messages, kwargs))
                raise truncated(kwargs["max_tokens"])
        return await super().__call__(settings, messages, **kwargs)


class Recovery(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def discover(self, runner):
        await runner.dispatch("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})

    async def test_cold_read_splits_until_complete_without_double_counting(self):
        model = DenseModel(ready=True)
        job, runner = self.runner(model)
        self.assertFalse((self.tools.store.root / "reading-notes").exists())
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        coverage = runner.coverage[DOC_ID]
        pages = self.tools.store.loaded(DOC_ID)[1]
        self.assertTrue(coverage["textComplete"])
        self.assertEqual(coverage["processedPages"], [1, 2])
        self.assertEqual(coverage["processedCharacters"], sum(len(p["text"]) for p in pages))
        self.assertGreater(model.count("truncated"), 0)
        self.assertGreater(model.count("reading"), 1)
        self.assertTrue(any(e["type"] == "reading_batch_split" for e in job.events))
        self.assertTrue(all(c[1] == 3600 for c in model.calls if c[0] in {"reading", "truncated"}))

    async def test_245_page_cold_document_recovers_at_page_21_and_finishes(self):
        class Page21(FakeModel):
            failed = False

            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading":
                    pages = json.loads(messages[1]["content"])["pages"]
                    if pages[0]["page"] == 21 and not self.failed:
                        self.failed = True
                        raise truncated(kwargs["max_tokens"])
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(Page21())
        metadata = {"documentId": DOC_ID, "title": "245页隔离年报", "sourceUrl": "https://example.com/report.pdf",
                    "publishedAt": "2026-03-10", "pageCount": 245, "fiscalYear": 2025, "reportType": "annual"}
        pages = [{"page": n, "pageLabel": str(n), "text": f"隔离第{n}页。" * 40} for n in range(1, 246)]
        runner.source(metadata)
        with patch.object(self.tools.store, "loaded", return_value=(metadata, pages)):
            await runner.read_all_batches(DOC_ID, metadata, "isolated-hash")
        coverage = runner.coverage[DOC_ID]
        self.assertTrue(coverage["textComplete"])
        self.assertEqual(coverage["processedPages"], list(range(1, 246)))
        self.assertEqual(coverage["processedCharacters"], sum(len(p["text"]) for p in pages))
        self.assertLess(job.model_calls, 40)
        self.assertEqual(sum(e["type"] == "reading_batch_split" for e in job.events), 1)

    async def test_failed_batch_preserves_cursor_and_resume_finishes_the_remainder(self):
        class Once(FakeModel):
            failed = False

            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading" and self.count("reading") == 1 and not self.failed:
                    self.failed = True
                    raise truncated()
                return await super().__call__(settings, messages, **kwargs)

        model = Once()
        job, runner = self.runner(model, limits={"read_characters": 1000})
        await self.discover(runner)
        with self.assertRaises(ToolError) as raised:
            await runner.read({"documentId": DOC_ID})
        self.assertEqual(raised.exception.code, "READING_BATCH_FAILED")
        self.assertEqual(runner.coverage[DOC_ID]["processedCharacters"], 1000)
        self.assertFalse(runner.coverage[DOC_ID]["textComplete"])
        self.assertEqual(runner.coverage[DOC_ID]["nextCursor"], {"startPage": 1, "offset": 1000})
        await runner.read({"documentId": DOC_ID})
        self.assertTrue(runner.coverage[DOC_ID]["textComplete"])
        self.assertEqual(runner.coverage[DOC_ID]["processedCharacters"], sum(len(p["text"]) for p in self.tools.store.loaded(DOC_ID)[1]))

    async def test_bad_json_after_repair_also_splits_and_completes(self):
        class BadJson(DenseModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading":
                    pages = json.loads(messages[1]["content"])["pages"]
                    if sum(len(p["text"]) for p in pages) > 2000:
                        return {"role": "assistant", "content": "not json"}, USAGE
                return await FakeModel.__call__(self, settings, messages, **kwargs)

        job, runner = self.runner(BadJson())
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertTrue(any(e["type"] == "reading_note_invalid" and e["problems"] for e in job.events))

    async def test_persistent_failure_remains_unread_and_other_tools_can_run(self):
        class Broken(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading":
                    raise truncated()
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(Broken(), limits={"read_characters": 1000})
        await self.discover(runner)
        await runner.run_tool_call({"id": "read", "function": {"name": "read_document", "arguments": json.dumps({"documentId": DOC_ID})}})
        failure = json.loads(runner.messages[-1]["content"])
        self.assertEqual(failure["error"]["code"], "READING_BATCH_FAILED")
        self.assertEqual(runner.coverage[DOC_ID]["processedPages"], [])
        self.assertFalse(runner.coverage[DOC_ID]["textComplete"])
        self.assertEqual(job.tool_calls[-1]["status"], "failed")
        await runner.run_tool_call({"id": "market", "function": {"name": "get_market_data", "arguments": json.dumps(
            {"company": "同花顺", "startDate": "2024-01-01", "endDate": "2026-10-23"})}})
        self.assertEqual(job.tool_calls[-1]["status"], "completed")
        with self.assertRaises(ValueError):
            runner.validate_content({"content": json.dumps(report())})  # 不能把未读完标成完成报告

    async def test_auth_failure_is_fatal_instead_of_retried_as_a_document_gap(self):
        class AuthFailure(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading":
                    raise ModelServiceError("MODEL_AUTH_FAILED", "密钥无效")
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(AuthFailure())
        await runner.run()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error["code"], "MODEL_AUTH_FAILED")

    async def test_temporary_read_error_retries_same_cursor(self):
        class Temporary(FakeModel):
            failed = False

            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "reading" and not self.failed:
                    self.failed = True
                    raise ModelServiceError("MODEL_TIMEOUT", "临时超时")
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(Temporary())
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertTrue(any(e["type"] == "reading_batch_retry" for e in job.events))

    async def test_provider_length_reason_usage_and_budget_are_persisted(self):
        job, runner = self.runner()
        job.recorder = SessionRecorder(job.session_id, job.task_id)
        runner.completion = complete_turn
        body = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": '{"summary":"unfinished'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 3600, "total_tokens": 3700}}
        with patch("app.services.model_client._request_payload", return_value=body) as call:
            with self.assertRaises(ModelServiceError):
                await runner.model([{"role": "user", "content": "read"}], reading=True)
        self.assertEqual(call.call_args[0][1]["max_tokens"], 3600)
        event = next(e for e in job.events if e["type"] == "model_failed")
        self.assertEqual((event["finishReason"], event["outputTokenLimit"], event["usage"]["completion_tokens"]), ("length", 3600, 3600))
        self.assertEqual(job.usage["total_tokens"], 3700)
        self.assertTrue(any(e.get("data", {}).get("type") == "model_failed" for e in job.recorder.pending))

    async def test_method_invalid_diagnostics_and_short_reference_repair(self):
        def plan(task, attempt):
            if attempt == 1:
                return {"focus": "f"}
            result = FakeModel().default_plan(task)
            result["checks"] = [{**check, "methodReference": check["methodReference"].split("/skills/")[1]} for check in result["checks"]]
            return result

        job, runner = self.runner(FakeModel(plan=plan), omens=["exalted", "opportunity", "abyssal_echoes"])
        await runner.prepare_methods()
        self.assertEqual(runner.method_usage["status"], "planned")
        self.assertTrue(runner.method_usage["diagnostics"][0]["problems"])
        self.assertTrue(any(e["type"] == "methods_plan_invalid" for e in job.events))
        self.assertTrue(all(c["methodReference"].startswith("plugins/") for c in runner.method_usage["plan"]["checks"]))

    async def test_truncated_method_plan_falls_back_and_research_continues(self):
        class PlanFailure(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "plan":
                    raise truncated(6500)
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(PlanFailure())
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(runner.method_usage["status"], "plan_failed")
        self.assertEqual(runner.method_usage["diagnostics"][0]["finishReason"], "length")

    async def test_discarded_review_really_keeps_original_report_and_tables(self):
        revised = report([section("新一", "a"), section("新二", "b"), section("新三", "c")])
        table = {"section": 0, "title": "保留的表", "columns": ["产量"], "rows": [{"label": "a", "cells": ["1"], "sourceId": DOC_ID, "page": 2}]}
        job, runner = self.runner(FakeModel(review=revised, tables=[{"tables": [table]}]))
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["run"]["reviewOutcome"], "discarded")
        self.assertEqual(len(job.report["sections"]), 2)
        self.assertEqual(job.report["sections"][0]["heading"], "经营证据")
        self.assertEqual(job.report["sections"][0]["tables"][0]["title"], "保留的表")

    def test_reading_output_budget_has_independent_configuration(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "isolated-test", "LLM_MAX_TOKENS": "1800", "LLM_READING_MAX_TOKENS": "4096"}):
            self.assertEqual(load_model_settings().reading_max_tokens, 4096)
        for value in ("0", "8193", "nan"):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "isolated-test", "LLM_READING_MAX_TOKENS": value}), self.assertRaises(ModelServiceError):
                load_model_settings()

    def test_table_verification_preserves_negative_sign(self):
        from app.services.report_figures import check_table

        table = {"rows": [{"sourceId": "d", "page": 1, "cells": ["100.5", "-100.5"]}]}
        checked = check_table(table, lambda *_: "净利润 -100.5")
        self.assertEqual(checked["unmatched"], [[0, 0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
