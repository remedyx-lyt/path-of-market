"""M1-4 预兆策略与 Agent 行为验收（离线、脚本化模型）。

对应 task-board 最低验收案例：
1. 不同问题/预兆 → 不同的方法、研究计划与工具提示（真实模型的实际工具选择差异由 scripts/check-omens-live.py 验收）
2. 资料冲突 → 底稿明确列出冲突并要求补查，未解决的冲突进入报告局限
3. 缺少证据 → 能力缺口与未覆盖项明确写出，不宣称覆盖
4. 达到步数限制 → 停止并保留部分结果，预兆标记为未完成
"""

import json
import unittest

from support import DOC_ID, FakeModel, RunnerFixture, report, section

OPPORTUNITY_TEXT = "已发生事实与尚未验证的假设分开；保守、中性、乐观三种情景；跟踪指标包括订单与产能。"
ABYSS_TEXT = "先写乐观叙事，再拆三个关键假设；最坏情景下现金流先恶化；监控应收账款与存货。"


def omen_report(*, opportunity=OPPORTUNITY_TEXT, coverage=True):
    sections = [
        section("经营证据", "原文记录需结合单位与年度解释。"),
        section("机会验证", opportunity, omens=["opportunity"]),
        section("反方检查", ABYSS_TEXT, omens=["abyssal_echoes"]),
        section("行情口径", "实际价格与复权序列不同。", market=True),
    ]
    self_report = (
        [
            {"omen": "opportunity", "addressed": ["区分事实与假设"], "missingItems": ["无新闻/政策工具，催化因素只依据公司披露"]},
            {"omen": "abyssal_echoes", "addressed": ["拆解关键假设"], "missingItems": []},
        ]
        if coverage
        else []
    )
    return report(sections, self_report)


def spec_message(runner):
    return next((json.loads(m["content"]) for m in runner.messages if '"omen_research_specs"' in m.get("content", "")), None)


class OmenStrategy(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_case1_omens_change_methods_plan_and_tool_hints(self):
        _, plain = self.runner()
        _, ancient = self.runner(omens=["ancient"])
        _, abyss = self.runner(omens=["abyssal_echoes"])
        self.assertIsNone(spec_message(plain))
        ancient_hints = " ".join(spec_message(ancient)["omens"][0]["toolHints"])
        abyss_hints = " ".join(spec_message(abyss)["omens"][0]["toolHints"])
        self.assertIn("get_market_data", ancient_hints)  # 远古：更长历史区间
        self.assertIn("search", abyss_hints)  # 深渊回响：回查风险/应收/商誉
        self.assertNotEqual(ancient_hints, abyss_hints)
        model = FakeModel()
        _, runner = self.runner(model, omens=["abyssal_echoes"])
        await runner.prepare_methods()
        refs = [r["reference"] for r in runner.method_usage["references"]]
        self.assertTrue(any("valuation-methodologies" in r for r in refs))
        self.assertGreaterEqual(sum(c.get("omen") == "abyssal_echoes" for c in runner.method_usage["plan"]["checks"]), 2)

    async def test_completed_run_reports_coverage_per_omen(self):
        model = FakeModel(final=omen_report())
        job, runner = self.runner(model, omens=["opportunity", "abyssal_echoes"])
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        coverage = {c["omen"]: c for c in job.report["omenCoverage"]}
        self.assertTrue(coverage["opportunity"]["covered"])
        self.assertTrue(coverage["abyssal_echoes"]["covered"])
        self.assertEqual(coverage["opportunity"]["sections"], ["机会验证"])
        self.assertIn("催化因素只依据公司披露", " ".join(coverage["opportunity"]["missingItems"]))
        self.assertTrue(coverage["opportunity"]["skillsRead"])
        self.assertGreaterEqual(coverage["abyssal_echoes"]["planChecks"], 2)

    async def test_writing_instruction_lists_selected_omens(self):
        model = FakeModel(final=omen_report(), ready=True)
        job, runner = self.runner(model, omens=["opportunity", "abyssal_echoes"])
        await runner.run()
        compose_messages = next(c[2] for c in model.calls if c[0] == "compose")
        instruction = compose_messages[-1]["content"]
        self.assertIn("opportunity", instruction)
        self.assertIn("三种情景推演", instruction)
        self.assertIn("omenCoverage", instruction)
        self.assertIn("合计不超过 12 节", instruction)  # 真实验收中两个预兆曾让报告写到 14 节而整篇重写

    async def test_report_without_omen_section_is_sent_back(self):
        _, runner = self.runner(omens=["opportunity"])
        runner.source(
            {"documentId": DOC_ID, "title": "t", "sourceUrl": "u", "publishedAt": "2025-03-10", "pageCount": 2, "fiscalYear": 2024}
        )
        runner.coverage[DOC_ID].update(textComplete=True, processedPages=[1, 2])
        runner.market_data = {"limitations": []}
        runner.sources["market-300033"] = {"sourceId": "market-300033", "kind": "market"}
        with self.assertRaises(ValueError) as error:
            runner.validate_content({"content": json.dumps(report())})
        self.assertIn("机遇预兆没有对应章节", str(error.exception))
        runner.validate_content({"content": json.dumps(omen_report())})

    async def test_case2_conflicts_surface_and_stay_in_limitations(self):
        _, runner = self.runner()
        runner.financial_gaps.append("2025年度营业收入存在不同来源数值冲突，未自动选值。")
        state = json.loads(runner.context()[-2]["content"])
        self.assertEqual(state["type"], "current_research_state")
        self.assertTrue(state["conflicts"])
        self.assertIn("补查", state["conflictInstruction"])
        self.assertTrue(any("未解决的来源冲突" in item for item in runner.report(reason="step_budget")["limitations"]))

    async def test_case3_missing_evidence_is_explicit(self):
        weak = OPPORTUNITY_TEXT.replace("保守、中性、乐观三种情景；", "")
        model = FakeModel(final=omen_report(opportunity=weak, coverage=False))
        job, runner = self.runner(model, omens=["opportunity", "abyssal_echoes"])
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        coverage = {c["omen"]: c for c in job.report["omenCoverage"]}
        self.assertFalse(coverage["opportunity"]["covered"])
        missing = " ".join(coverage["opportunity"]["missingItems"])
        self.assertIn("保守/中性/乐观", missing)
        self.assertIn("模型未提交", missing)
        self.assertTrue(coverage["opportunity"]["capabilityGaps"])  # 新闻/政策等工具缺口始终列出

    async def test_case4_step_budget_stops_and_marks_omens_incomplete(self):
        job, runner = self.runner(omens=["exalted"], limits={"max_steps": 1})
        await runner.run()
        self.assertEqual(job.status, "partial")
        self.assertEqual(job.report["run"]["stopReason"], "step_budget")
        coverage = job.report["omenCoverage"][0]
        self.assertFalse(coverage["covered"])
        self.assertIn("研究未完成", coverage["missingItems"][0])

    async def test_no_omen_keeps_empty_coverage(self):
        job, runner = self.runner()
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["omenCoverage"], [])

    async def test_more_omens_get_more_report_budget(self):
        model = FakeModel(final=omen_report(), ready=True)
        await self.runner(model, omens=["opportunity", "abyssal_echoes"])[1].run()
        compose_tokens = next(c[1] for c in model.calls if c[0] == "compose")
        self.assertEqual(compose_tokens, 14000 + 2 * 2500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
