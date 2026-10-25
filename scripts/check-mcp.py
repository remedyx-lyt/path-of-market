"""MCP独立连通检查。--live才访问公开网络；不加载模型配置、不调用LLM。"""
import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent"))
from app.tools.public_web import PublicWeb, PublicSearchArguments, identifier


async def main(args):
    with TemporaryDirectory() as folder:
        web = PublicWeb(Path(folder))
        found = await web.search(PublicSearchArguments(query=args.query, numResults=2), date.today().isoformat())
        item = {"sourceId": identifier(args.url), "url": args.url, "title": "连通检查页面", "publishedAt": None}
        snapshot = await web.fetch(item)
        proof = {"searchServer": "exa", "readerServer": "official-fetch", "searchResults": len(found["results"]),
                 "bodyCharacters": len(snapshot["text"]), "fetchComplete": snapshot["fetchComplete"], "modelCalls": 0}
        print(json.dumps(proof, ensure_ascii=False))
        assert proof["searchResults"] and proof["fetchComplete"] and proof["bodyCharacters"] > 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--query", default="Model Context Protocol official tools documentation")
    parser.add_argument("--url", default="https://example.com")
    args = parser.parse_args()
    if not args.live:
        parser.error("公开网络检查需--live；离线检查请运行tests.test_public_web。")
    asyncio.run(main(args))
