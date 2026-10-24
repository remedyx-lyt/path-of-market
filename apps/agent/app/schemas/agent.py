"""M1-3 异步研究与引用约定；不改变原有 mock/model 接口。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.research import ModelResearchRequest
from app.tools.contracts import DocumentArguments


class AgentResearchRequest(ModelResearchRequest):
    include_financials: bool = Field(default=True, alias="includeFinancials", strict=True,
        description="提取财务底稿并通过原页视觉检查，生成同期间表图；纯专题可关闭。")
    include_market: bool = Field(default=True, alias="includeMarket", strict=True)
    include_current_period: bool = Field(default=True, alias="includeCurrentPeriod", strict=True,
        description="补充研究截止年度最新已披露的季报/半年报；纯历史年度专题可关闭。")


class AgentReadArguments(DocumentArguments):
    mode: Literal["full", "page", "search"] = Field(default="full",
        description="full 完整分批读原文并形成带页码的阅读记录；page/search 仅重点复查，不能代替通读。")
    page: int = Field(default=1, ge=1)
    query: str = Field(default="", max_length=100)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=80)
    page: int | None = Field(default=None, ge=1, strict=True)


class AgentSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    heading: str = Field(min_length=1, max_length=120, strict=True)
    content: str = Field(min_length=1, max_length=10000, strict=True)
    citations: list[Citation] = Field(default_factory=list, max_length=12)
    topics: list[Literal['business', 'performance', 'profitability', 'cashflow', 'balance_sheet', 'research', 'risks']] = Field(default_factory=list, max_length=7)


class AgentContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240, strict=True)
    summary: str = Field(min_length=1, max_length=3000, strict=True)
    sections: list[AgentSection] = Field(min_length=2, max_length=10)


class ReadingFact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1400, strict=True)
    pages: list[int] = Field(min_length=1, max_length=20)


class ReadingNote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=2400, strict=True)
    facts: list[ReadingFact] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=6)
