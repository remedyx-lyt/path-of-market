"""已发现资料的本地缓存与按页证据读取，不接收任意磁盘路径。"""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile
import threading

from app.tools.cninfo import utc_now
from app.tools.contracts import ToolError


def atomic_write(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, value: dict):
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


class DocumentStore:
    def __init__(self, root: Path):
        self.root = root
        self._guard = threading.Lock()
        self._locks = {}

    def lock(self, identifier):
        with self._guard:
            return self._locks.setdefault(identifier, threading.RLock())

    def path(self, identifier: str, suffix: str):
        if not re.fullmatch(r"cninfo-[0-9]{6,20}", identifier):
            raise ToolError("INVALID_DOCUMENT_ID", "文件标识无效。")
        path = self.root / (identifier + suffix)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ToolError("INVALID_DOCUMENT_ID", "文件缓存路径无效。")
        return path

    def register(self, document: dict):
        identifier = document["documentId"]
        with self.lock(identifier):
            path = self.path(identifier, ".json")
            if path.exists():
                previous = self.metadata(identifier)
                if previous["sourceUrl"] != document["sourceUrl"]:
                    raise ToolError("SOURCE_CONFLICT", "同一文件标识的来源地址发生变化，需要核查。")
                document = {**previous, **document}
            write_json(path, document)

    def metadata(self, identifier):
        path = self.path(identifier, ".json")
        if not path.exists():
            raise ToolError("DOCUMENT_NOT_FOUND", "尚未发现此文件，请先调用 find_documents。")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["documentId"] != identifier or not data["sourceUrl"].startswith("https://static.cninfo.com.cn/finalpage/"):
                raise ValueError
            return data
        except (ValueError, KeyError, TypeError, OSError):
            raise ToolError("CACHE_INVALID", "文件目录记录损坏，请重新查找资料。") from None

    def fetch(self, identifier, provider):
        with self.lock(identifier):
            metadata = self.metadata(identifier)
            pdf_path = self.path(identifier, ".pdf")
            cached = pdf_path.exists() and metadata.get("sha256") is not None
            if cached:
                body = pdf_path.read_bytes()
                if sha256(body).hexdigest() != metadata["sha256"]:
                    raise ToolError("CACHE_INTEGRITY_ERROR", "缓存 PDF 与校验值不一致，请移除此文件缓存后重试。")
            else:
                body = provider.download(metadata["sourceUrl"])
                if len(body) > 40_000_000 or not body.startswith(b"%PDF-"):
                    raise ToolError("INVALID_PDF", "来源返回的不是支持的 PDF 文件。")
                atomic_write(pdf_path, body)
                metadata.update(sha256=sha256(body).hexdigest(), downloadedAt=utc_now(), byteSize=len(body))
            index = self._index(identifier, metadata)
            metadata.update(
                pageCount=len(index["pages"]),
                extraction="pypdf-text",
                indexedAt=index["indexedAt"],
                indexSha256=sha256(self.path(identifier, ".pages.json").read_bytes()).hexdigest(),
            )
            write_json(self.path(identifier, ".json"), metadata)
            return {
                "document": metadata,
                "cacheHit": cached,
                "pageCount": len(index["pages"]),
                "emptyTextPages": [p["page"] for p in index["pages"] if not p["text"].strip()],
                "limitations": ["PDF 文本提取不等于表格结构识别；扫描页需后续 OCR。"],
            }

    def _index(self, identifier, metadata):
        index_path = self.path(identifier, ".pages.json")
        if index_path.exists():
            try:
                content = index_path.read_bytes()
                expected = metadata.get("indexSha256")
                index = json.loads(content.decode("utf-8"))
                if (
                    isinstance(index, dict)
                    and index.get("schemaVersion") == 1
                    and index.get("sha256") == metadata.get("sha256")
                    and (expected is None or expected == sha256(content).hexdigest())
                    and isinstance(index.get("pages"), list)
                    and 1 <= len(index["pages"]) <= 1000
                    and all(
                        isinstance(p, dict)
                        and p.get("page") == n
                        and isinstance(p.get("text"), str)
                        and isinstance(p.get("pageLabel"), str)
                        for n, p in enumerate(index["pages"], 1)
                    )
                ):
                    return index
            except (ValueError, OSError, UnicodeError):
                pass
        try:
            process = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("pdf_worker.py")), str(self.path(identifier, ".pdf"))],
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if process.returncode != 0:
                raise ToolError("PDF_PARSE_ERROR", "PDF 解析进程失败。")
            index = json.loads(process.stdout.decode("utf-8"))
        except subprocess.TimeoutExpired:
            raise ToolError("PDF_PARSE_TIMEOUT", "PDF 解析超过 60 秒，已停止本次解析。") from None
        except (OSError, UnicodeError, ValueError):
            raise ToolError("PDF_PARSE_ERROR", "无法解析该 PDF。") from None
        if "error" in index:
            raise ToolError(index["error"], "该 PDF 加密、损坏或超过本批解析限制，未生成可用文本。")
        index.update(schemaVersion=1, sha256=metadata["sha256"], indexedAt=utc_now())
        write_json(index_path, index)
        metadata["indexSha256"] = sha256(index_path.read_bytes()).hexdigest()
        return index

    def loaded(self, identifier):
        metadata = self.metadata(identifier)
        pdf_path, index_path = self.path(identifier, ".pdf"), self.path(identifier, ".pages.json")
        if not index_path.exists() or not pdf_path.exists() or not metadata.get("sha256"):
            raise ToolError("DOCUMENT_NOT_FETCHED", "请先调用 fetch_document 下载并解析文件。")
        if sha256(pdf_path.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ToolError("CACHE_INTEGRITY_ERROR", "PDF 校验失败，未使用缓存证据。")
        index = self._index(identifier, metadata)
        digest = sha256(index_path.read_bytes()).hexdigest()
        if metadata.get("indexSha256") != digest or metadata.get("indexedAt") != index["indexedAt"]:
            metadata.update(indexSha256=digest, indexedAt=index["indexedAt"])
            write_json(self.path(identifier, ".json"), metadata)
        return metadata, index["pages"]

    def read(self, identifier, page, offset, limit):
        with self.lock(identifier):
            metadata, pages = self.loaded(identifier)
            if page > len(pages):
                raise ToolError("PAGE_OUT_OF_RANGE", "页码超出 PDF 范围。", {"pageCount": len(pages)})
            entry = pages[page - 1]
            text = entry["text"]
            if offset > len(text):
                raise ToolError("OFFSET_OUT_OF_RANGE", "字符偏移超出本页范围。", {"totalCharacters": len(text)})
            end = min(len(text), offset + limit)
            return {
                "document": metadata,
                "page": page,
                "pageLabel": entry["pageLabel"],
                "text": text[offset:end],
                "offset": offset,
                "totalCharacters": len(text),
                "truncated": end < len(text),
                "nextOffset": end if end < len(text) else None,
                "textStatus": "extracted" if text.strip() else "empty_or_needs_ocr",
                "citation": {
                    "documentId": identifier,
                    "page": page,
                    "sourceUrl": metadata["sourceUrl"] + f"#page={page}",
                    "publishedAt": metadata["publishedAt"],
                },
            }

    def search(self, identifier, query, start_page, limit):
        with self.lock(identifier):
            metadata, pages = self.loaded(identifier)
            if start_page > len(pages):
                raise ToolError("PAGE_OUT_OF_RANGE", "起始页超出 PDF 范围。", {"pageCount": len(pages)})
            # 转义用户字符，只容忍 PDF 排版引入的空白；不用模型猜页码。
            pattern = re.compile(r"\s*".join(re.escape(c) for c in query if not c.isspace()), re.IGNORECASE)
            matches, next_page = [], None
            for entry in pages[start_page - 1 :]:
                hit = pattern.search(entry["text"])
                if hit:
                    page = entry["page"]
                    matches.append(
                        {
                            "page": page,
                            "pageLabel": entry["pageLabel"],
                            "excerpt": entry["text"][max(0, hit.start() - 120) : hit.end() + 280],
                            "sourceUrl": metadata["sourceUrl"] + f"#page={page}",
                        }
                    )
                    if len(matches) == limit:
                        next_page = page + 1 if page < len(pages) else None
                        break
            return {
                "document": metadata,
                "query": query,
                "matches": matches,
                "nextStartPage": next_page,
                "pageCount": len(pages),
                "searchType": "keyword",
                "limitations": ["只搜索可提取文本；未匹配不代表报告没有讨论该主题。"],
            }

    def read_batch(self, identifier, start_page, offset, max_pages, max_characters):
        """连续阅读，不用关键词筛掉页面；游标允许下一次精确接续。"""
        with self.lock(identifier):
            metadata, pages = self.loaded(identifier)
            if start_page > len(pages):
                raise ToolError("PAGE_OUT_OF_RANGE", "起始页超出 PDF 范围。", {"pageCount": len(pages)})
            if offset > len(pages[start_page - 1]["text"]):
                raise ToolError("OFFSET_OUT_OF_RANGE", "字符偏移超出起始页范围。")
            entries, remaining, next_cursor = [], max_characters, None
            for index in range(start_page - 1, min(len(pages), start_page - 1 + max_pages)):
                page = pages[index]
                begin = offset if index == start_page - 1 else 0
                end = min(len(page["text"]), begin + remaining)
                text = page["text"][begin:end]
                complete = end == len(page["text"])
                entries.append(
                    {
                        "page": page["page"],
                        "pageLabel": page["pageLabel"],
                        "offset": begin,
                        "endOffset": end,
                        "pageComplete": complete,
                        "text": text,
                        "textStatus": "extracted" if page["text"].strip() else "empty_or_needs_ocr",
                        "sourceUrl": metadata["sourceUrl"] + f"#page={page['page']}",
                    }
                )
                remaining -= len(text)
                next_cursor = (
                    {"startPage": page["page"], "offset": end}
                    if not complete
                    else {"startPage": page["page"] + 1, "offset": 0}
                    if page["page"] < len(pages)
                    else None
                )
                if not complete or remaining == 0:
                    break
            return {
                "document": metadata,
                "pages": entries,
                "nextCursor": next_cursor,
                "pageCount": len(pages),
                "endOfDocument": next_cursor is None,
                "coverageNote": "这是本次实际返回的原文范围；模型是否阅读及累计覆盖率须由研究 Runner 记录。",
            }
