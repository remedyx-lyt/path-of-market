"""工具参数和错误约定；资料正文始终是数据，不是执行指令。"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              populate_by_name=True)


class CompanyArguments(Arguments):
    company: str = Field(min_length=1, max_length=120, description="A 股证券简称或六位代码，如同花顺、300033。")


class FindArguments(CompanyArguments):
    years: list[Annotated[int, Field(ge=2000, le=2100)]] = Field(min_length=1, max_length=4,
        description="报告所属会计年度，不是披露年份；一次最多四年。")
    as_of_date: str = Field(alias="asOfDate", description="研究截止日期 YYYY-MM-DD；只用该日及之前披露的文件。")

    @field_validator("years")
    @classmethod
    def unique_years(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("年度不能重复")
        return value

    @field_validator("as_of_date")
    @classmethod
    def valid_date(cls, value):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or parsed > date.today():
            raise ValueError("需要有效且不晚于今天的 YYYY-MM-DD 日期")
        return value


class DocumentArguments(Arguments):
    document_id: str = Field(alias="documentId", pattern=r"^cninfo-[0-9]{6,20}$",
                             description="find_documents 返回的文件标识，不能传文件路径或任意 URL。")


class ReadArguments(DocumentArguments):
    page: int = Field(ge=1, description="从 1 开始的 PDF 物理页码，可能与印刷页码不同。")
    offset: int = Field(default=0, ge=0, description="本页文字字符偏移；配合 nextOffset 继续读取。")
    limit: int = Field(default=6000, ge=100, le=12000, description="本次返回的最大字符数。")


class SearchArguments(DocumentArguments):
    query: str = Field(min_length=1, max_length=100, description="单个原文关键词，例如研发投入；不是语义向量检索。")
    start_page: int = Field(default=1, alias="startPage", ge=1)
    limit: int = Field(default=8, ge=1, le=20, description="最多返回多少个命中页面。")


class BatchReadArguments(DocumentArguments):
    start_page: int = Field(default=1, alias="startPage", ge=1, description="从第一页开始按顺序通读，后续用 nextCursor。")
    offset: int = Field(default=0, ge=0, description="起始页内字符偏移，不能丢掉上一批未读完的页面。")
    max_pages: int = Field(default=8, alias="maxPages", ge=1, le=20)
    max_characters: int = Field(default=18000, alias="maxCharacters", ge=1000, le=30000)


class ToolCall(Arguments):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
