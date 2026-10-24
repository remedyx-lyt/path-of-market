"""可核查的财务取数与 PDF 视觉观察；绘图规格由程序生成。"""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from app.tools.contracts import DocumentArguments

Metric = Literal['revenue', 'netProfit', 'recurringProfit', 'operatingCashFlow', 'totalAssets', 'netAssets', 'rdExpense']
PeriodKind = Literal['annual', 'h1', 'q1', 'q3']


class InspectArguments(DocumentArguments):
    pages: list[Annotated[int, Field(strict=True, ge=1)]] = Field(min_length=1, max_length=3, description='PDF物理页码，单次最多3页。')
    focus: str = Field(default='检查表格列序、单位、年份和图表含义。', min_length=1, max_length=500)


class RawFinancialPoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric: Metric
    year: int = Field(ge=1990, le=2100)
    period: PeriodKind
    raw_value: str = Field(alias='rawValue', pattern=r'^-?\d[\d,]*(?:\.\d+)?$', max_length=40)
    unit: Literal['元', '万元', '亿元']
    page: int = Field(ge=1, strict=True)


class VisualObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page: int = Field(ge=1, strict=True)
    summary: str = Field(min_length=1, max_length=1800)
    uncertainties: list[str] = Field(default_factory=list, max_length=8)


class VisualResult(BaseModel):
    # 部分供应商附加顶层type等标签，只读取声明的数据；每个观察/取数条目仍严格校验。
    model_config = ConfigDict(extra='ignore')
    observations: list[VisualObservation] = Field(min_length=1, max_length=3)
    financial_points: list[RawFinancialPoint] = Field(default_factory=list, alias='financialPoints', max_length=45)
