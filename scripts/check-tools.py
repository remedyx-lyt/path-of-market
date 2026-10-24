"""M1-2 离线回归：官方来源适配、PDF 真正提取、缓存与真实 HTTP 工具协议。"""

from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent"))

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.tools.cninfo import CninfoProvider, PublicTransport, SHANGHAI
from app.tools.contracts import ToolError
from app.tools.registry import ResearchTools


def sample_pdf():
    """内存中的小型测试 PDF；数字只为验证提取，不能进入正式研究。"""
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    for text in ["Research expense 123.45; revenue 999.00. " * 180, "Another page with R e s e a r c h expense 456.78.", ""]:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(("BT /F1 10 Tf 20 800 Td (" + text + ") Tj ET").encode("ascii"))
        page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def announcement(identifier="1234567890", year=2024, title=None, published="2025-03-10", code="300033", org="9900008416"):
    return {"secCode": code, "orgId": org, "announcementId": identifier,
            "announcementTitle": title or f"{year}年年度报告",
            "announcementTime": int(datetime.fromisoformat(published).replace(tzinfo=SHANGHAI).timestamp() * 1000),
            "adjunctUrl": f"finalpage/{published}/{identifier}.PDF"}


class FakeTransport:
    def __init__(self):
        self.items = [announcement(), announcement("1234567891", title="2024年年度报告摘要"),
                      announcement("1234567892", title="2024年年度报告（修订版）", published="2025-04-20"),
                      announcement("1234567893", code="600519", org="other"),
                      announcement("1234567894", year=2025, published="2026-03-10"),
                      announcement("1234567895", title="2024年年度报告英文版"),
                      announcement("1234567896", title="关于2024年年度报告的更正公告")]
        self.downloads = 0
        self.data = sample_pdf()
        self.forms = []
        self.has_more = False

    def get_json(self, url, *, form=None):
        if url.endswith("szse_stock.json"):
            return {"stockList": [{"code": "300033", "zwjc": "同花顺", "orgId": "9900008416"},
                                  {"code": "600519", "zwjc": "贵州茅台", "orgId": "gssh0600519"},
                                  {"code": "600001", "zwjc": "同花示例", "orgId": "other"}]}
        self.forms.append(form)
        return {"announcements": self.items, "hasMore": self.has_more}

    def get_bytes(self, url, **_):
        self.downloads += 1
        return self.data


class ToolChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.transport = FakeTransport()
        self.tools = ResearchTools(Path(self.tmp.name), CninfoProvider(self.transport))

    def call(self, name, arguments, code=None):
        result = self.tools.execute(name, arguments)
        self.assertTrue(result["callId"] and result["startedAt"] and result["finishedAt"])
        if code:
            self.assertEqual(result["status"], "failed", result)
            self.assertEqual(result["error"]["code"], code, result)
        else:
            self.assertEqual(result["status"], "completed", result)
        return result.get("data")

    def find(self, cutoff="2026-10-23", years=None):
        return self.call("find_documents", {"company": "同花顺", "years": years or [2024, 2025], "asOfDate": cutoff})

    def fetched(self):
        self.find()
        return self.call("fetch_document", {"documentId": "cninfo-1234567890"})

    def test_01_company_resolution(self):
        for query in ["同花顺", "300033", "300033.SZ", "SZ300033"]:
            self.assertEqual(self.call("resolve_company", {"company": query})["code"], "300033")
        self.call("resolve_company", {"company": "同花"}, "COMPANY_AMBIGUOUS")
        self.call("resolve_company", {"company": "不存在的公司"}, "COMPANY_NOT_FOUND")
        self.call("resolve_company", {"company": "300033.SH"}, "COMPANY_MARKET_MISMATCH")

    def test_02_discovery_filters_versions_and_cutoff(self):
        found = self.find("2025-03-20")
        self.assertEqual([d["documentId"] for d in found["documents"]], ["cninfo-1234567890"])
        self.assertEqual(found["missingYears"], [2025])
        found = self.find()
        self.assertEqual(len(found["documents"]), 3)
        self.assertEqual([d["documentId"] for d in found["documents"] if d["preferred"]],
                         ["cninfo-1234567894", "cninfo-1234567892"])
        self.assertTrue(all(d["sourceUrl"].startswith("https://static.cninfo.com.cn/") for d in found["documents"]))

    def test_03_strict_arguments_and_unknown_tool(self):
        self.call("bash", {"command": "ignored"}, "UNKNOWN_TOOL")
        for args in [{"company": 123}, {"company": " "}, {"company": "同花顺", "extra": True}]:
            self.call("resolve_company", args, "INVALID_TOOL_ARGUMENTS")
        for updates in [{"years": [True]}, {"years": [2024, 2024]}, {"asOfDate": "2026-02-30"},
                        {"asOfDate": "20261023"}, {"asOfDate": "2099-01-01"}]:
            args = {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23", **updates}
            self.call("find_documents", args, "INVALID_TOOL_ARGUMENTS")
        self.call("read_document", {"documentId": "../.env", "page": 1}, "INVALID_TOOL_ARGUMENTS")
        self.call("read_document", {"documentId": "cninfo-1234567890", "page": True}, "INVALID_TOOL_ARGUMENTS")

    def test_04_pdf_download_parse_citations_and_cache(self):
        first = self.fetched()
        self.assertEqual(first["pageCount"], 3)
        self.assertEqual(first["emptyTextPages"], [3])
        self.assertFalse(first["cacheHit"])
        second = self.call("fetch_document", {"documentId": "cninfo-1234567890"})
        self.assertTrue(second["cacheHit"])
        self.assertEqual(self.transport.downloads, 1)
        page = self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1})
        self.assertIn("123.45", page["text"])
        self.assertEqual(page["citation"]["page"], 1)
        self.assertTrue(page["citation"]["sourceUrl"].endswith("#page=1"))
        self.assertEqual(len(page["document"]["sha256"]), 64)
        # 另一工具实例从磁盘缓存恢复，不需要再寻找或下载。
        tools = ResearchTools(Path(self.tmp.name), CninfoProvider(self.transport))
        self.assertEqual(tools.execute("read_document", {"documentId": "cninfo-1234567890", "page": 1})["status"], "completed")

    def test_05_page_continuation_search_and_empty_page(self):
        self.fetched()
        one = self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1, "limit": 100})
        self.assertTrue(one["truncated"])
        two = self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1, "offset": one["nextOffset"], "limit": 12000})
        self.assertFalse(two["truncated"])
        self.assertEqual(one["text"] + two["text"], self.tools.store.loaded("cninfo-1234567890")[1][0]["text"])
        match = self.call("search_document", {"documentId": "cninfo-1234567890", "query": "Research expense", "limit": 1})
        self.assertEqual(match["matches"][0]["page"], 1)
        self.assertEqual(match["nextStartPage"], 2)
        more = self.call("search_document", {"documentId": "cninfo-1234567890", "query": "Research expense", "startPage": 2})
        self.assertEqual(more["matches"][0]["page"], 2)
        empty = self.call("read_document", {"documentId": "cninfo-1234567890", "page": 3})
        self.assertEqual(empty["textStatus"], "empty_or_needs_ocr")
        self.call("read_document", {"documentId": "cninfo-1234567890", "page": 9}, "PAGE_OUT_OF_RANGE")
        self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1, "offset": 200000}, "OFFSET_OUT_OF_RANGE")

    def test_06_missing_invalid_pdf_and_integrity(self):
        self.call("fetch_document", {"documentId": "cninfo-9876543210"}, "DOCUMENT_NOT_FOUND")
        self.find()
        self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1}, "DOCUMENT_NOT_FETCHED")
        self.transport.data = b"<html>access denied</html>"
        self.call("fetch_document", {"documentId": "cninfo-1234567890"}, "INVALID_PDF")
        self.transport.data = sample_pdf()
        self.fetched()
        (Path(self.tmp.name) / "cninfo-1234567890.pdf").write_bytes(b"changed")
        self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1}, "CACHE_INTEGRITY_ERROR")

    def test_07_provider_failure_partial_query_and_sse(self):
        self.transport.has_more = True
        found = self.find()
        self.assertFalse(found["queryComplete"])
        self.assertTrue(found["gaps"])
        self.assertEqual(len(self.transport.forms), 6)
        self.transport.has_more = False
        self.call("find_documents", {"company": "600519", "years": [2024], "asOfDate": "2026-10-23"})
        self.assertEqual(self.transport.forms[-1]["column"], "sse")
        with patch.object(self.transport, "get_json", side_effect=ToolError("SOURCE_UNAVAILABLE", "来源不可用")):
            self.call("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"}, "SOURCE_UNAVAILABLE")

    def test_08_no_arbitrary_url_or_private_error_body(self):
        with self.assertRaises(ToolError):
            PublicTransport().get_bytes("http://127.0.0.1/.env")
        self.find()
        with patch.object(self.transport, "get_bytes", side_effect=RuntimeError("private-path-or-upstream-body")):
            result = self.tools.execute("fetch_document", {"documentId": "cninfo-1234567890"})
        self.assertNotIn("private-path", json.dumps(result))
        self.assertEqual(result["error"]["code"], "TOOL_EXECUTION_ERROR")

    def test_09_schema_declarations(self):
        declarations = self.tools.declarations()
        self.assertEqual(len(declarations), 8)
        schema = next(d for d in declarations if d["function"]["name"] == "find_documents")["function"]["parameters"]
        self.assertIn("asOfDate", schema["required"])
        self.assertFalse(schema["additionalProperties"])

    def test_10_actual_http_contract(self):
        import uvicorn
        import app.api.routes.tools as routes
        from app.main import app
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        with patch.object(routes, "get_research_tools", return_value=self.tools):
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                self.assertTrue(server.started)
                base = f"http://127.0.0.1:{port}"
                with urlopen(base + "/tools", timeout=5) as response:
                    self.assertEqual(len(json.load(response)["tools"]), 8)
                with urlopen(Request(base + "/tools/execute", data=json.dumps({"name": "find_documents", "arguments":
                        {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"}}).encode(),
                        headers={"Content-Type": "application/json"}), timeout=5) as response:
                    self.assertEqual(json.load(response)["status"], "completed")
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/tools/execute", data=b'{"name":123}', headers={"Content-Type": "application/json"}), timeout=5)
                self.assertEqual(error.exception.code, 422)
                error.exception.read()
                error.exception.close()
                with urlopen(base + "/health", timeout=5) as response:
                    self.assertEqual(json.load(response)["mode"], "mock")
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                sock.close()

    def test_11_full_document_batches_without_skipped_text(self):
        self.fetched()
        cursor = {"startPage": 1, "offset": 0}
        text, seen = "", set()
        for _ in range(30):
            batch = self.call("read_document_batch", {"documentId": "cninfo-1234567890",
                              "maxPages": 2, "maxCharacters": 1000, **cursor})
            for page in batch["pages"]:
                text += page["text"]
                seen.add(page["page"])
            cursor = batch["nextCursor"]
            if cursor is None:
                self.assertTrue(batch["endOfDocument"])
                break
        self.assertIsNone(cursor)
        self.assertEqual(seen, {1, 2, 3})
        self.assertEqual(text, "".join(p["text"] for p in self.tools.store.loaded("cninfo-1234567890")[1]))

    def test_12_pdf_parser_limits_and_cache_rebuild(self):
        import subprocess
        self.find()
        with patch("app.tools.documents.subprocess.run", side_effect=subprocess.TimeoutExpired("parser", 60)):
            self.call("fetch_document", {"documentId": "cninfo-1234567890"}, "PDF_PARSE_TIMEOUT")
        self.fetched()
        cache_path = Path(self.tmp.name) / "cninfo-1234567890.pages.json"
        index = json.loads(cache_path.read_text(encoding="utf-8"))
        index["pages"][0]["text"] = "corrupted"
        cache_path.write_text(json.dumps(index), encoding="utf-8")
        page = self.call("read_document", {"documentId": "cninfo-1234567890", "page": 1})
        self.assertIn("123.45", page["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
