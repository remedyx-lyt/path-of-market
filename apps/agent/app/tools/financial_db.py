"""结构化财务报表 Provider：AKShare 封装的东方财富数据中心“按报告期”三大报表与主营构成。

程序只做字段映射、截止日过滤与缓存，数值原样进入底稿；模型不提供、不改写数字。
来源：AKShare 文档 stock_profit_sheet_by_report_em / stock_balance_sheet_by_report_em / stock_cash_flow_sheet_by_report_em
与 stock_zygc_em（主营构成：按行业/产品/地区的收入、成本、毛利率，只有年报与中报期）
（akshare.akfamily.xyz，2026-10-26 以 1.19.3 实测字段）。
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import math
import os

from pydantic import Field, model_validator

from app.tools.cninfo import utc_now
from app.tools.contracts import Arguments, ToolError
from app.tools.documents import write_json

# 东方财富字段 → 底稿指标。营业收入用 OPERATE_INCOME（不含利息等其他类金融收入），与年报“营业收入”行一致。
FIELDS = {
    "profit": {
        "OPERATE_INCOME": "revenue",
        "PARENT_NETPROFIT": "netProfit",
        "DEDUCT_PARENT_NETPROFIT": "recurringProfit",
        "OPERATE_COST": "operatingCost",
        "RESEARCH_EXPENSE": "rdExpense",
    },
    "balance": {
        "TOTAL_ASSETS": "totalAssets",
        "TOTAL_LIABILITIES": "totalLiabilities",
        "TOTAL_PARENT_EQUITY": "netAssets",
        "MONETARYFUNDS": "cash",
        "ACCOUNTS_RECE": "receivables",
        "INVENTORY": "inventory",
    },
    "cashflow": {"NETCASH_OPERATE": "operatingCashFlow"},
}
FUNCTIONS = {
    "profit": "stock_profit_sheet_by_report_em",
    "balance": "stock_balance_sheet_by_report_em",
    "cashflow": "stock_cash_flow_sheet_by_report_em",
}
PERIOD_BY_DATE = {"12-31": "annual", "06-30": "h1", "03-31": "q1", "09-30": "q3"}
# 主营构成没有披露日期，按同一报告期利润表的披露日套用研究截止日。
SEGMENT_DIMENSIONS = {"按产品分类": "product", "按地区分类": "geography", "按行业分类": "industry"}
SEGMENT_COLUMNS = ("报告日期", "分类类型", "主营构成", "主营收入", "毛利率")
KEEP = ("REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE", "CURRENCY")


class FinancialStatementArguments(Arguments):
    company: str = Field(min_length=1, max_length=120)
    start_year: int = Field(alias="startYear", ge=2000, le=2100, description="最早会计年度（含）。")
    end_year: int = Field(alias="endYear", ge=2000, le=2100, description="最晚会计年度（含），不晚于截止日所在年度。")
    as_of_date: str = Field(alias="asOfDate", description="研究截止日 YYYY-MM-DD；只取该日及之前披露的报告期。")

    @model_validator(mode="after")
    def check_range(self):
        try:
            cutoff = date.fromisoformat(self.as_of_date)
        except ValueError:
            raise ValueError("需要有效的 YYYY-MM-DD 截止日") from None
        if cutoff.isoformat() != self.as_of_date or cutoff > date.today():
            raise ValueError("需要有效且不晚于今天的截止日")
        if not self.start_year <= self.end_year <= cutoff.year or self.end_year - self.start_year > 11:
            raise ValueError("年度范围无效：起止年度递增、不晚于截止年度、最多12年")
        return self


def akshare_fetch(kind, symbol):
    """调用 AKShare；只保留需要的列。tqdm 进度条关闭，避免写入服务日志。"""
    os.environ.setdefault("TQDM_DISABLE", "1")
    import akshare  # 依赖较重（pandas），按需导入

    frame = getattr(akshare, FUNCTIONS[kind])(symbol=symbol)
    columns = [c for c in (*KEEP, *FIELDS[kind]) if c in frame.columns]
    return [
        {c: (str(v) if c in KEEP else finite_number(v)) if v is not None and v == v else None for c, v in record.items()}
        for record in frame[columns].to_dict("records")
    ]


def akshare_segments(symbol):
    os.environ.setdefault("TQDM_DISABLE", "1")
    import akshare

    frame = akshare.stock_zygc_em(symbol=symbol)
    return [
        {c: (finite_number(v) if c in {"主营收入", "毛利率"} else str(v)) if v is not None and v == v else None for c, v in record.items()}
        for record in frame[[c for c in SEGMENT_COLUMNS if c in frame.columns]].to_dict("records")
    ]


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and abs(number) < 1e17 else None


class FinancialStatementProvider:
    """缓存按“证券 + 取数日期”保存原始行，同一天重复研究不再请求；缓存不提交。"""

    def __init__(self, cache_root=None, fetch=None, fetch_segments=None):
        self.cache_root = cache_root
        self.fetch = fetch or akshare_fetch
        self.fetch_segments = fetch_segments or akshare_segments

    def raw_rows(self, symbol):
        path = self.cache_root / "financial-db" / f"{symbol}-{date.today().isoformat()}-v2.json" if self.cache_root else None
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")), True
            except (OSError, ValueError):
                pass
        failures = {}

        def load(kind):
            try:
                return kind, self.fetch(kind, symbol)
            except Exception:  # 第三方库与网页接口的任何失败都不外泄细节
                failures[kind] = True
                return kind, []

        def segments():
            try:
                return self.fetch_segments(symbol)
            except Exception:  # 主营构成取不到不影响三大报表，记为 None，由调用方说明缺口
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = pool.submit(segments)
            rows = dict(pool.map(load, FIELDS))
            rows["segments"] = pending.result()
        if failures:
            raise ToolError("FINANCIAL_DB_UNAVAILABLE", "AKShare 财务报表暂时取不到：" + "、".join(sorted(failures)), {"failed": sorted(failures)})
        if path and rows["segments"] is not None:  # 主营构成失败时不缓存，下次研究重试
            write_json(path, rows)
        return rows, False

    def statements(self, company: dict, start_year: int, end_year: int, as_of: str) -> dict:
        if company.get("exchange") not in {"SSE", "SZSE"}:
            raise ToolError("FINANCIAL_DB_UNSUPPORTED", "当前只接入沪深A股的结构化财务报表。")
        symbol = ("SH" if company["exchange"] == "SSE" else "SZ") + company["code"]
        rows, cached = self.raw_rows(symbol)
        points, periods, skipped_after = [], {}, 0
        for kind in FIELDS:
            for record in rows[kind]:
                report_date, notice = str(record.get("REPORT_DATE") or "")[:10], str(record.get("NOTICE_DATE") or "")[:10]
                period = PERIOD_BY_DATE.get(report_date[5:])
                if not period or len(notice) != 10 or not report_date[:4].isdigit():
                    continue
                year = int(report_date[:4])
                # 多取前一年，使首年同比有基数；展示年数仍由底稿按任务年限截取。
                if not start_year - 1 <= year <= end_year:
                    continue
                if notice > as_of:
                    skipped_after += 1
                    continue
                if record.get("CURRENCY") not in (None, "CNY"):
                    continue
                for field, metric in FIELDS[kind].items():
                    value = finite_number(record.get(field))
                    if value is None:
                        continue
                    periods[(year, period)] = max(periods.get((year, period), ""), notice)
                    points.append({
                        "metric": metric, "year": year, "period": period, "value": value,
                        "rawValue": format(value, ".2f"), "unit": "元", "field": field,
                        "publishedAt": notice, "updatedAt": str(record.get("UPDATE_DATE") or "")[:10] or None,
                    })
        if not points:
            raise ToolError("FINANCIAL_DB_NO_DATA", "AKShare 未返回截止日前可用的财务报表数据。")
        notices = {(p["year"], p["period"]): p["publishedAt"] for p in points if p["field"] == "OPERATE_INCOME"}
        segment_points = []
        for record in rows.get("segments") or []:
            report_date = str(record.get("报告日期") or "")[:10]
            period, dimension = PERIOD_BY_DATE.get(report_date[5:]), SEGMENT_DIMENSIONS.get(record.get("分类类型"))
            value, label = finite_number(record.get("主营收入")), str(record.get("主营构成") or "").strip()
            if not (period and dimension and label and value is not None and value >= 0 and report_date[:4].isdigit()):
                continue
            if label.startswith("其中"):  # “其中:外购金”是上一项的子项，计入会重复（山东黄金实测行业合计达营收141%）
                continue
            year = int(report_date[:4])
            if (year, period) not in notices:  # 该期利润表在截止日前未披露，或不在年份范围内
                continue
            margin = finite_number(record.get("毛利率"))
            segment_points.append({
                "dimension": dimension, "label": label[:60], "year": year, "period": period, "value": value,
                "rawValue": format(value, ".2f"), "unit": "元", "publishedAt": notices[(year, period)],
                "grossMargin": round(margin * 100, 4) if margin is not None else None,
            })
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code={symbol}"
        return {
            "company": company,
            "provider": "AKShare · 东方财富数据中心",
            "symbol": symbol,
            "sourceUrl": url,
            "retrievedAt": utc_now(),
            "cacheReused": cached,
            "latestNoticeDate": max(periods.values()),
            "periods": [{"year": y, "period": p, "noticeDate": n} for (y, p), n in sorted(periods.items())],
            "points": points,
            "segmentPoints": segment_points,
            "segmentsAvailable": rows.get("segments") is not None,
            "excludedAfterCutoff": skipped_after,
            "limitations": [
                "结构化数据来自 AKShare 封装的东方财富数据中心，为统一口径的合并报表数；可能采用后续更正或重述后的数值，与当时原始披露偶有差异。",
                "只按披露日期过滤到研究截止日；主营构成（分产品/地区/行业收入与毛利率）只有年报与中报期，套用同期利润表披露日；产能、产销量、客户集中度等仍以年报原文为准。",
            ],
        }
