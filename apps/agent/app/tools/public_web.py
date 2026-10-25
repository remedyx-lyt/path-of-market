"""M2-7：官方 MCP SDK 的只读适配，Exa 搜索 + 官方 Fetch 正文。

不把远端工具描述/提示加载为系统指令，不开放 shell、sampling 或用户文件。
搜索只发现来源；获取完整快照与模型阅读覆盖在 runner_web 中分别记录。
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit

from jsonschema import validate
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from pydantic import BaseModel, ConfigDict, Field
from app.core.config import PROJECT_ROOT
from app.tools.cninfo import utc_now
from app.tools.contracts import ToolError
from app.tools.documents import write_json

DEFAULT_ENDPOINT = "https://mcp.exa.ai/mcp?tools=web_search_advanced_exa"
CHUNK_SIZE = 24000
TRUNCATED = re.compile(r"\n\n<error>Content truncated\. Call the fetch tool with a start_index of (\d+) to get more content\.</error>$")


class PublicSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=500, description="只发本次公开检索所需词，不含用户画像或私人材料。")
    num_results: int = Field(default=4, ge=1, le=8, alias="numResults")
    domains: list[str] = Field(default_factory=list, max_length=6, description="优先公司官网、交易所、政府与行业一手来源的域名。")


class WebReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    source_id: str = Field(alias="sourceId", pattern=r"^web-[a-f0-9]{24}$")
    mode: str = Field(default="full", pattern=r"^(full|search)$")
    query: str = Field(default="", max_length=100, description="search仅在完整读过后用于原文回查。")


@dataclass(frozen=True)
class WebSettings:
    enabled: bool = True
    endpoint: str = DEFAULT_ENDPOINT
    timeout: float = 45


def load_web_settings():
    # 单独读取自己的非敏感配置；不要求模型密钥，不继承整个 .env 给子进程。
    names = {"MCP_WEB_ENABLED", "MCP_SEARCH_URL", "MCP_TIMEOUT_SECONDS"}
    values = {}
    path = PROJECT_ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in names:
                values[key] = value.strip().strip("\"'")
    values.update({k: os.environ[k] for k in names if k in os.environ})
    try:
        endpoint = values.get("MCP_SEARCH_URL", DEFAULT_ENDPOINT).strip()
        parts = urlsplit(endpoint)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError
        timeout = float(values.get("MCP_TIMEOUT_SECONDS", "45"))
        if not 5 <= timeout <= 120:
            raise ValueError
        return WebSettings(values.get("MCP_WEB_ENABLED", "true").lower() not in {"0", "false", "no"}, endpoint, timeout)
    except ValueError:
        raise ToolError("MCP_CONFIG_ERROR", "MCP配置无效，请核对HTTPS搜索入口与5–120秒超时。") from None


def public_url(value):
    """发现阶段仅接收公开HTTPS；Fetch服务另核查DNS与每次重定向目标。"""
    try:
        u = urlsplit(value.strip())
        if u.scheme == "http" and u.hostname == "static.cninfo.com.cn":
            u = u._replace(scheme="https")
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in {None, 443}:
            raise ValueError
        if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError
        if u.hostname.lower() in {"localhost", "metadata.google.internal"} or "." not in u.hostname:
            raise ValueError
        try:
            if not ipaddress.ip_address(u.hostname).is_global:
                raise ValueError
        except ValueError as e:
            # 域名不是IP；数字地址/IPv6的非公开情况仍必须拒绝。
            if re.fullmatch(r"[\d.]+", u.hostname) or ":" in u.hostname:
                raise ValueError from e
        return urlunsplit((u.scheme, u.netloc.lower(), u.path or "/", u.query, ""))
    except (ValueError, AttributeError):
        raise ToolError("WEB_URL_REJECTED", "仅支持公开HTTPS网页，不能读取本地/内网地址。") from None


def identifier(url):
    return "web-" + sha256(url.encode()).hexdigest()[:24]


def published_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def result_text(result):
    if result.is_error:
        raise ToolError("MCP_TOOL_ERROR", "MCP服务未能完成操作（可能限流、站点拒绝或正文不可读取），未计为有效证据。")
    return "\n".join(c.text for c in result.content if c.type == "text")


def grouped_code(error):
    nested = getattr(error, "exceptions", ())
    if nested:
        codes = [grouped_code(e) for e in nested]
        return "MCP_RATE_LIMITED" if "MCP_RATE_LIMITED" in codes else "MCP_TIMEOUT" if "MCP_TIMEOUT" in codes else "MCP_UNAVAILABLE"
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429:
        return "MCP_RATE_LIMITED"
    return "MCP_TIMEOUT" if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower() else "MCP_UNAVAILABLE"


class MCPGateway:
    """每次操作独立的有界连接；上下文退出由SDK关闭HTTP/stdio及子进程。"""
    def __init__(self, settings=None, *, search_server=None, fetch_server=None):
        self.settings = settings or load_web_settings()
        self.search_server = search_server or self.settings.endpoint
        # SDK只继承安全运行变量；固定模块/参数，没有模型传入命令或额外进程权限。
        self.fetch_server = fetch_server or StdioServerParameters(command=sys.executable, args=["-m", "mcp_server_fetch"])

    @asynccontextmanager
    async def connect(self, which):
        if not self.settings.enabled:
            raise ToolError("MCP_DISABLED", "公开信息MCP已关闭，可在.env启用MCP_WEB_ENABLED。")
        try:
            async with asyncio.timeout(self.settings.timeout):
                async with Client(self.search_server if which == "search" else self.fetch_server,
                                  read_timeout_seconds=self.settings.timeout) as client:
                    listing = await client.list_tools()
                    schemas = {t.name: t.input_schema for t in listing.tools}
                    yield client, schemas
        except (asyncio.CancelledError, ToolError):
            raise
        except Exception as error:
            # SDK任务组可能包装错误；不向前端/模型暴露带凭据的URL和堆栈。
            def find_tool(e):
                if isinstance(e, ToolError):
                    return e
                return next((t for child in getattr(e, "exceptions", ()) if (t := find_tool(child))), None)
            if original := find_tool(error):
                raise original from None
            code = grouped_code(error)
            raise ToolError(code, {"MCP_RATE_LIMITED": "公开搜索MCP达到免费限流，请稍后重试；已有资料保留。",
                                   "MCP_TIMEOUT": "MCP操作超时，已有资料和阅读游标保留，可继续。"}.get(code, "MCP连接或协议操作失败，已有资料保留。")) from None

    async def call(self, client, schemas, name, arguments):
        if name not in {"web_search_advanced_exa", "fetch"} or name not in schemas:
            raise ToolError("MCP_TOOL_UNAVAILABLE", "MCP服务未提供约定的只读工具，请核对服务版本。")
        try:
            validate(arguments, schemas[name])
        except Exception:
            raise ToolError("MCP_SCHEMA_CHANGED", "远端工具参数格式已变化，未发送不兼容请求。") from None
        return await client.call_tool(name, arguments)


class PublicWeb:
    def __init__(self, root: Path, gateway=None):
        self.root = root / "public-web"
        self.gateway = gateway or MCPGateway()

    async def search(self, args, cutoff):
        for domain in args.domains:
            if not re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", domain):
                raise ToolError("INVALID_TOOL_ARGUMENTS", "domains只接受域名，不接受URL或路径。")
        params = {"query": args.query, "numResults": args.num_results,
                  "endPublishedDate": (date.fromisoformat(cutoff) + timedelta(days=1)).isoformat(),
                  "textMaxCharacters": 600, "enableSummary": False}
        if args.domains:
            params["includeDomains"] = args.domains
        async with self.gateway.connect("search") as (client, schemas):
            result = await self.gateway.call(client, schemas, "web_search_advanced_exa", params)
            result_text(result)  # 即使服务附带structuredContent，也不能忽略isError。
            content = result.structured_content
            try:
                body = content if isinstance(content, dict) and "results" in content else json.loads(result_text(result))
                results = body["results"]
                if not isinstance(results, list):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise ToolError("MCP_SEARCH_FORMAT_CHANGED", "搜索服务结果格式不符，未将摘要冒充完整资料。") from None
        documents, excluded = [], 0
        for item in results[:args.num_results]:
            try:
                url = public_url(item["url"])
            except (ToolError, KeyError):
                excluded += 1
                continue
            published = published_date(item.get("publishedDate"))
            if published and published > cutoff:
                excluded += 1
                continue
            documents.append({"sourceId": identifier(url), "url": url, "title": str(item.get("title") or url)[:300],
                              "publishedAt": published, "dateStatus": "search_metadata" if published else "unknown",
                              "snippet": str(item.get("text") or "")[:600], "format": "pdf" if urlsplit(url).path.lower().endswith(".pdf") else "web",
                              "provider": "exa-mcp", "discoveredAt": utc_now()})
        return {"results": documents, "excludedResults": excluded, "asOfDate": cutoff, "provider": "exa-mcp",
                "instruction": "仅发现，摘要不是已读证据。选择相关网页用read_web_document full；PDF仍走官方PDF工具。发布日期未知的网页不能支持截止日事实。"}

    def path(self, sid):
        if not re.fullmatch(r"web-[a-f0-9]{24}", sid):
            raise ToolError("INVALID_SOURCE_ID", "网页来源标识无效。")
        return self.root / (sid + ".json")

    def load(self, sid, snapshot_sha=None):
        path = self.path(sid)
        if snapshot_sha is not None:
            if not re.fullmatch(r"[a-f0-9]{64}", snapshot_sha):
                raise ToolError("WEB_CACHE_INVALID", "网页快照标识无效。")
            archived = path.with_name(f"{sid}.{snapshot_sha}.json")
            if archived.exists():
                path = archived
        if not path.exists():
            return None
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if identifier(item["url"]) != sid or sha256(item["text"].encode()).hexdigest() != item["sha256"]:
                raise ValueError
            if snapshot_sha is not None and item["sha256"] != snapshot_sha:
                raise ValueError
            return item
        except (OSError, ValueError, KeyError, TypeError):
            raise ToolError("WEB_CACHE_INVALID", "网页快照校验失败，未使用损坏的正文。") from None

    def save(self, item):
        item["sha256"] = sha256(item["text"].encode()).hexdigest()
        write_json(self.path(item["sourceId"]), item)
        if item.get("fetchComplete"):
            archive = self.path(item["sourceId"]).with_name(f"{item['sourceId']}.{item['sha256']}.json")
            if not archive.exists():
                write_json(archive, item)

    async def fetch(self, discovered):
        sid, url = discovered["sourceId"], public_url(discovered["url"])
        if urlsplit(url).path.lower().endswith(".pdf"):
            raise ToolError("PDF_REQUIRES_DOCUMENT_TOOL", "此链接为PDF，请使用find_documents/read_document读取官方完整报告；不能把搜索摘要当全文。")
        cached = self.load(sid)
        # 新研究/新搜索再次选中同URL时重新取网页，不能永远拿第一次内容当最新；老分支按hash读不可变快照。
        if cached and cached.get("discoveredAt") != discovered.get("discoveredAt"):
            cached = None
        item = cached or {**discovered, "text": "", "fetchComplete": False, "retrievedAt": utc_now(), "fetchCursor": 0}
        if item["fetchComplete"]:
            return item
        async with self.gateway.connect("fetch") as (client, schemas):
            # 一次最多约24万字；保留游标再次full接续，不因大文章截断而假装完成。
            for _ in range(10):
                text = item["text"]
                overlap = min(256, len(text))
                start = len(text) - overlap
                result = await self.gateway.call(client, schemas, "fetch", {"url": url, "start_index": start, "max_length": CHUNK_SIZE, "raw": False})
                raw = result_text(result)
                header = re.search(r"Contents of (https://[^\n]+):\n", raw)
                if not header:
                    raise ToolError("WEB_TEXT_UNAVAILABLE", "网页未返回可解析的正文；可能拒绝访问或格式不支持。")
                public_url(header[1])  # 重定向后来源仍须是公开HTTPS
                body = raw[header.end():]
                truncated = TRUNCATED.search(body)
                if truncated:
                    body = body[:truncated.start()]
                    if int(truncated[1]) != start + len(body):
                        raise ToolError("WEB_CURSOR_INVALID", "正文分页游标与内容长度不符，未拼接不可靠文本。")
                if text and body[:overlap] != text[-overlap:]:
                    raise ToolError("WEB_CONTENT_CHANGED", "网页在分批获取期间发生变化，旧快照保留，未混接新旧正文。")
                if len(body) <= overlap and truncated:
                    raise ToolError("WEB_CURSOR_INVALID", "正文游标未前进，已停止重复读取。")
                item.update(text=text + body[overlap:], fetchComplete=not bool(truncated), fetchedUrl=header[1], fetchCursor=start+len(body))
                self.save(item)
                if item["fetchComplete"]:
                    break
        if not item["text"].strip():
            raise ToolError("WEB_TEXT_EMPTY", "未取得实质正文，未标为全文获取完成。")
        return item
