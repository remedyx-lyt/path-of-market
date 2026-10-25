"""财务底稿、同比和受控图表；不让 LLM 提供最终计算值或可执行图形代码。"""

from decimal import Decimal, InvalidOperation
import re

LABELS = {
    "revenue": "营业收入",
    "netProfit": "归母净利润",
    "recurringProfit": "扣非归母净利润",
    "operatingCashFlow": "经营现金流净额",
    "totalAssets": "总资产",
    "netAssets": "归母净资产",
    "rdExpense": "研发费用",
    "operatingCost": "营业成本",
    "totalLiabilities": "总负债",
    "cash": "货币资金",
    "receivables": "应收账款",
    "inventory": "存货",
    "rdInvestment": "研发投入",
}
PERIODS = {"annual": "年度", "h1": "上半年", "q1": "一季度", "q3": "前三季度"}
FLOW = {"revenue", "netProfit", "recurringProfit", "operatingCashFlow", "rdExpense", "operatingCost", "rdInvestment"}
SCALE = {"元": Decimal(1), "万元": Decimal(10000), "亿元": Decimal(100000000)}
ROW_LABELS = {
    "revenue": "营业收入",
    "netProfit": "归属于上市公司股东的净利润",
    "recurringProfit": "归属于上市公司股东的扣除非经常性损益的净利润",
    "operatingCashFlow": "经营活动产生的现金流量净额",
    "totalAssets": "(?:总资产|资产总额|资产总计)",
    "netAssets": "归属于上市公司股东的净资产",
    "rdExpense": "研发费用",
    "operatingCost": "营业成本",
    "totalLiabilities": "(?:负债合计|负债总额)",
    "cash": "货币资金",
    "receivables": "应收账款",
    "inventory": "存货",
    "rdInvestment": "研发投入(?:金额|合计)?",
}


def locate_summary_pages(pages):
    for entry in pages[:40]:
        text = re.sub(r"\s+", "", entry["text"])
        if "主要会计数据" in text and sum(label in text for label in ["营业收入", "净利润", "现金流"]) >= 3:
            return [entry["page"]]
    return []


def verified_points(result, document, pages, unit_context=None):
    """数字需在同一物理页原文出现；列序与期间由视觉核对，仍需保留模型取数局限。"""
    accepted, gaps = [], []
    for point in result.financial_points:
        if point.page not in pages or point.year > document["fiscalYear"]:
            gaps.append("取数页码或年度无效，已排除。")
            continue
        if point.metric in FLOW:
            expected = {"annual": "annual", "interim": "h1", "q1": "q1", "q3": "q3"}.get(document.get("reportType", "annual"))
            if point.period != expected:
                gaps.append("流量指标期间与原报告不一致，已排除。")
                continue
        try:
            raw = Decimal(point.raw_value.replace(",", ""))
            tokens = re.findall(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", pages[point.page])
            matched = any(Decimal(t.replace(",", "")) == raw for t in tokens)
            compact = re.sub(r"\s+", "", pages[point.page])
            if not re.search(ROW_LABELS[point.metric], compact):
                raise ValueError
            row_unit = re.search(ROW_LABELS[point.metric] + r"[（(](亿元|万元|元)[）)]", compact)
            global_unit = re.search(r"单位[:：](?:人民币)?(亿元|万元|元)", compact)
            declared = row_unit or global_unit
            context = (unit_context or {}).get(point.page)
            declared_unit = declared[1] if declared else context["unit"] if context else None
            value = raw * SCALE[point.unit]
            quote = re.sub(r"\s+", "", point.quote)
            adjacent_unit = (
                re.search(re.escape(point.raw_value.replace(",", "")) + r"(亿元|万元|元)", quote.replace(",", "")) if quote else None
            )
            if adjacent_unit:
                declared_unit = adjacent_unit[1]
            if quote and (
                quote not in compact
                or not re.search(ROW_LABELS[point.metric], quote)
                or not any(Decimal(t.replace(",", "")) == raw for t in re.findall(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", point.quote))
            ):
                raise ValueError
            if not value.is_finite() or abs(value) > Decimal("1e17") or not matched or declared_unit != point.unit:
                raise ValueError
        except (ValueError, InvalidOperation):
            gaps.append(f"{point.year}{PERIODS[point.period]}{LABELS[point.metric]}未与本页文字数字匹配，未画图。")
            continue
        accepted.append(
            {
                "metric": point.metric,
                "year": point.year,
                "period": point.period,
                "value": float(value),
                "sourceId": document["documentId"],
                "page": point.page,
                "publishedAt": document["publishedAt"],
                "rawValue": point.raw_value,
                "unit": point.unit,
                "quote": point.quote,
                "unitEvidence": context,
                "verification": "text_quote_and_number_match" if point.quote else "vision_and_text_number_match",
            }
        )
    return accepted, gaps


def precision(point):
    """原值的最小刻度（元）：如 1,234.56 万元 → 100 元。用于判断不同来源的数是否只差在四舍五入。"""
    raw = point["rawValue"].replace(",", "")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return SCALE[point["unit"]] / Decimal(10) ** decimals


def yoy(current, previous):
    if previous is None:
        return {"value": None, "reason": "缺少上年同期间数据"}
    if previous == 0:
        return {"value": None, "reason": "上年同期基数为零"}
    if previous < 0:
        return {"value": None, "reason": "上年同期为负，改看扭亏或亏损绝对变化"}
    return {"value": round(float((Decimal(str(current)) / Decimal(str(previous)) - 1) * 100), 4), "reason": ""}


def build_financial_data(points, gaps=(), *, history_years=3):
    groups, issues = {}, list(gaps)
    for point in points:
        key = (point["period"], point["year"], point["metric"])
        groups.setdefault(key, []).append(point)
    values = {}
    for key, candidates in groups.items():
        database = [p for p in candidates if p.get("verificationOrigin") == "financial_database"]
        primary = [p for p in candidates if p.get("verificationOrigin") == "automatic_financial_summary"]
        if database:
            # 结构化报表（合并口径、元为单位）有这一项就直接用，不再与年报原文取数比对（用户 2026-10-26 决定）。
            candidates = database
        elif primary:
            candidates = primary
        elif any(p.get("quote") for p in candidates):
            candidates = [p for p in candidates if p.get("quote")]
        if len({p["value"] for p in candidates}) > 1:
            finest = min(candidates, key=precision)
            if all(
                p["value"] == finest["value"]
                or precision(p) > precision(finest)
                and abs(Decimal(str(p["value"])) - Decimal(str(finest["value"]))) <= (precision(p) + precision(finest)) / 2
                for p in candidates
            ):
                candidates = [p for p in candidates if precision(p) == precision(finest)]
            else:
                issues.append(f"{key[1]}{PERIODS[key[0]]}{LABELS[key[2]]}存在不同来源数值冲突，未自动选值。")
                continue
        values[key] = max(candidates, key=lambda p: p["publishedAt"])
    datasets, charts = [], []
    for kind, label in PERIODS.items():
        years = sorted({y for k, y, _ in values if k == kind})
        if not years:
            continue
        rows = []
        for year in years[-history_years:]:
            cells = {metric: p for (k, y, metric), p in values.items() if k == kind and y == year}
            amounts = {metric: p["value"] for metric, p in cells.items()}
            growth = {
                metric: yoy(p["value"], values.get((kind, year - 1, metric), {}).get("value"))
                for metric, p in cells.items()
                if metric in FLOW
            }
            if amounts.get("revenue", 0) > 0 and "netProfit" in amounts:
                amounts["attributableMargin"] = round(amounts["netProfit"] / amounts["revenue"] * 100, 4)
            if amounts.get("revenue", 0) > 0:
                if "operatingCost" in amounts:
                    amounts["grossMargin"] = round((1 - amounts["operatingCost"] / amounts["revenue"]) * 100, 4)
                for metric, ratio in [("rdExpense", "rdExpenseRatio"), ("rdInvestment", "rdInvestmentRatio")]:
                    if metric in amounts:
                        amounts[ratio] = round(amounts[metric] / amounts["revenue"] * 100, 4)
            if amounts.get("totalAssets", 0) > 0 and "totalLiabilities" in amounts:
                amounts["liabilityRatio"] = round(amounts["totalLiabilities"] / amounts["totalAssets"] * 100, 4)
            rows.append(
                {
                    "year": year,
                    "periodLabel": f"{year}{label}",
                    "values": amounts,
                    "yoy": growth,
                    "evidence": {
                        metric: {k: p[k] for k in ["sourceId", "page", "rawValue", "unit", "verification"]} for metric, p in cells.items()
                    },
                }
            )
        datasets.append({"id": kind, "label": label, "rows": rows})
        definitions = [
            ("revenue", "营业收入", "bar", ["revenue"], "amount", "performance"),
            ("growth", "营收与归母利润同比", "line", ["revenue", "netProfit"], "yoy", "performance"),
            ("cash-profit", "归母利润与经营现金流", "bar", ["netProfit", "operatingCashFlow"], "amount", "cashflow"),
            ("margin", "利润率变化", "line", ["attributableMargin", "grossMargin"], "ratio", "profitability"),
            ("balance", "资产与负债", "bar", ["totalAssets", "totalLiabilities"], "amount", "balance_sheet"),
            ("working-capital", "货币资金、应收账款与存货", "bar", ["cash", "receivables", "inventory"], "amount", "balance_sheet"),
            ("leverage", "资产负债率", "line", ["liabilityRatio"], "ratio", "balance_sheet"),
            ("rd", "研发费用与研发投入（分别披露口径）", "bar", ["rdExpense", "rdInvestment"], "amount", "research"),
            ("rd-ratio", "研发费用率与研发投入占比", "line", ["rdExpenseRatio", "rdInvestmentRatio"], "ratio", "research"),
        ]
        for slug, title, chart_type, keys, mode, topic in definitions:
            active = [key for key in keys if any(key in (r["yoy"] if mode == "yoy" else r["values"]) for r in rows)]
            if active:
                charts.append(
                    {
                        "id": kind + "-" + slug,
                        "datasetId": kind,
                        "title": label + " · " + title,
                        "type": chart_type,
                        "keys": active,
                        "valueKind": mode,
                        "unit": "亿元" if mode == "amount" else "%",
                        "topic": topic,
                    }
                )
    if not datasets:
        issues.append("尚无可用的财务底稿（结构化报表或年报原文取数），无法生成财务图表。")
    structured = any(p.get("verificationOrigin") == "financial_database" for p in points)
    return {
        "schemaVersion": 1,
        "datasets": datasets,
        "charts": charts,
        "gaps": list(dict.fromkeys(issues)),
        "labels": {
            **LABELS,
            "attributableMargin": "归母净利率",
            "grossMargin": "毛利率",
            "liabilityRatio": "资产负债率",
            "rdExpenseRatio": "研发费用率",
            "rdInvestmentRatio": "研发投入占营收",
        },
        "method": (
            "标准财务数直接取自 AKShare（东方财富数据中心）结构化三大报表，合并口径；报表里没有的研发投入等才用年报原文取数。"
            "金额统一元，图示亿元；同比仅同期间且正基数，不能当独立审计。"
            if structured
            else "先视觉核对原页，再匹配本页文字数字；金额统一元，图示亿元；同比仅同期间且正基数，不能把此校验当独立审计。"
        ),
    }
