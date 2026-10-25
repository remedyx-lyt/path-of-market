import unittest
from tests.support import RunnerFixture, FakeModel, DOC_ID, fixtures
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

    def test_official_unusual_annual_title_is_supported_without_summary(self):
        from datetime import date
        company = self.tools.provider.resolve_company('同花顺')
        item = fixtures.announcement(title='某公司2024年年报报告')
        document = self.tools.provider._document(item, company, [2024], date(2026,10,25))
        self.assertEqual(document['reportType'], 'annual')
        self.assertIsNone(self.tools.provider._document({**item, 'announcementTitle': '2024年年报报告摘要'}, company, [2024], date(2026,10,25)))

    async def test_resume_refreshes_missing_years_without_discarding_reading(self):
        _, runner = self.runner(question='研究公司')
        await runner.find_documents({'company': '同花顺', 'years': [2024], 'asOfDate': '2026-10-23'})
        runner.notes['kept'] = [{'summary': 'already read'}]
        await runner.refresh_missing_history()
        self.assertEqual(runner.notes['kept'], [{'summary': 'already read'}])
        self.assertTrue(runner.history_checked)
        self.assertIn('annual_history_rechecked', runner.messages[-1]['content'])

    def test_large_official_pdf_has_consistent_bounded_download_limit(self):
        from app.tools.cninfo import MAX_PDF_BYTES, CninfoProvider
        class Transport:
            def get_bytes(self, url, *, maximum):
                self.maximum = maximum
                return b'%PDF-test'
        transport = Transport()
        self.assertEqual(CninfoProvider(transport).download('https://static.cninfo.com.cn/a.PDF'), b'%PDF-test')
        self.assertEqual(transport.maximum, MAX_PDF_BYTES)
        self.assertTrue(79_925_886 < MAX_PDF_BYTES <= 100_000_000)


if __name__ == "__main__":
    unittest.main()
