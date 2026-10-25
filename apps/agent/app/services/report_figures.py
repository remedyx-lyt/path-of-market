"""业务分部证据、占比与逐章图表安排；原始数值和模型的解释分开。"""

from collections import defaultdict
from decimal import Decimal
import re

from app.services.financial_data import PERIODS, SCALE

DIMENSIONS = {"product": "产品", "geography": "地区", "industry": "行业"}


def compact(text):
    return re.sub(r"\s+", "", text)


def locate_detail_pages(pages):
    """定位正文表格，不依赖公司名或固定页码；不扫描附注中的子公司报表冒充合并数据。"""
    selected = set()
    for entry in pages[:60]:
        text = compact(entry["text"])
        if (
            ("营业收入构成" in text and "分产品" in text)
            or ("研发投入金额" in text and "研发投入占" in text)
            or ("主要财务数据同比" in text and "营业成本" in text)
            or ("研发投入" in text and "上年同期" in text and "营业成本" in text)
        ):
            selected.add(entry["page"])
    # 先找到完整报表区的第一个合并资产负债表，后续三页可能跨页。
    start = next(
        (
            p["page"]
            for i, p in enumerate(pages)
            if "合并资产负债表" in compact(p["text"])
            and "流动资产" in compact(p["text"] + (pages[i + 1]["text"] if i + 1 < len(pages) else ""))
        ),
        None,
    )
    if start:
        selected.update(range(start, min(start + 3, len(pages)) + 1))
    income = next(
        (
            p["page"]
            for i, p in enumerate(pages)
            if "合并利润表" in compact(p["text"])
            and "营业总收入" in compact(p["text"] + (pages[i + 1]["text"] if i + 1 < len(pages) else ""))
        ),
        None,
    )
    if income:
        selected.update(range(income, min(income + 1, len(pages)) + 1))
    return sorted(selected)[:12]


OPERATING_MARKERS = (("产销量情况",), ("生产量", "销售量", "库存量"), ("产能", "产量", "销量"))


def locate_operating_pages(pages):
    """定位产能、产量、销量、库存量表（制造业等经营数量数据），只看正文前段，不扫附注。"""
    found = [p["page"] for p in pages[:80] if any(all(m in compact(p["text"]) for m in group) for group in OPERATING_MARKERS)]
    return found[:6]


NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def number_tokens(text):
    """文中出现的数字（去千分位、去小数末尾的0）。PDF 文字可能在数字内断行，原文与去空白后的文本都取。"""
    tokens = set()
    for raw in NUMBER.findall(text) + NUMBER.findall(compact(text)):
        try:
            tokens.add(format(Decimal(raw.replace(",", "")).normalize(), "f"))
        except ArithmeticError:
            continue
    return tokens


def found_on_page(raw, page_values):
    """表中数字是否出现在原页：原样出现，或原文按“元→万元/亿元”换算后、按表中小数位四舍五入相等（如 38,240,xxx,xxx 元 → 382.40 亿元）。"""
    value = Decimal(raw.replace(",", ""))
    places = Decimal(1).scaleb(min(value.as_tuple().exponent, 0))

    def scaled_equal(p, scale):
        try:
            return (p / scale).quantize(places) == value
        except ArithmeticError:  # PDF 文字里相邻数字粘连成的超长数串，换算超出精度，不可能匹配
            return False

    return value in page_values or any(scaled_equal(p, s) for p in page_values for s in (Decimal(10000), Decimal(100000000)))


def check_table(table, page_text):
    """逐格核对：含数字的格子，其中每个数字都须出现在本行所引原页（允许单位换算）。返回核对统计与未核对上的格子位置。

    计算值（如利用率、占比、同比）在原页找不到属于正常情况，前端标为“未在原页找到”，不当作原文数据。
    """
    checked, unmatched = 0, []
    for r, row in enumerate(table["rows"]):
        if row.get("page") is None and not page_text(row["sourceId"], None):  # 网页可核对完整快照；行情无原文不计入核对
            continue
        cited = [(row["sourceId"], row["page"])] + [(c["sourceId"], c.get("page")) for c in row.get("alsoFrom") or []]
        page_values = {Decimal(t) for sid, page in cited for t in number_tokens(page_text(sid, page))}
        for c, cell in enumerate(row["cells"]):
            numbers = NUMBER.findall(cell)
            if not numbers:
                continue
            checked += 1
            if not all(found_on_page(n, page_values) for n in numbers):
                unmatched.append([r, c])
    return {"checkedCells": checked, "matchedCells": checked - len(unmatched), "unmatched": unmatched}


def dominant_share(dataset):
    """最近一期最大单项（非扣除项）收入占比；单一业务占比很高时，结构图不是必做项。"""
    latest = dataset["rows"][-1]["items"]
    return max((p["share"] for p in latest if not p.get("derived")), default=0)


def verified_segments(result, document, pages):
    accepted, gaps = [], []
    expected = {"annual": "annual", "interim": "h1", "q1": "q1", "q3": "q3"}.get(document.get("reportType", "annual"))
    for point in result.segment_points:
        quote = compact(point.quote)
        text = compact(pages.get(point.page, ""))
        raw = Decimal(point.raw_value.replace(",", ""))
        numbers = re.findall(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", point.quote)
        units = re.findall(r"单位[:：](?:人民币)?(亿元|万元|元)", text)
        if (
            point.page not in pages
            or point.year > document["fiscalYear"]
            or point.period != expected
            or quote not in text
            or compact(point.label) not in quote
            or not any(Decimal(n.replace(",", "")) == raw for n in numbers)
            or point.unit not in units
            or raw * SCALE[point.unit] > Decimal("1e17")
        ):
            gaps.append(f"{point.label}收入未通过原文/金额/单位/期间核对，未进入业务图。")
            continue
        accepted.append(
            {
                "dimension": point.dimension,
                "label": point.label,
                "year": point.year,
                "period": point.period,
                "value": float(raw * SCALE[point.unit]),
                "sourceId": document["documentId"],
                "page": point.page,
                "rawValue": point.raw_value,
                "unit": point.unit,
                "quote": point.quote,
                "publishedAt": document["publishedAt"],
                "verification": "text_quote_and_number_match",
            }
        )
    return accepted, gaps


def build_business_data(points, financial_data, gaps=(), *, history_years=3):
    groups, issues = defaultdict(list), list(gaps)
    for p in points:
        groups[(p["dimension"], p["period"], p["year"], p["label"])].append(p)
    values = {}
    for key, candidates in groups.items():
        if len({p["value"] for p in candidates}) > 1:
            issues.append(f"{key[2]}{PERIODS[key[1]]}{key[3]}收入存在来源冲突，已排除。")
            continue
        values[key] = max(candidates, key=lambda p: p["publishedAt"])
    totals = {(d["id"], r["year"]): r for d in financial_data["datasets"] for r in d["rows"]}
    datasets = []
    for dimension in DIMENSIONS:
        for period in PERIODS:
            years = sorted({y for dim, k, y, _ in values if dim == dimension and k == period})[-history_years:]
            rows = []
            for year in years:
                cells = [p for (dim, k, y, _), p in values.items() if dim == dimension and k == period and y == year]
                row = totals.get((period, year), {})
                total = row.get("values", {}).get("revenue")
                subtotal = sum(p["value"] for p in cells)
                if total is None or total <= 0 or subtotal > total + max(0.01, total * 0.0001):
                    issues.append(f"{year}{PERIODS[period]}{DIMENSIONS[dimension]}收入缺总额或分项超总额，未生成占比图。")
                    continue
                items = [{**p, "share": round(p["value"] / total * 100, 6), "derived": False} for p in cells]
                residual = total - subtotal
                # 少量未披露分项用总额减已知项；不能把已知项重新归一为100%。
                if residual > max(0.01, total * 0.0001):
                    items.append({"label": "其余收入（总额扣除）", "value": residual, "share": residual / total * 100, "derived": True})
                if len(items) < 2:
                    continue
                rows.append(
                    {
                        "year": year,
                        "periodLabel": f"{year}{PERIODS[period]}",
                        "total": total,
                        "totalEvidence": row["evidence"]["revenue"],
                        "items": items,
                    }
                )
            if rows:
                datasets.append(
                    {
                        "id": f"{dimension}-{period}",
                        "dimension": dimension,
                        "period": period,
                        "label": DIMENSIONS[dimension] + "收入",
                        "rows": rows,
                    }
                )
    return {
        "schemaVersion": 1,
        "datasets": datasets,
        "gaps": list(dict.fromkeys(issues)),
        "method": "分产品、地区、行业各自独立；占比＝分项收入÷同期合并营收，缺项用总额扣除并标明，不能跨维度相加。",
    }


def plan_section_figures(sections, financial_data, business_data):
    """按章节主题安排相关图；没有量化数据时使用有引文的定性图，不伪造数值。"""
    plan = []
    available_charts = {c["id"] for c in financial_data["charts"]}
    available_business = {d["id"] for d in business_data["datasets"]}
    for index, section in enumerate(sections):
        chart_ids = [c for c in section.get("chartIds", []) if c in available_charts]
        business_ids = [d for d in section.get("businessIds", []) if d in available_business]
        diagram = section.get("visual")
        plan.append(
            {"sectionIndex": index, "financialChartIds": chart_ids, "businessDatasetIds": business_ids, "diagram": diagram, "gap": None}
        )
    return plan
