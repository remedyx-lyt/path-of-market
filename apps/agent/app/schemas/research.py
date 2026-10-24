"""研究接口的数据约定；对外 JSON 使用 userStyle、isMock、toolCalls。"""

from enum import Enum
from datetime import date
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportOmen(str, Enum):
    EXALTED = "exalted"
    ANCIENT = "ancient"
    OPPORTUNITY = "opportunity"
    ABYSSAL_ECHOES = "abyssal_echoes"


class ResearchRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "target": "示例公司",
                    "question": "如何研究它的研发投入变化？",
                    "userStyle": "关注长期增长和风险验证",
                    "omens": ["opportunity", "abyssal_echoes"],
                }
            ]
        },
    )

    target: str = Field(min_length=1, max_length=120, strict=True, description="公司或板块名称")
    question: str = Field(min_length=1, max_length=2000, strict=True, description="本次研究问题")
    user_style: str = Field(
        default="",
        alias="userStyle",
        max_length=500,
        strict=True,
        description="可选研究偏好",
    )
    omens: list[ReportOmen] = Field(
        default_factory=list,
        max_length=4,
        strict=True,
        description="可选研究预兆，本阶段只接收与展示",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["agent"] = "agent"
    mode: Literal["mock"] = "mock"


class ReportSection(BaseModel):
    heading: str
    content: str


class MockResearchReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["mock"] = "mock"
    is_mock: Literal[True] = Field(default=True, alias="isMock")
    target: str
    question: str
    user_style: str = Field(alias="userStyle")
    omens: list[ReportOmen]
    title: str
    summary: str
    sections: list[ReportSection]
    sources: list[str] = Field(default_factory=list, max_length=0)
    tool_calls: list[dict[str, str]] = Field(default_factory=list, max_length=0, alias="toolCalls")


class ModelResearchRequest(ResearchRequest):
    as_of_date: date = Field(alias="asOfDate", description="研究截止日期；不代表模型掌握该日期的数据")

    @field_validator("as_of_date", mode="before")
    @classmethod
    def valid_date(cls, value):
        if type(value) is date:
            return value
        if type(value) is not str or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("研究截止日期应为 YYYY-MM-DD")
        return date.fromisoformat(value)


class ModelSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    heading: str = Field(min_length=1, max_length=120, strict=True)
    content: str = Field(min_length=1, max_length=12000, strict=True)


class ModelContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240, strict=True)
    summary: str = Field(min_length=1, max_length=2400, strict=True)
    sections: list[ModelSection] = Field(min_length=2, max_length=6)


class ModelRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    status: Literal["completed"] = "completed"
    states: list[str]
    started_at: str = Field(alias="startedAt")
    finished_at: str = Field(alias="finishedAt")
    stop_reason: Literal["model_response_received"] = Field(default="model_response_received", alias="stopReason")
    provider: Literal["deepseek-compatible"] = "deepseek-compatible"
    model: str
    usage: dict[str, int]


class ModelResearchReport(ModelResearchRequest, ModelContent):
    model_config = ConfigDict(populate_by_name=True)
    mode: Literal["model"] = "model"
    is_mock: Literal[False] = Field(default=False, alias="isMock")
    evidence_status: Literal["not_retrieved"] = Field(default="not_retrieved", alias="evidenceStatus")
    sources: list[str] = Field(default_factory=list, max_length=0)
    tool_calls: list[dict[str, str]] = Field(default_factory=list, max_length=0, alias="toolCalls")
    limitations: list[str]
    run: ModelRun
