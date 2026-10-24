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

    def evidence_ready(self, runner):
        runner.source({"documentId": DOC_ID, "title": "年报", "sourceUrl": "u", "publishedAt": "2025-03-10", "pageCount": 2, "fiscalYear": 2024})
        runner.coverage[DOC_ID].update(textComplete=True, processedPages=[1, 2])
        runner.market_data = {"limitations": []}
        runner.sources["market-300033"] = {"sourceId": "market-300033", "kind": "market"}

    async def test_operating_table_is_requested_again_then_recorded(self):
        # 写作第二步单独生成数据表；必做的产能/产销表缺失时补要一次，仍缺则写入局限，报告照常完成。
        table = {"section": 0, "title": "产销量", "unit": "万只", "columns": ["产量", "销量"],
                 "rows": [{"label": "光模块", "cells": ["2,376", "2,109"], "sourceId": DOC_ID, "page": 2}]}
        model = FakeModel(tables=[{"tables": []}, {"tables": [table]}])
        job, runner = self.runner(model)
        with patch.object(runner, "operating_pages", return_value={DOC_ID: [2]}):
            await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(model.count("tables"), 2)
        self.assertEqual(job.report["sections"][0]["tables"][0]["title"], "产销量")
        model = FakeModel(tables=[{"tables": []}])
        job, runner = self.runner(model)
        with patch.object(runner, "operating_pages", return_value={DOC_ID: [2]}):
            await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertTrue(any("未能生成对应数据表" in item for item in job.report["limitations"]))

    async def test_bad_tables_are_dropped_and_quotes_repaired(self):
        _, runner = self.runner()
        await runner.run()  # 完成通读，使第2页成为已处理页
        good = {"section": 0, "title": "好表", "columns": ["产量"], "rows": [{"label": "a", "cells": ["1"], "sourceId": DOC_ID, "page": 2}]}
        bad_page = {**good, "title": "页码不对", "rows": [{"label": "a", "cells": ["1"], "sourceId": DOC_ID, "page": 99}]}
        bad_section = {**good, "section": 9}
        raw = json.dumps({"tables": [good, bad_page, bad_section]}, ensure_ascii=False).replace("好表", '好"表"')
        parsed = runner.parse_tables(raw, 2)
        self.assertEqual([t.title for _, t in parsed], ['好"表"'])
        numeric = {"section": "0", "title": "数值格", "columns": ["产量", "毛利率"], "rows": [{"label": 2025, "cells": [2376, 42.61], "sourceId": DOC_ID, "page": 2}]}
        parsed = runner.parse_tables(json.dumps({"tables": [numeric]}), 2)  # 真实运行中模型常把数字写成数值
        self.assertEqual(parsed[0][1].rows[0].cells, ["2376", "42.61"])

    async def test_unknown_figure_ids_and_uncited_nodes_are_removed(self):
        # 真实运行案例 A：自拟图表 ID、定性图节点无来源，都曾让整篇报告重写。
        job, runner = self.runner()
        self.evidence_ready(runner)
        node = {"label": "n", "detail": "d", "citations": [{"sourceId": DOC_ID, "page": 1}]}
        sections = [
            {**section("经营", "a"), "chartIds": ["made-up-chart"], "visual": {"kind": "cards", "title": "t", "nodes": [node, node, {**node, "citations": []}]}},
            {**section("风险", "b"), "visual": {"kind": "cards", "title": "t", "nodes": [node, {**node, "citations": []}]}},
        ]
        content = runner.validate_content({"content": json.dumps(report(sections))})
        self.assertEqual(content.sections[0].chart_ids, [])
        self.assertEqual(len(content.sections[0].visual.nodes), 2)
        self.assertIsNone(content.sections[1].visual)  # 只剩 1 个有来源节点，不放这张图
        self.assertTrue(any(e["type"] == "unknown_figures_removed" for e in job.events))

    async def test_required_figures_are_placed_by_program(self):
        job, runner = self.runner()
        self.evidence_ready(runner)
        sections = [{**section("经营", "a", topics=["business"])}, {**section("资产负债", "b", topics=["balance_sheet"]), "chartIds": ["annual-revenue"]}]
        charts = {"charts": [{"id": "annual-revenue", "keys": ["revenue"]}, {"id": "annual-balance", "keys": ["totalAssets", "totalLiabilities"]}], "gaps": []}
        rows = lambda *shares: [{"items": [{"share": s} for s in shares]}]
        business = {"datasets": [
            {"id": "product-annual", "dimension": "product", "rows": rows(55.0, 45.0)},
            {"id": "geography-annual", "dimension": "geography", "rows": rows(93.0, 7.0)},  # 单一地区占九成以上，不强制
        ]}
        with patch.object(runner, "financial_data", return_value=charts), patch.object(runner, "business_data", return_value=business):
            content = runner.validate_content({"content": json.dumps(report(sections))})
        self.assertEqual(content.sections[0].business_ids, ["product-annual"])
        self.assertEqual(content.sections[1].chart_ids, ["annual-revenue", "annual-balance"])
        placed = [e for e in job.events if e["type"] == "required_figures_placed"]
        self.assertEqual(placed[0]["added"], ["annual-balance", "product-annual"])

    def test_table_cells_are_checked_against_cited_page(self):
        from app.services.report_figures import check_table

        texts = {2: "项目 单位 2025 年 光通信模块 销售量 万只 2,109 生产量 2,376 库存量 521 同比 105.12%"}
        table = {"rows": [{"sourceId": "d", "page": 2, "cells": ["2,109", "2,376", "88.8%", "光模块"]}]}
        result = check_table(table, lambda sid, page: texts.get(page, ""))
        self.assertEqual(result, {"checkedCells": 3, "matchedCells": 2, "unmatched": [[0, 2]]})  # 88.8% 是计算值

    def test_real_table_mistakes_are_normalized(self):
        # 真实运行：columns 多写了行名表头“期间”、chartColumns 按含表头的序号且多于4列、行情行没有页码、页码写成文字。
        from app.schemas.agent import AgentContent
        from app.services.runner_report import normalize_report

        rows = [{"label": "2024年", "cells": ["2,088", "1,536", "1,459", "34.65%", "70%"], "sourceId": DOC_ID, "page": "2"},
                {"label": "2025年", "cells": ["2,806", "2,376", "2,109", "42.61%", "85%"], "sourceId": "market-300033", "page": None}]
        table = {"title": "产销", "unit": "万只", "columns": ["期间", "产能", "产量", "销量", "毛利率", "利用率"], "rows": rows,
                 "chart": "bar", "chartColumns": [1, 2, 3, 4, 5], "note": ""}
        broken = {"title": "坏表", "columns": ["a", "b"], "rows": [{"label": "x", "cells": ["1", "2", "3", "4"], "sourceId": DOC_ID, "page": 1}]}
        raw, fixes = normalize_report(json.dumps(report([{**section("经营", "a"), "tables": [table, broken]}, section("b", "c")])))
        t = AgentContent.model_validate_json(raw).sections[0].tables
        self.assertEqual(len(t), 1)  # 行列对不上的表去掉，不拖累整篇
        self.assertEqual((t[0].label_header, t[0].columns[0], t[0].chart_columns), ("期间", "产能", [0, 1, 2, 3]))
        self.assertEqual([r.page for r in t[0].rows], [2, None])
        self.assertEqual(len(fixes), 4)

    async def test_review_failure_or_revision_keeps_tables(self):
        from app.core.config import ModelServiceError

        table = {"section": 0, "title": "产销量", "columns": ["产量"], "rows": [{"label": "a", "cells": ["1"], "sourceId": DOC_ID, "page": 2}]}

        class BrokenReview(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "review":
                    raise ModelServiceError("MODEL_INVALID_RESPONSE", "输出不完整", 502)
                return await super().__call__(settings, messages, **kwargs)

        job, runner = self.runner(BrokenReview(tables=[{"tables": [table]}]))
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["run"]["reviewOutcome"], "discarded")
        revised = report()
        revised["summary"] = "复核后的摘要"
        model = FakeModel(review=revised, tables=[{"tables": [table]}])
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.report["summary"], "复核后的摘要")
        self.assertEqual(job.report["sections"][0]["tables"][0]["title"], "产销量")  # 复核不带表，完成后原样挂回
        review_input = json.loads(next(c[2] for c in model.calls if c[0] == "review")[1]["content"])
        self.assertNotIn("tables", review_input["candidate"]["sections"][0])

    def test_extra_sections_are_merged_and_wrapper_removed(self):
        from app.schemas.agent import AgentContent
        from app.services.runner_report import normalize_report

        sections = [section(f"第{i}节", f"正文{i}") for i in range(1, 15)]
        raw, fixes = normalize_report(json.dumps({"candidate": report(sections)}))
        content = AgentContent.model_validate_json(raw)
        self.assertEqual(len(content.sections), 12)
        last = content.sections[-1].content
        self.assertTrue(all(f"【第{i}节】" in last and f"正文{i}" in last for i in (12, 13, 14)))  # 正文全保留
        self.assertTrue(any("candidate" in f for f in fixes) and any("合并为一节" in f for f in fixes))

    async def test_invalid_review_keeps_checked_report(self):
        job, runner = self.runner(FakeModel(review={"candidate": "坏的复核稿"}))
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["run"]["reviewOutcome"], "discarded")
        self.assertTrue(any(e["type"] == "review_discarded" for e in job.events))

    def test_table_check_allows_unit_conversion_and_extra_sources(self):
        from app.services.report_figures import check_table

        texts = {1: "营业收入（元） 38,240,177,201.48 23,862,155,079.13", 2: "营业收入（元） 10,717,852,567.26"}
        row = {"sourceId": "d", "page": 1, "cells": ["382.40", "238.62", "107.18", "35,900.5"], "alsoFrom": [{"sourceId": "d", "page": 2}]}
        result = check_table({"rows": [row]}, lambda sid, page: texts.get(page, ""))
        self.assertEqual(result["unmatched"], [[0, 3]])  # 亿元换算与补充来源页都能对上；最后一格对不上
        row.pop("alsoFrom")
        self.assertEqual(check_table({"rows": [row]}, lambda sid, page: texts.get(page, ""))["unmatched"], [[0, 2], [0, 3]])

    def test_page_lists_and_operating_table_detection(self):
        # 真实运行：行里写 pages 列表导致产能表被丢；另一张收入表引用同一页，被误当成已有产能表而未补要。
        from app.schemas.agent import SectionTable
        from app.services.runner_report import normalize_table, operating_table_present

        row = {"label": "2025年", "cells": ["2,806"], "sourceId": DOC_ID, "pages": [13, 25]}
        capacity = SectionTable.model_validate(normalize_table({"title": "产能与产量", "columns": ["产能"], "rows": [row]}, 0, []))
        self.assertEqual((capacity.rows[0].page, [c.page for c in capacity.rows[0].also_from]), (13, [25]))
        revenue = SectionTable.model_validate({"title": "收入结构", "columns": ["收入"], "rows": [{"label": "a", "cells": ["1"], "sourceId": DOC_ID, "page": 13}]})
        located = {(DOC_ID, 13)}
        self.assertFalse(operating_table_present([revenue], located))
        self.assertTrue(operating_table_present([revenue, capacity], located))

    def test_ready_variants_go_to_writing(self):
        from app.services.agent_runner import wants_to_write

        self.assertTrue(wants_to_write('{"ready":true}'))
        self.assertTrue(wants_to_write('核心证据已齐。JSON：{"ready":true}'))
        self.assertTrue(wants_to_write('{"status":"done","ready":true,"note":"x"}'))
        self.assertFalse(wants_to_write(json.dumps(report())))
        self.assertFalse(wants_to_write("还需要补查"))

    def test_table_shape_is_validated(self):
        from app.schemas.agent import SectionTable

        row = {"label": "a", "cells": ["1", "2"], "sourceId": DOC_ID, "page": 1}
        SectionTable.model_validate({"title": "t", "columns": ["x", "y"], "rows": [row], "chart": "bar", "chartColumns": [1]})
        for bad in ({"columns": ["x"]}, {"chartColumns": [5]}, {"chart": "line", "chartColumns": []}):
            with self.assertRaises(ValueError):
                SectionTable.model_validate({"title": "t", "columns": ["x", "y"], "rows": [row], "chart": "bar", "chartColumns": [0], **bad})

    def test_parent_company_statements_are_excluded_across_pages(self):
        # 真实验收：母公司报表跨页，第94页上半部分母公司“负债合计”被当成合并总负债，与合并值相撞判为冲突、负债缺失。
        from app.services.runner_evidence import consolidated_text

        pages = [
            {"page": 1, "text": "1、合并资产负债表 单位：元 负债合计 13,667,772,290.16"},
            {"page": 2, "text": "合并报表续 所有者权益合计 2、母公司资产负债表 负债合计 1,000"},
            {"page": 3, "text": "（母公司续）负债合计 3,828,613,280.38 3、合并利润表 营业总收入 100"},
            {"page": 4, "text": "8、母公司所有者权益变动表 ……"},
            {"page": 5, "text": "三、公司基本情况 公司注册地"},
        ]
        self.assertIn("13,667,772,290.16", consolidated_text(pages, 1))
        self.assertNotIn("1,000", consolidated_text(pages, 2))
        page3 = consolidated_text(pages, 3)
        self.assertNotIn("3,828,613,280.38", page3)  # 页首延续母公司口径
        self.assertIn("营业总收入", page3)  # 页内遇到合并报表标题后恢复
        self.assertEqual(consolidated_text(pages, 4), "")
        self.assertIn("公司注册地", consolidated_text(pages, 5))

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
        charts = {"charts": [{"id": "annual-revenue", "keys": ["revenue"]}, {"id": "annual-margin", "keys": ["grossMargin"]}], "gaps": []}
        with patch.object(runner, "financial_data", return_value=charts), patch.object(
            runner, "business_data", return_value={"datasets": [{"id": "product-annual", "dimension": "product", "rows": [{"items": [{"share": 60.0}, {"share": 40.0}]}]}]}
        ):
            content = runner.validate_content({"content": json.dumps(report(sections))})
        self.assertEqual([s.chart_ids for s in content.sections], [["annual-revenue", "annual-margin"], [], []])
        self.assertEqual([s.business_ids for s in content.sections], [[], ["product-annual"], []])
        removed = [e for e in job.events if e["type"] == "figure_duplicates_removed"]
        self.assertEqual(removed[0]["removed"], ["annual-revenue", "product-annual"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
