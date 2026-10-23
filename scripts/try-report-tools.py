"""联网验收年报工具；不调用模型。公司、年度来自输入，PDF 由程序自己寻找。"""

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent"))

from app.tools.registry import ResearchTools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", default="同花顺")
    parser.add_argument("--years", nargs="+", type=int, default=[2024, 2025])
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--query", default="研发投入")
    parser.add_argument("--output", type=Path, default=ROOT / "storage/runs/m1-2-tools.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    tools, records = ResearchTools(), []

    def call(name, arguments):
        result = tools.execute(name, arguments)
        records.append(result)
        print(name, result["status"], f"{result['durationMs']}ms", flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"kind": "tool-validation-not-agent-loop", "calls": records},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        if result["status"] != "completed":
            print(json.dumps(result["error"], ensure_ascii=False), flush=True)
            raise SystemExit(1)
        return result["data"]

    found = call("find_documents", {"company": args.company, "years": args.years, "asOfDate": args.as_of})
    print(json.dumps({"company": found["company"], "gaps": found["gaps"]}, ensure_ascii=False), flush=True)
    for document in found["documents"]:
        if not document["preferred"]:
            continue
        identifier = document["documentId"]
        downloaded = call("fetch_document", {"documentId": identifier})
        print(f"{document['title']} | {downloaded['pageCount']} 页 | {document['sourceUrl']}", flush=True)
        cursor = {"startPage": 1, "offset": 0}
        while cursor is not None:
            batch = call("read_document_batch", {"documentId": identifier, **cursor})
            cursor = batch["nextCursor"]
        print("全本原文已分批返回；本脚本不调用模型，不代表模型已通读。", flush=True)
        matched = call("search_document", {"documentId": identifier, "query": args.query, "limit": 3})
        if matched["matches"]:
            first_page = matched["matches"][0]["page"]
            page = call("read_document", {"documentId": identifier, "page": first_page})
            print(f"关键词所在 PDF 第 {first_page} 页：{page['text'][:240]}", flush=True)
        else:
            print("未命中关键词，请更换词语或按页阅读。", flush=True)
    print("完整工具返回已保存：", args.output, flush=True)
    if found["missingYears"] or not found["queryComplete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
