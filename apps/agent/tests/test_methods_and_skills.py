"""Skill 使用：不选预兆也按问题选方法；选预兆叠加专属 Skill；计划缓存、失败降级与按需读取记录。"""

import json
import unittest

from support import RunnerFixture, FakeModel, AgentResearchRequest

from app.core.omens import OMENS, select_methods


def request(question, omens=(), financials=True):
    return AgentResearchRequest(target="t", question=question, asOfDate="2026-10-23", omens=list(omens), includeFinancials=financials)


def names(selection):
    return [path.split("/skills/")[1] for path, _ in selection]


class MethodSelection(unittest.TestCase):
    def test_base_methods_always_present_without_omen(self):
        chosen = names(select_methods(request("随便看看这家公司", financials=False)))
        self.assertIn("initiating-coverage/references/task1-company-research.md", chosen)
        self.assertIn("thesis-tracker/SKILL.md", chosen)
        self.assertNotIn("initiating-coverage/references/task4-chart-generation.md", chosen)  # 不做财务图时不读图表方法

    def test_question_intent_selects_different_skills(self):
        competition = names(select_methods(request("竞争格局与护城河")))
        industry = names(select_methods(request("所在行业的周期位置")))
        valuation = names(select_methods(request("现在估值贵不贵")))
        self.assertIn("competitive-analysis/SKILL.md", competition)
        self.assertNotIn("competitive-analysis/SKILL.md", industry)
        self.assertIn("sector-overview/SKILL.md", industry)
        self.assertIn("initiating-coverage/references/valuation-methodologies.md", valuation)

    def test_omen_stacks_its_own_skills_on_top_of_question(self):
        plain = names(select_methods(request("竞争格局")))
        stacked = names(select_methods(request("竞争格局", omens=["opportunity", "abyssal_echoes"])))
        self.assertTrue(set(plain) < set(stacked))
        self.assertIn("catalyst-calendar/SKILL.md", stacked)
        self.assertIn("initiating-coverage/references/valuation-methodologies.md", stacked)

    def test_selection_order_is_canonical_for_prefix_cache(self):
        a = [p for p, _ in select_methods(request("竞争格局", omens=["abyssal_echoes"]))]
        b = [p for p, _ in select_methods(request("风险与竞争", omens=["abyssal_echoes"]))]
        self.assertEqual(a[:4], b[:4])  # 基础方法固定在最前

    def test_every_omen_method_exists_in_pinned_catalog(self):
        from app.core.research_skills import catalog

        available = catalog()
        for omen in OMENS.values():
            for path in omen.methods:
                self.assertIn(path, available, path)


class MethodPlanning(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_plan_runs_even_without_financials_or_omens(self):
        job, runner = self.runner()
        await runner.prepare_methods()
        self.assertEqual(runner.method_usage["status"], "planned")
        self.assertTrue(runner.method_usage["references"])

    async def test_omen_plan_needs_tagged_checks_then_repairs(self):
        def plan(task, attempt):
            reference = task["references"][0]["reference"]
            base = [{"topic": "business", "question": "q", "evidenceNeeded": "e", "figureIdea": "无", "methodReference": reference}] * 3
            if attempt == 1:
                return {"focus": "f", "checks": base, "unavailable": []}  # 缺少预兆专属检查
            tagged = [{**base[0], "omen": "abyssal_echoes"}] * 2
            return {"focus": "f", "checks": base + tagged, "unavailable": []}

        model = FakeModel(plan=plan)
        job, runner = self.runner(model, omens=["abyssal_echoes"])
        await runner.prepare_methods()
        self.assertEqual(model.count("plan"), 2)
        self.assertEqual(sum(c.get("omen") == "abyssal_echoes" for c in runner.method_usage["plan"]["checks"]), 2)

    async def test_plan_is_cached_and_reused_for_identical_task(self):
        first_model = FakeModel()
        _, first = self.runner(first_model, omens=["exalted"])
        await first.prepare_methods()
        second_model = FakeModel()
        _, second = self.runner(second_model, omens=["exalted"])
        await second.prepare_methods()
        self.assertEqual(second_model.count("plan"), 0)
        self.assertTrue(second.method_usage["planCacheReused"])
        self.assertEqual(second.method_usage["originRunId"], first.job.task_id)

    async def test_plan_failure_degrades_instead_of_aborting(self):
        model = FakeModel(plan=lambda task, attempt: {"focus": "f"})
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(runner.method_usage["status"], "plan_failed")
        self.assertTrue(any("方法计划未通过" in item for item in job.report["limitations"]))

    async def test_references_precede_task_in_plan_request(self):
        model = FakeModel()
        _, runner = self.runner(model, omens=["ancient"])
        await runner.prepare_methods()
        body = model.calls[0][2][1]["content"]
        self.assertTrue(body.startswith('{"references"'))
        self.assertLess(body.index('"references"'), body.index('"task"'))

    async def test_catalog_visible_and_on_demand_reads_recorded(self):
        job, runner = self.runner()
        catalog = next(json.loads(m["content"]) for m in runner.messages if '"skill_catalog"' in m.get("content", ""))
        self.assertGreaterEqual(len(catalog["skills"]), 10)
        await runner.prepare_methods()
        target = "plugins/vertical-plugins/equity-research/skills/sector-overview/SKILL.md"
        await runner.dispatch("read_research_skill", {"reference": target})
        self.assertIn(target, runner.method_usage["onDemandReads"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
