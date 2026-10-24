"""M1-3 异步研究与引用约定；不改变原有 mock/model 接口。"""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.research import ModelResearchRequest
from app.tools.contracts import DocumentArguments


class AgentResearchRequest(ModelResearchRequest):
    include_financials: bool = Field(
        default=True, alias="includeFinancials", strict=True, description="提取财务底稿并通过原页视觉检查，生成同期间表图；纯专题可关闭。"
    )
    include_market: bool = Field(default=True, alias="includeMarket", strict=True)
    include_current_period: bool = Field(
        default=True,
        alias="includeCurrentPeriod",
        strict=True,
        description="补充研究截止年度最新已披露的季报/半年报；纯历史年度专题可关闭。",
    )


class AgentReadArguments(DocumentArguments):
    mode: Literal["full", "page", "search"] = Field(
        default="full", description="full 完整分批读原文并形成带页码的阅读记录；page/search 仅重点复查，不能代替通读。"
    )
    page: int = Field(default=1, ge=1)
    pages: list[int] = Field(
        default_factory=list, max_length=5, description="mode=page 时可一次回查 1 至 5 页，减少来回轮次；提供后忽略 page。"
    )
    query: str = Field(default="", max_length=100)


OmenId = Literal["exalted", "ancient", "opportunity", "abyssal_echoes"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=80)
    page: int | None = Field(default=None, ge=1, strict=True)


class DiagramNode(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=40)
    detail: str = Field(min_length=1, max_length=220)
    citations: list[Citation] = Field(min_length=1, max_length=3)


class SectionDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["flow", "cards"]
    title: str = Field(min_length=1, max_length=100)
    nodes: list[DiagramNode] = Field(min_length=2, max_length=6)


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=60)
    cells: list[Annotated[str, Field(max_length=120)]] = Field(min_length=1, max_length=10)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=80, description="本行数字所在资料")
    page: int | None = Field(default=None, ge=1, strict=True, description="本行数字所在 PDF 物理页（行情数据为 null）；程序核对数字确实出现在该页")
    also_from: list[Citation] = Field(default_factory=list, alias="alsoFrom", max_length=4, description="一行跨多期、数字来自不同报告时补充的来源页")
    note: str = Field(default="", max_length=200, description="本行口径或计算说明（如“计算值：产量÷产能”）")


class SectionTable(BaseModel):
    """模型根据已读原文自行决定的数据表（可选画成图）。程序逐格核对数字是否出现在所引原页，核对不上的格子标出。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)
    unit: str = Field(default="", max_length=30)
    label_header: str = Field(default="", alias="labelHeader", max_length=30, description="行名那一列的表头，如“期间”")
    columns: list[Annotated[str, Field(min_length=1, max_length=30)]] = Field(min_length=1, max_length=10)
    rows: list[TableRow] = Field(min_length=1, max_length=30)
    chart: Literal["none", "bar", "line"] = "none"
    chart_columns: list[int] = Field(default_factory=list, alias="chartColumns", max_length=4, description="画图的列（从0起）")
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def check_shape(self):
        if any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("每行 cells 数量须与 columns 一致")
        if any(not 0 <= i < len(self.columns) for i in self.chart_columns) or (self.chart != "none" and not self.chart_columns):
            raise ValueError("chartColumns 须是 columns 的有效序号；画图时至少选一列")
        return self


class AgentSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    heading: str = Field(min_length=1, max_length=120, strict=True)
    content: str = Field(min_length=1, max_length=10000, strict=True)
    citations: list[Citation] = Field(default_factory=list, max_length=12)
    topics: list[Literal["business", "performance", "profitability", "cashflow", "balance_sheet", "research", "risks"]] = Field(
        default_factory=list, max_length=7
    )
    visual: SectionDiagram | None = None
    chart_ids: list[str] = Field(default_factory=list, alias="chartIds", max_length=8)
    business_ids: list[str] = Field(default_factory=list, alias="businessIds", max_length=6)
    tables: list[SectionTable] = Field(default_factory=list, max_length=3)
    omens: list[OmenId] = Field(default_factory=list, max_length=4, description="本章服务的预兆；每个所选预兆至少有一个明确章节。")


class OmenSelfReport(BaseModel):
    """模型对每个所选预兆的覆盖自评；程序另行核对章节标记、关键要素与能力缺口。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    omen: OmenId
    addressed: list[str] = Field(default_factory=list, max_length=12)
    missing_items: list[str] = Field(default_factory=list, alias="missingItems", max_length=12)


class AgentContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240, strict=True)
    summary: str = Field(min_length=1, max_length=3000, strict=True)
    sections: list[AgentSection] = Field(min_length=2, max_length=12)
    omen_coverage: list[OmenSelfReport] = Field(default_factory=list, alias="omenCoverage", max_length=4)


class ReadingFact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1400, strict=True)
    pages: list[int] = Field(min_length=1, max_length=20)


class ReadingNote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2400, strict=True)
    facts: list[ReadingFact] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=6)


class MethodCheck(BaseModel):
    """研究方法计划中的一项检查；methodReference 必须是本次实际提供给模型的参考文件。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=80, strict=True)
    question: str = Field(min_length=1, max_length=600, strict=True)
    evidence_needed: str = Field(alias="evidenceNeeded", min_length=1, max_length=600, strict=True)
    figure_idea: str = Field(alias="figureIdea", max_length=400, strict=True)
    method_reference: str = Field(alias="methodReference", min_length=1, max_length=300, strict=True)
    omen: str | None = Field(default=None, max_length=40, description="这项检查服务的预兆 ID；基础检查为空。")


class MethodPlan(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)
    focus: str = Field(min_length=1, max_length=1200, strict=True)
    checks: list[MethodCheck] = Field(min_length=3, max_length=16)
    unavailable: list[str] = Field(default_factory=list, max_length=16)
