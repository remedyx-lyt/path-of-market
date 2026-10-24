"""重构后的公共部件：JSON 重试、派生缓存、方法计划校验、视觉模型配置、异常日志。"""

import asyncio
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import patch

from support import DOC_ID, FakeModel, RunnerFixture, SETTINGS, report, section

from app.core.config import ModelServiceError, ModelSettings, load_model_settings
from app.schemas.agent import MethodPlan
from app.services.model_json import DerivedCache, ask_json, stable_key
from app.tools.contracts import ToolError


class Helpers(unittest.IsolatedAsyncioTestCase):
    async def test_ask_json_repairs_once_then_raises(self):
        replies = iter(["not json", '{"ok": 1}'])
        sent = []

        async def call(messages):
            sent.append(messages)
            return {"role": "assistant", "content": next(replies)}

        import json

        value, _ = await ask_json(call, [{"role": "user", "content": "q"}], json.loads, "fix it")
        self.assertEqual(value, {"ok": 1})
        self.assertEqual(sent[1][-1]["content"], "fix it")
        self.assertEqual(len(sent[0]), 1)  # 原消息列表不被修改

        async def always_bad(messages):
            return {"role": "assistant", "content": "bad"}

        with self.assertRaises(ValueError):
            await ask_json(always_bad, [], json.loads, "fix")

    def test_derived_cache_round_trip_and_corruption(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as temp:
            cache = DerivedCache(Path(temp), "result")
            key = stable_key({"b": 1, "a": [1, 2]})
            self.assertEqual(key, stable_key({"a": [1, 2], "b": 1}))
            self.assertEqual(cache.load(key, dict), (None, None))
            cache.save(key, {"x": 1}, runId="run-1")
            self.assertEqual(cache.load(key, dict), ({"x": 1}, "run-1"))
            cache.path(key).write_text("{broken", encoding="utf-8")
            self.assertEqual(cache.load(key, dict), (None, None))

    def test_method_plan_schema_replaces_asserts(self):
        check = {"topic": "business", "question": "q", "evidenceNeeded": "e", "figureIdea": "", "methodReference": "p"}
        MethodPlan.model_validate({"focus": "f", "checks": [check] * 3})
        for bad in (
            {"focus": "f", "checks": [check] * 2},
            {"checks": [check] * 3},
            {"focus": "f", "checks": [{**check, "question": 1}] * 3},
        ):
            with self.assertRaises(ValueError):
                MethodPlan.model_validate(bad)


class RunnerParts(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_vision_models_come_from_settings(self):
        from app.services.agent_runner import AgentRunner
        from app.services.research_jobs import ResearchJob
        from app.schemas.agent import AgentResearchRequest

        job = ResearchJob(AgentResearchRequest(target="同花顺", question="q", asOfDate="2026-10-23"))
        await asyncio.to_thread(self.tools.execute, "find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        settings = ModelSettings("k", SETTINGS.base_url, "text-only-model", 1, 1800, ("some-vision-model",))
        runner = AgentRunner(job, self.tools, settings)  # 默认真实供应商路径，但在联网前就应拒绝
        with self.assertRaises(ToolError) as error:
            await runner.inspect({"documentId": "cninfo-1234567890", "pages": [1]})
        self.assertEqual(error.exception.code, "VISION_MODEL_UNSUPPORTED")

    async def test_unexpected_error_is_logged_with_traceback(self):
        job, runner = self.runner()

        async def broken(*args, **kwargs):
            raise RuntimeError("boom")

        runner.prepare_methods = broken
        with self.assertLogs("path_of_market.agent", level="ERROR") as logs:
            await runner.run()
        self.assertEqual(job.status, "failed")
        self.assertIn("boom", "\n".join(logs.output))
        self.assertNotIn("boom", job.error["message"])  # 网页只看到受控错误

    async def test_unknown_tool_rejected_by_dispatch_table(self):
        _, runner = self.runner()
        with self.assertRaises(ToolError) as error:
            await runner.dispatch("bash", {"command": "x"})
        self.assertEqual(error.exception.code, "UNKNOWN_TOOL")

    async def test_report_calls_use_report_timeout(self):
        seen = []

        class Recording(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                seen.append((self.kind(messages, kwargs), settings.timeout_seconds))
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(Recording(ready=True))
        runner.settings = replace(SETTINGS, report_timeout_seconds=99)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        timeouts = {kind: {t for k, t in seen if k == kind} for kind, _ in seen}
        self.assertEqual(timeouts["decision"], {SETTINGS.timeout_seconds})
        self.assertEqual(timeouts["compose"], {99})
        self.assertEqual(timeouts["review"], {99})

    def test_report_timeout_setting_is_bounded(self):
        base = {"DEEPSEEK_API_KEY": "isolated-test-key-only", "LLM_TIMEOUT_SECONDS": "60", "LLM_MAX_TOKENS": "1800"}
        with patch.dict(os.environ, {**base, "LLM_REPORT_TIMEOUT_SECONDS": "240"}):
            self.assertEqual(load_model_settings().report_timeout_seconds, 240)
        for bad in ("30", "601"):  # 不得短于研究轮次，也不超过 600 秒
            with patch.dict(os.environ, {**base, "LLM_REPORT_TIMEOUT_SECONDS": bad}), self.assertRaises(ModelServiceError):
                load_model_settings()

    async def test_context_near_limit_wraps_up_with_report(self):
        # 真实验收案例 B 曾在上下文越过上限时直接停止、只留部分结果；现在接近上限就停止取证并写报告。
        from support import DEFAULT_SCRIPT
        from app.services.agent_runner import context_characters

        script = DEFAULT_SCRIPT[:2] + [[("read_document", {"documentId": DOC_ID, "mode": "page", "page": 1})], "final"]
        probe = FakeModel(script=script)
        _, runner = self.runner(probe)
        await runner.run()
        sizes = [context_characters(c[2]) for c in probe.calls if c[0] == "decision"]
        threshold = (sizes[1] + sizes[2]) // 2  # 第三轮决策前越过
        model = FakeModel(script=script)
        job, runner = self.runner(model, limits={"max_context_characters": threshold + 50000, "context_reserve_characters": 50000})
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.count("decision"), 2)  # 第三轮不再让模型选工具
        self.assertEqual(model.count("compose"), 1)
        self.assertTrue(any(e["type"] == "context_wrapup" for e in job.events))
        self.assertTrue(any("提前结束取证" in item for item in job.report["limitations"]))

    async def test_wrapup_records_missing_required_evidence_as_limitation(self):
        # 真实验收案例 C：收尾时还没取得行情，硬性核查连续退回三次后只留部分结果；现在记入局限。
        from support import DEFAULT_SCRIPT
        from app.services.agent_runner import context_characters

        find = DEFAULT_SCRIPT[0][0]
        script = [[find], DEFAULT_SCRIPT[1][0:1], [("read_document", {"documentId": DOC_ID, "mode": "page", "page": 1})], "final"]
        probe = FakeModel(script=script)
        _, runner = self.runner(probe)
        await runner.run()
        sizes = [context_characters(c[2]) for c in probe.calls if c[0] == "decision"]
        threshold = (sizes[1] + sizes[2]) // 2
        final = report([section("经营证据", "原文记录需结合单位与年度解释。"), section("未取得行情", "取证提前结束，本次没有行情数据。", page=2)])
        model = FakeModel(script=script, final=final)
        job, runner = self.runner(model, limits={"max_context_characters": threshold + 50000, "context_reserve_characters": 50000})
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.count("compose"), 1)  # 缺行情不再反复退回重写
        self.assertIn("提前结束取证，未完成：本任务要求的行情分析未取得行情数据。", job.report["limitations"])

    async def test_invalid_arguments_tell_the_model_what_is_wrong(self):
        _, runner = self.runner()
        call = {"id": "c1", "function": {"name": "get_market_data", "arguments": json.dumps(
            {"company": "同花顺", "startDate": "2021-10-23", "endDate": "2026-10-23"})}}
        await runner.run_tool_call(call)
        error = json.loads(runner.messages[-1]["content"])["error"]
        self.assertEqual(error["code"], "INVALID_TOOL_ARGUMENTS")
        self.assertTrue(any("最多约三年" in p for p in error["details"]["problems"]))

    def test_mechanical_overflows_are_normalized_not_rewritten(self):
        # 真实验收案例 C 的三次重写都因这类机械超限：图层级多余 citations、章节引用 14 条、图节点引用 4 条。
        from app.schemas.agent import AgentContent
        from app.services.runner_report import normalize_report

        cite = [{"sourceId": DOC_ID, "page": p} for p in range(1, 15)]
        node = {"label": "n", "detail": "d", "citations": cite[:4] + cite[:1]}
        draft = report([
            {**section("甲", "a"), "citations": cite + cite[:2]},
            {**section("乙", "b"), "visual": {"kind": "cards", "title": "t", "citations": cite[:1], "nodes": [node, node]}},
        ])
        raw, fixes = normalize_report(json.dumps(draft))
        content = AgentContent.model_validate_json(raw)
        self.assertEqual(len(content.sections[0].citations), 12)
        self.assertEqual([len(n.citations) for n in content.sections[1].visual.nodes], [3, 3])
        self.assertEqual(len(fixes), 4)
        self.assertEqual(normalize_report(json.dumps(report())), (json.dumps(report()), []))  # 合格草稿原样返回

    async def test_repeated_figures_are_removed_instead_of_rewriting(self):
        job, runner = self.runner()
        runner.source({"documentId": DOC_ID, "title": "t", "sourceUrl": "u", "publishedAt": "2025-03-10", "pageCount": 2, "fiscalYear": 2024})
        runner.coverage[DOC_ID].update(textComplete=True, processedPages=[1, 2])
        runner.market_data = {"limitations": []}
        runner.sources["market-300033"] = {"sourceId": "market-300033", "kind": "market"}
        sections = [
            {**section("收入", "a"), "chartIds": ["annual-revenue", "annual-margin"]},
            {**section("风险", "b"), "chartIds": ["annual-revenue"], "businessIds": ["product-annual"]},
            {**section("行情", "c", market=True), "businessIds": ["product-annual"]},
        ]
        charts = {"charts": [{"id": "annual-revenue"}, {"id": "annual-margin"}], "gaps": []}
        with patch.object(runner, "financial_data", return_value=charts), patch.object(
            runner, "business_data", return_value={"datasets": [{"id": "product-annual"}]}
        ):
            content = runner.validate_content({"content": json.dumps(report(sections))})
        self.assertEqual([s.chart_ids for s in content.sections], [["annual-revenue", "annual-margin"], [], []])
        self.assertEqual([s.business_ids for s in content.sections], [[], ["product-annual"], []])
        removed = [e for e in job.events if e["type"] == "figure_duplicates_removed"]
        self.assertEqual(removed[0]["removed"], ["annual-revenue", "product-annual"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
