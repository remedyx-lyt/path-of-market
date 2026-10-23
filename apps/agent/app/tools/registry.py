"""参考 Pi 的工具定义/执行分离；不依赖特定模型 SDK 或网页。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import time
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import PROJECT_ROOT
from app.tools.cninfo import CninfoProvider
from app.tools.contracts import (CompanyArguments, DocumentArguments, FindArguments,
                                 ReadArguments, SearchArguments, BatchReadArguments, ToolError)
from app.tools.documents import DocumentStore


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type
    method: str

    def declaration(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                "parameters": self.arguments.model_json_schema(by_alias=True)}}


TOOLS = (
    ToolDefinition("resolve_company", "从巨潮当前公司目录识别沪深证券简称或六位代码；歧义返回候选。", CompanyArguments, "resolve"),
    ToolDefinition("find_documents", "在线查找公司指定会计年度、截止日前披露的完整年报；排除摘要并保留修订版本。无需用户上传。", FindArguments, "find"),
    ToolDefinition("fetch_document", "下载 find_documents 发现的官方 PDF，缓存、校验并提取按页文本。", DocumentArguments, "fetch"),
    ToolDefinition("search_document", "在已下载 PDF 中搜索关键词并返回命中物理页和片段；可继续分页。", SearchArguments, "search"),
    ToolDefinition("read_document", "读取已下载 PDF 指定物理页原文与来源；过长时用 nextOffset 继续。", ReadArguments, "read"),
    ToolDefinition("read_document_batch", "连续分批通读选定年报全部页面；从第一页开始，用 nextCursor 接续到 endOfDocument。关键词搜索仅辅助复查。", BatchReadArguments, "read_batch"),
)


class ResearchTools:
    def __init__(self, root: Path | None = None, provider=None):
        self.provider = provider or CninfoProvider()
        self.store = DocumentStore(root if root is not None else PROJECT_ROOT / "storage/documents")
        self.definitions = {tool.name: tool for tool in TOOLS}

    def declarations(self):
        return [tool.declaration() for tool in TOOLS]

    def execute(self, name: str, arguments: dict) -> dict:
        start, clock = datetime.now(timezone.utc).isoformat(), time.monotonic()
        result = {"callId": str(uuid4()), "name": name, "startedAt": start}
        try:
            if name not in self.definitions:
                raise ToolError("UNKNOWN_TOOL", "此工具尚未注册。")
            tool = self.definitions[name]
            args = tool.arguments.model_validate(arguments)
            data = getattr(self, tool.method)(args)
            result.update(status="completed", data=data, error=None)
        except ValidationError as error:
            result.update(status="failed", data=None, error={"code": "INVALID_TOOL_ARGUMENTS",
                "message": "工具参数无效，请按工具定义提供公司、年度、日期或页码。",
                "details": {"fields": [".".join(map(str, e["loc"])) for e in error.errors(include_input=False)]}})
        except ToolError as error:
            result.update(status="failed", data=None,
                          error={"code": error.code, "message": error.message, "details": error.details})
        except Exception:
            # 不向模型或 HTTP 调用方暴露本地路径、堆栈或第三方响应。
            result.update(status="failed", data=None, error={"code": "TOOL_EXECUTION_ERROR",
                          "message": "工具执行失败，未生成可用证据。", "details": {}})
        result.update(finishedAt=datetime.now(timezone.utc).isoformat(),
                      durationMs=round((time.monotonic() - clock) * 1000))
        return result

    def resolve(self, args):
        return self.provider.resolve_company(args.company)

    def find(self, args):
        company = self.provider.resolve_company(args.company)
        result = self.provider.find_documents(company, args.years, args.as_of_date)
        for document in result["documents"]:
            self.store.register(document)
        gaps = [f"{year} 年完整年报在当前来源与截止日期下未找到。" for year in result["missingYears"]]
        if not result["queryComplete"]:
            gaps.append("已到公告查询页数上限，结果可能不完整。")
        return {"company": company, "asOfDate": args.as_of_date, **result, "gaps": gaps,
                "source": "巨潮公开披露网站", "searchedAt": datetime.now(timezone.utc).isoformat()}

    def fetch(self, args):
        return self.store.fetch(args.document_id, self.provider)

    def read(self, args):
        return self.store.read(args.document_id, args.page, args.offset, args.limit)

    def search(self, args):
        return self.store.search(args.document_id, args.query, args.start_page, args.limit)

    def read_batch(self, args):
        return self.store.read_batch(args.document_id, args.start_page, args.offset, args.max_pages, args.max_characters)


@lru_cache(maxsize=1)
def get_research_tools():
    return ResearchTools()
