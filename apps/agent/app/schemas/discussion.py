"""报告旁的追问与局部修订；版本由程序合并，模型不能覆盖原报告。"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.agent import Citation


class FollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)
    action: Literal["ask", "revise"] = "ask"
    parent_id: UUID = Field(alias="parentId")
    request_id: UUID = Field(alias="requestId")


class SectionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    index: int = Field(ge=0, le=12, strict=True)
    heading: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=10000)
    citations: list[Citation] = Field(min_length=1, max_length=12)


class FollowupAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    answer: str = Field(min_length=1, max_length=16000)
    citations: list[Citation] = Field(default_factory=list, max_length=20)
    section_edits: list[SectionEdit] = Field(default_factory=list, alias="sectionEdits", max_length=12)
    summary: str | None = Field(default=None, min_length=1, max_length=3000)
