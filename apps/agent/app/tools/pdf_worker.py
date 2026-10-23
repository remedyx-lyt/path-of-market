"""在可终止的子进程里解析 PDF；不联网、不执行文档内容。"""

import json
import sys

from pypdf import PdfReader


def extract(path: str) -> dict:
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        return {"error": "PDF_ENCRYPTED"}
    if not 1 <= len(reader.pages) <= 1000:
        return {"error": "PDF_PAGE_LIMIT"}
    labels = reader.page_labels
    pages, characters = [], 0
    for number, page in enumerate(reader.pages, 1):
        stream = page.get_contents()
        if stream and len(stream.get_data()) > 20_000_000:
            return {"error": "PDF_CONTENT_LIMIT"}
        text = page.extract_text() or ""
        characters += len(text)
        if characters > 8_000_000 or len(text) > 200_000:
            return {"error": "PDF_CONTENT_LIMIT"}
        pages.append({"page": number, "pageLabel": str(labels[number - 1]), "text": text})
    return {"pages": pages}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = extract(sys.argv[1])
    except Exception:
        result = {"error": "PDF_PARSE_ERROR"}
    print(json.dumps(result, ensure_ascii=False))
