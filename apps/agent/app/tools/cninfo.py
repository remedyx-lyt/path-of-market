"""巨潮公开披露网站适配器；端点变化只影响本模块，不绑定研究工作流。"""

from datetime import date, datetime, timedelta, timezone
import html
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.tools.contracts import ToolError

SITE = "https://www.cninfo.com.cn"
STATIC = "https://static.cninfo.com.cn"
SHANGHAI = timezone(timedelta(hours=8))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class PublicTransport:
    """固定官方主机、不转发模型密钥；限制每次请求的大小与等待时间。"""
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def get_bytes(self, url: str, *, form: dict | None = None, maximum: int = 8_000_000) -> bytes:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"www.cninfo.com.cn", "static.cninfo.com.cn"}
                or parsed.username or parsed.password or parsed.port not in {None, 443}):
            raise ToolError("SOURCE_URL_REJECTED", "资料地址不属于当前接入的官方来源。")
        headers = {"User-Agent": "Mozilla/5.0 PathOfMarket/0.3", "Referer": SITE + "/",
                   "Accept-Encoding": "identity"}
        body = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            body = urlencode(form).encode("utf-8")
        deadline = time.monotonic() + self.timeout
        try:
            with self.opener.open(Request(url, data=body, headers=headers), timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > maximum:
                    raise ToolError("SOURCE_TOO_LARGE", "来源文件超过本次大小限制。")
                chunks, total = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise ToolError("SOURCE_TIMEOUT", "公开资料读取超时，请稍后重试。")
                    chunk = response.read1(min(65536, maximum + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise ToolError("SOURCE_TOO_LARGE", "来源文件超过本次大小限制。")
                    chunks.append(chunk)
                return b"".join(chunks)
        except HTTPError as error:
            code = "SOURCE_RATE_LIMITED" if error.code == 429 else "SOURCE_UNAVAILABLE"
            raise ToolError(code, "公开资料来源暂时不可用，请稍后重试。") from None
        except TimeoutError:
            raise ToolError("SOURCE_TIMEOUT", "公开资料读取超时，请稍后重试。") from None
        except (OSError, URLError, ValueError):
            raise ToolError("SOURCE_UNAVAILABLE", "无法读取公开资料来源，请检查网络后重试。") from None

    def get_json(self, url: str, *, form: dict | None = None):
        try:
            return json.loads(self.get_bytes(url, form=form).decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            raise ToolError("SOURCE_INVALID_RESPONSE", "公开来源返回的内容不是有效数据，可能需要更新适配器。") from None


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


class CninfoProvider:
    name = "cninfo"

    def __init__(self, transport=None):
        self.transport = transport or PublicTransport()
        self._companies = None
        self._companies_at = 0

    def resolve_company(self, query: str) -> dict:
        if self._companies is None or time.monotonic() - self._companies_at > 86400:
            data = self.transport.get_json(SITE + "/new/data/szse_stock.json")
            if not isinstance(data, dict) or not isinstance(data.get("stockList"), list):
                raise ToolError("SOURCE_INVALID_RESPONSE", "公司目录格式发生变化，需要更新适配器。")
            rows = [r for r in data["stockList"] if isinstance(r, dict)
                    and re.fullmatch(r"[0-9]{6}", str(r.get("code", "")))
                    and isinstance(r.get("zwjc"), str) and isinstance(r.get("orgId"), str)]
            if not rows:
                raise ToolError("SOURCE_INVALID_RESPONSE", "公开公司目录为空，请稍后重试。")
            self._companies, self._companies_at = rows, time.monotonic()
        name = normalize_name(query)
        code = re.fullmatch(r"(?:sz|sh|bj)?([0-9]{6})(?:\.(?:sz|sh|bj))?", name)
        matches = [r for r in self._companies if r["code"] == (code[1] if code else name)
                   or normalize_name(r["zwjc"]) == name]
        if len(matches) != 1:
            candidates = matches or [r for r in self._companies if name in normalize_name(r["zwjc"])]
            raise ToolError("COMPANY_AMBIGUOUS" if candidates else "COMPANY_NOT_FOUND",
                            "请用证券简称或六位代码明确研究对象。",
                            {"candidates": [{"code": r["code"], "name": r["zwjc"]} for r in candidates[:10]]})
        row = matches[0]
        exchange = "SSE" if row["code"].startswith("6") else "SZSE" if row["code"].startswith(("0", "2", "3")) else "BSE"
        market_hint = re.search(r"^(sz|sh|bj)|\.(sz|sh|bj)$", name)
        if market_hint:
            expected = {"SZSE": "sz", "SSE": "sh", "BSE": "bj"}[exchange]
            if (market_hint[1] or market_hint[2]) != expected:
                raise ToolError("COMPANY_MARKET_MISMATCH", "代码与指定交易所不匹配，请核对研究对象。")
        if exchange == "BSE" or row["code"].startswith("2"):
            raise ToolError("MARKET_NOT_SUPPORTED", "本批先支持沪深 A 股年报；北交所、港股、美股后续接入。")
        return {"code": row["code"], "name": row["zwjc"], "exchange": exchange,
                "orgId": row["orgId"], "provider": self.name,
                "directoryUrl": SITE + "/new/data/szse_stock.json", "resolvedAt": utc_now()}

    def find_documents(self, company: dict, years: list[int], as_of: str) -> dict:
        # 同一会计年度的完整修订版可能较晚披露；一直查到研究截止日。
        cutoff = date.fromisoformat(as_of)
        if cutoff < date(min(years), 1, 1):
            return {"documents": [], "missingYears": sorted(years), "queryComplete": True}
        found, complete = {}, False
        for page in range(1, 7):
            result = self.transport.get_json(SITE + "/new/hisAnnouncement/query", form={
                "pageNum": page, "pageSize": 30, "column": "szse" if company["exchange"] == "SZSE" else "sse",
                "tabName": "fulltext", "stock": company["code"] + "," + company["orgId"],
                "searchkey": "", "secid": "", "plate": "", "category": "category_ndbg_szsh;",
                "trade": "", "seDate": f"{min(years)}-01-01~{as_of}", "sortName": "time",
                "sortType": "desc", "isHLtitle": "false"})
            if (not isinstance(result, dict) or "announcements" not in result
                    or result["announcements"] is not None and not isinstance(result["announcements"], list)
                    or not isinstance(result.get("hasMore"), bool)):
                raise ToolError("SOURCE_INVALID_RESPONSE", "公告查询格式发生变化，需要更新适配器。")
            for item in result["announcements"] or []:
                document = self._document(item, company, years, cutoff)
                if document:
                    found[document["documentId"]] = document
            if not result["hasMore"]:
                complete = True
                break
        documents = sorted(found.values(), key=lambda r: (r["fiscalYear"], r["publishedAt"], r["documentId"]), reverse=True)
        # 每年优先使用截止日内最新披露的完整版本，同时保留候选以供冲突核查。
        selected = set()
        for document in documents:
            document["preferred"] = document["fiscalYear"] not in selected
            selected.add(document["fiscalYear"])
        return {"documents": documents, "missingYears": sorted(set(years) - selected), "queryComplete": complete}

    def _document(self, item, company, years, cutoff):
        if not isinstance(item, dict) or item.get("secCode") != company["code"] or item.get("orgId") != company["orgId"]:
            return None
        title = html.unescape(re.sub(r"<[^>]+>", "", str(item.get("announcementTitle", "")))).strip()
        match = re.search(r"(20[0-9]{2})\s*年?年度报告(?:全文)?(?:[（(][^）)]*(?:修订|更新|更正|修正)[^）)]*[）)])?$", title)
        if (not match or int(match[1]) not in years
                or any(word in title for word in ("摘要", "英文", "取消", "撤销", "关于", "公告"))):
            return None
        try:
            published = datetime.fromtimestamp(item["announcementTime"] / 1000, SHANGHAI).date()
        except (TypeError, KeyError, ValueError, OSError, OverflowError):
            raise ToolError("SOURCE_INVALID_RESPONSE", "公告缺少可验证的披露日期。") from None
        if published > cutoff:
            return None
        identifier, relative = str(item.get("announcementId", "")), item.get("adjunctUrl", "")
        if (not re.fullmatch(r"[0-9]{6,20}", identifier) or not isinstance(relative, str)
                or not re.fullmatch(r"finalpage/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]+\.[Pp][Dd][Ff]", relative)):
            raise ToolError("SOURCE_INVALID_RESPONSE", "公告缺少有效 PDF 地址。")
        return {"documentId": "cninfo-" + identifier, "title": title, "companyCode": company["code"],
                "companyName": company["name"], "fiscalYear": int(match[1]), "publishedAt": published.isoformat(),
                "provider": self.name, "sourceUrl": STATIC + "/" + relative,
                "announcementUrl": SITE + "/new/disclosure/detail?" + urlencode({"stockCode": company["code"],
                    "announcementId": identifier, "orgId": company["orgId"], "announcementTime": published.isoformat()}),
                "discoveredAt": utc_now()}

    def download(self, url: str) -> bytes:
        return self.transport.get_bytes(url, maximum=40_000_000)
