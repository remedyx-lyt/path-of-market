"""结构化财务报表（AKShare）：字段映射、截止日过滤、直接作财务底稿主来源，以及引用不强制到页。全部离线，不联网。"""

import unittest

from support import DOC_ID, FakeModel, RunnerFixture

from app.schemas.agent import Citation
from app.services.financial_data import build_financial_data
from app.tools.contracts import ToolError
from app.tools.financial_db import FinancialStatementProvider

COMPANY = {"code": "300033", "name": "同花顺", "exchange": "SZSE"}


def fake_rows(kind, symbol):
    """模拟 AKShare 三张表的行：2025 年报（2026-03 披露）、2024 年报，以及截止日之后才披露的 2026 三季报。"""
    rows = {
        "profit": [
            {"REPORT_DATE": "2026-09-30 00:00:00", "NOTICE_DATE": "2026-10-26 00:00:00", "CURRENCY": "CNY", "OPERATE_INCOME": 3.0e9},
            {"REPORT_DATE": "2025-12-31 00:00:00", "NOTICE_DATE": "2026-03-28 00:00:00", "CURRENCY": "CNY",
             "OPERATE_INCOME": 4.0e9, "PARENT_NETPROFIT": 1.2e9, "RESEARCH_EXPENSE": None},
            {"REPORT_DATE": "2024-12-31 00:00:00", "NOTICE_DATE": "2025-03-28 00:00:00", "CURRENCY": "CNY",
             "OPERATE_INCOME": 3.2e9, "PARENT_NETPROFIT": 1.0e9},
        ],
        "balance": [{"REPORT_DATE": "2025-12-31 00:00:00", "NOTICE_DATE": "2026-03-28 00:00:00", "CURRENCY": "CNY",
                     "TOTAL_ASSETS": 1.0e10, "TOTAL_LIABILITIES": 4.0e9}],
        "cashflow": [{"REPORT_DATE": "2025-12-31 00:00:00", "NOTICE_DATE": "2026-03-28 00:00:00", "CURRENCY": "CNY",
                      "NETCASH_OPERATE": 1.5e9}],
    }
    return rows[kind]


class Provider(unittest.TestCase):
    def test_maps_fields_and_filters_by_notice_date(self):
        data = FinancialStatementProvider(fetch=fake_rows).statements(COMPANY, 2023, 2026, "2026-10-23")
        values = {(p["metric"], p["year"], p["period"]): p["value"] for p in data["points"]}
        self.assertEqual(values[("revenue", 2025, "annual")], 4.0e9)
        self.assertEqual(values[("totalLiabilities", 2025, "annual")], 4.0e9)
        self.assertEqual(values[("operatingCashFlow", 2025, "annual")], 1.5e9)
        self.assertNotIn(("revenue", 2026, "q3"), values)  # 截止日之后才披露，不能用
        self.assertNotIn(("rdExpense", 2025, "annual"), values)  # 空值不当 0
        self.assertEqual(data["excludedAfterCutoff"], 1)
        self.assertEqual(data["symbol"], "SZ300033")

    def test_failures_and_unsupported_market_are_tool_errors(self):
        def broken(kind, symbol):
            raise RuntimeError("network")

        with self.assertRaises(ToolError) as caught:
            FinancialStatementProvider(fetch=broken).statements(COMPANY, 2024, 2025, "2026-10-23")
        self.assertEqual(caught.exception.code, "FINANCIAL_DB_UNAVAILABLE")
        with self.assertRaises(ToolError):
            FinancialStatementProvider(fetch=fake_rows).statements({**COMPANY, "exchange": "BSE"}, 2024, 2025, "2026-10-23")


class Merge(unittest.TestCase):
    def test_database_value_is_used_directly_without_cross_check(self):
        database = {"metric": "revenue", "year": 2025, "period": "annual", "value": 4.0e9, "sourceId": "akshare-300033", "page": None,
                    "publishedAt": "2026-03-28", "rawValue": "4000000000.00", "unit": "元", "verification": "akshare_structured",
                    "verificationOrigin": "financial_database"}
        report = {**database, "value": 3.9e9, "sourceId": DOC_ID, "page": 8, "rawValue": "39.00", "unit": "亿元", "quote": "营业收入 39.00",
                  "verification": "text_quote_and_number_match", "verificationOrigin": "automatic_financial_summary"}
        stale = ["2025年度营业收入未与本页文字数字匹配，未画图。", "2025年度研发投入未与本页文字数字匹配，未画图。"]
        data = build_financial_data([report, database], stale)
        self.assertEqual(data["gaps"], stale[1:])  # 结构化报表已覆盖的指标不再报年报取数失败
        row = data["datasets"][0]["rows"][0]
        self.assertEqual(row["values"]["revenue"], 4.0e9)
        self.assertEqual(row["evidence"]["revenue"]["sourceId"], "akshare-300033")
        self.assertFalse(any("不一致" in g or "冲突" in g for g in data["gaps"]))


class FakeStatements:
    def __init__(self):
        self.calls = 0

    def statements(self, company, start, end, as_of):
        self.calls += 1
        return FinancialStatementProvider(fetch=fake_rows).statements(company, start, end, as_of)


class Runner(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_database_feeds_financial_data_once(self):
        self.tools.statement_provider = FakeStatements()
        job, runner = self.runner(FakeModel(), includeFinancials=True)
        await runner.database_financials()
        await runner.database_financials()
        self.assertEqual(self.tools.statement_provider.calls, 1)
        source = runner.sources["akshare-300033"]
        self.assertEqual(source["kind"], "database")
        self.assertTrue(runner.check_citation(Citation(sourceId="akshare-300033", page=None)))
        annual = next(d for d in runner.financial_data()["datasets"] if d["id"] == "annual")
        self.assertEqual(annual["rows"][-1]["values"]["revenue"], 4.0e9)
        self.assertIsNone(annual["rows"][-1]["evidence"]["revenue"]["page"])
        self.assertIn("4000000000.00", runner.page_text("akshare-300033", None))  # 数据表引用它时可按数值核对

    async def test_database_failure_is_a_gap_not_a_stop(self):
        class Broken:
            def statements(self, *args):
                raise ToolError("FINANCIAL_DB_UNAVAILABLE", "AKShare 财务报表暂时取不到：profit")

        self.tools.statement_provider = Broken()
        _, runner = self.runner(FakeModel(), includeFinancials=True)
        await runner.database_financials()
        self.assertEqual(runner.database_info["status"], "failed")
        self.assertTrue(any("改由年报原文取数" in g for g in runner.financial_gaps))
        self.assertNotIn("akshare-300033", runner.sources)

    async def test_document_citation_without_page_after_full_reading(self):
        job, runner = self.runner()
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertTrue(runner.check_citation(Citation(sourceId=DOC_ID, page=None)))
        self.assertEqual(runner.loosen_page(DOC_ID, 99), (None, True))
        self.assertEqual(runner.loosen_page(DOC_ID, 2), (2, False))
        self.assertFalse(runner.check_citation(Citation(sourceId="cninfo-9999999999", page=None)))


if __name__ == "__main__":
    unittest.main()
