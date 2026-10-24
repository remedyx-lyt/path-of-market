"""可核查的财务取数与 PDF 视觉观察；绘图规格由程序生成。"""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from app.tools.contracts import DocumentArguments

Metric = Literal[
    "revenue",
    "netProfit",
    "recurringProfit",
    "operatingCashFlow",
    "totalAssets",
    "netAssets",
    "rdExpense",
    "operatingCost",
    "totalLiabilities",
    "cash",
    "receivables",
    "inventory",
    "rdInvestment",
]
PeriodKind = Literal["annual", "h1", "q1", "q3"]


class InspectArguments(DocumentArguments):
    pages: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=1, max_length=3, description="PDF物理页码，单次最多3页。")
    focus: str = Field(default="检查表格列序、单位、年份和图表含义。", min_length=1, max_length=500)


class RawFinancialPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Metric
    year: int = Field(ge=1990, le=2100)
    period: PeriodKind
    raw_value: str = Field(alias="rawValue", pattern=r"^-?\d[\d,]*(?:\.\d+)?$", max_length=40)
    unit: Literal["元", "万元", "亿元"]
    page: int = Field(ge=1, strict=True)
    quote: str = Field(default="", max_length=1200, description="文字取数时必须给出本页连续原文片段，含指标行与原始数值。")


class ExtractArguments(DocumentArguments):
    pages: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=1, max_length=4)
    focus: str = Field(default="业务收入分部、研发投入、资产负债与营业成本，保留原始金额、期间、单位和原文。", max_length=500)


class RawSegmentPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: Literal["product", "geography", "industry"]
    label: str = Field(min_length=1, max_length=60)
    year: int = Field(ge=1990, le=2100)
    period: PeriodKind
    raw_value: str = Field(alias="rawValue", pattern=r"^\d[\d,]*(?:\.\d+)?$", max_length=40)
    unit: Literal["元", "万元", "亿元"]
    page: int = Field(ge=1, strict=True)
    quote: str = Field(min_length=1, max_length=1200)


class ExtractResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    financial_points: list[RawFinancialPoint] = Field(default_factory=list, alias="financialPoints", max_length=70)
    segment_points: list[RawSegmentPoint] = Field(default_factory=list, alias="segmentPoints", max_length=60)
    gaps: list[str] = Field(default_factory=list, max_length=12)


def parse_extraction(content):
    """严格校验每个条目；坏条目排除并留缺口，不连带丢弃同批有效值。"""
    import json

    body = json.loads(content)
    if not isinstance(body, dict) or any(not isinstance(body.get(key, []), list) for key in ["financialPoints", "segmentPoints", "gaps"]):
        raise ValueError("取数结果顶层结构无效")
    if len(body.get("financialPoints", [])) > 70 or len(body.get("segmentPoints", [])) > 60:
        raise ValueError("取数条目过多，需缩小页面范围")
    values, issues = {}, [s for s in body.get("gaps", []) if isinstance(s, str)][:8]
    invalid = []
    for key, schema in [("financialPoints", RawFinancialPoint), ("segmentPoints", RawSegmentPoint)]:
        values[key] = []
        for index, entry in enumerate(body.get(key, [])):
            try:
                values[key].append(schema.model_validate(entry).model_dump(by_alias=True))
            except ValueError as error:
                fields = ",".join(str(e["loc"][0]) for e in error.errors())
                invalid.append(f"{key}第{index + 1}项的{fields}格式无效，已排除。")
    if invalid and not any(values.values()):
        raise ValueError("所有取数条目无效：" + "；".join(invalid[:3]))
    return ExtractResult.model_validate({**values, "gaps": issues + invalid[: max(0, 12 - len(issues))]})


class VisualObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, strict=True)
    summary: str = Field(min_length=1, max_length=1800)
    uncertainties: list[str] = Field(default_factory=list, max_length=8)


class VisualResult(BaseModel):
    # 部分供应商附加顶层type等标签，只读取声明的数据；每个观察/取数条目仍严格校验。
    model_config = ConfigDict(extra="ignore")
    observations: list[VisualObservation] = Field(min_length=1, max_length=3)
    financial_points: list[RawFinancialPoint] = Field(default_factory=list, alias="financialPoints", max_length=45)
