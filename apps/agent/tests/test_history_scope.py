import unittest
from tests.support import RunnerFixture, FakeModel, DOC_ID
from app.core.research_history import history_scope
from app.schemas.agent import AgentResearchRequest
from app.services.runtime import RunLimits


class HistoryTests(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    def test_default_and_ancient_and_explicit_short(self):
        for omens, question, count, first in [([], "研究公司", 5, 2021), (["ancient"], "研究公司", 10, 2016), (["ancient"], "研究最近两年的经营", 2, 2024)]:
            scope = history_scope(AgentResearchRequest(target="同花顺", question=question, omens=omens, asOfDate="2026-10-23"))
            self.assertEqual((scope["count"], scope["years"][0], scope["years"][-1]), (count, first, 2025))

    async def test_program_expands_primary_query_and_records_missing(self):
        _, runner = self.runner(FakeModel(), question="研究公司")
        calls = []
        original = runner.raw_tool
        async def raw(name, arguments):
            calls.append((name, arguments))
            return await original(name, arguments)
        runner.raw_tool = raw
        result = await runner.find_documents({"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        query = next(args for name, args in calls if name == "find_documents")
        self.assertEqual(query["years"], [2021,2022,2023,2024,2025])
        self.assertTrue(runner.history_checked)
        self.assertEqual(result["annualHistory"]["count"], 5)
        self.assertTrue(runner.required_annual)
        self.assertEqual({d["fiscalYear"] for d in runner.required_annual.values()}, {2024, 2025})
        self.assertTrue(runner.history_gap)

    async def test_ancient_query_ten_years(self):
        _, runner = self.runner(FakeModel(), question="研究公司", omens=["ancient"])
        result = await runner.find_documents({"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        self.assertEqual(result["annualHistory"]["years"], list(range(2016,2026)))

    def test_capacity_scales_but_writing_reserve_stays(self):
        five, ten = RunLimits.for_history(5), RunLimits.for_history(10)
        self.assertGreater(ten.max_model_calls, five.max_model_calls)
        self.assertEqual(ten.report_reserve_calls, five.report_reserve_calls)
        self.assertEqual(ten.read_characters, five.read_characters)

    def test_financial_chart_window_keeps_five_and_ten_years(self):
        from app.services.financial_data import build_financial_data
        points = [{"period": "annual", "year": year, "metric": "revenue", "value": year*10000,
                   "rawValue": str(year*10000), "unit": "元", "publishedAt": f"{year+1}-04-01", "sourceId": f"test-{year}", "page": 1, "verification": "isolated"}
                  for year in range(2015,2026)]
        for count in [5, 10]:
            data = build_financial_data(points, history_years=count)
            self.assertEqual([r["year"] for r in data["datasets"][0]["rows"]], list(range(2026-count,2026)))


if __name__ == "__main__":
    unittest.main()
