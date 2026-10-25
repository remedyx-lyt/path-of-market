import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.support import RunnerFixture, FakeModel, USAGE, tool_call
from tests.mcp_fixture import make_server
from app.core.config import ModelServiceError
from app.schemas.agent import Citation
from app.services.model_json import stable_key
from app.services.research_recovery import load_recovery
from app.services.runner_web import WEB_READ_SYSTEM
from app.tools.contracts import ToolError
from app.tools.public_web import MCPGateway, PublicWeb, PublicSearchArguments, WebSettings, CHUNK_SIZE, public_url
from mcp.client.stdio import StdioServerParameters


class WebModel(FakeModel):
    def kind(self, messages, kwargs):
        return "reading" if messages[0].get("content") == WEB_READ_SYSTEM else super().kind(messages, kwargs)


class PublicWebTests(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    def service(self, **kwargs):
        server = make_server(**kwargs)
        return PublicWeb(self.tools.store.root, MCPGateway(WebSettings(timeout=10), search_server=server, fetch_server=server))

    async def discovered(self, runner):
        results = await runner.dispatch("search_public_information", {"query": "行业公开变化", "numResults": 8})
        return results["results"][0]["sourceId"]

    async def test_stdio_protocol_discovery_and_call(self):
        params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("mcp_fixture.py"))])
        service = PublicWeb(self.tools.store.root, MCPGateway(WebSettings(timeout=20), search_server=params, fetch_server=params))
        found = await service.search(PublicSearchArguments(query="隔离测试", numResults=8), "2026-10-23")
        self.assertEqual(len(found["results"]), 1)
        snapshot = await service.fetch(found["results"][0])
        self.assertTrue(snapshot["fetchComplete"])
        self.assertIn("100亿元", snapshot["text"])

    async def test_search_filters_future_private_and_does_not_read(self):
        self.tools.public_web = self.service()
        job, runner = self.runner(WebModel(), includeMarket=False)
        sid = await self.discovered(runner)
        self.assertTrue(sid.startswith("web-"))
        self.assertEqual(job.model_calls, 0)
        self.assertFalse(runner.sources)
        self.assertEqual(len(runner.web_discovered), 1)

    async def test_full_read_all_chars_citation_and_lookup(self):
        self.tools.public_web = self.service()
        model = WebModel()
        job, runner = self.runner(model, includeMarket=False)
        sid = await self.discovered(runner)
        data = await runner.dispatch("read_web_document", {"sourceId": sid})
        progress = data["coverage"]
        self.assertTrue(progress["fetchComplete"] and progress["textComplete"])
        self.assertEqual(progress["processedCharacters"], len(self.tools.public_web.load(sid)["text"]))
        self.assertGreater(progress["batches"], 1)
        self.assertEqual(progress["unit"], "segment")
        self.assertTrue(runner.check_citation(Citation(sourceId=sid)))
        self.assertFalse(runner.check_citation(Citation(sourceId=sid, page=1)))
        found = await runner.dispatch("read_web_document", {"sourceId": sid, "mode": "search", "query": "100亿元"})
        self.assertTrue(found["matches"])
        calls = job.model_calls
        await runner.dispatch("read_web_document", {"sourceId": sid})
        self.assertEqual(job.model_calls, calls)

    async def test_unknown_date_never_becomes_retrieval_date(self):
        self.tools.public_web = self.service(body="正文100亿元。", unknown_date=True)
        job, runner = self.runner(WebModel(), includeMarket=False)
        sid = await self.discovered(runner)
        await runner.dispatch("read_web_document", {"sourceId": sid})
        self.assertEqual(runner.sources[sid]["publishedAt"], "")
        self.assertFalse(runner.check_citation(Citation(sourceId=sid)))
        self.assertFalse(runner._valid_summary_citation(Citation(sourceId=sid)))

    async def test_checkpoint_restart_continues_unread_batch(self):
        self.tools.public_web = self.service()
        model = WebModel()
        job, runner = self.runner(model, includeMarket=False)
        sid = await self.discovered(runner)
        original = model.__call__
        blocked = True
        async def completion(settings, messages, **kwargs):
            if blocked and messages[0].get("content") == WEB_READ_SYSTEM and json.loads(messages[1]["content"])["offset"] >= CHUNK_SIZE:
                raise ModelServiceError("MODEL_UNAVAILABLE", "isolated disconnect")
            return await original(settings, messages, **kwargs)
        runner.completion = completion
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": sid})
        self.assertEqual(runner.coverage[sid]["nextOffset"], CHUNK_SIZE)
        self.assertFalse(runner.coverage[sid]["textComplete"])
        recovery = load_recovery(self.tools, job.task_id)
        from app.services.agent_runner import AgentRunner
        restored = AgentRunner(job, self.tools, runner.settings, completion=model, recovery=recovery)
        before = model.count("reading")
        await restored.dispatch("read_web_document", {"sourceId": sid})
        self.assertTrue(restored.coverage[sid]["textComplete"])
        self.assertEqual(model.count("reading")-before, 1)

    async def test_fetched_is_not_model_read_on_failure(self):
        self.tools.public_web = self.service(body="短正文100亿元。")
        async def failed(*args, **kwargs):
            raise ModelServiceError("MODEL_UNAVAILABLE", "isolated")
        _, runner = self.runner(failed, includeMarket=False)
        sid = await self.discovered(runner)
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": sid})
        self.assertTrue(runner.coverage[sid]["fetchComplete"])
        self.assertFalse(runner.coverage[sid]["textComplete"])
        self.assertEqual(runner.coverage[sid]["processedCharacters"], 0)

    async def test_selected_fetch_failure_keeps_gap(self):
        self.tools.public_web = self.service(failure=True)
        _, runner = self.runner(WebModel(), includeMarket=False)
        sid = await self.discovered(runner)
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": sid})
        self.assertIn(sid, runner.sources)
        self.assertFalse(runner.coverage[sid]["textComplete"])

    async def test_cache_tamper_is_rejected(self):
        self.tools.public_web = self.service(body="正文")
        _, runner = self.runner(WebModel(), includeMarket=False)
        sid = await self.discovered(runner)
        await runner.dispatch("read_web_document", {"sourceId": sid})
        path = self.tools.public_web.path(sid)
        item = json.loads(path.read_text(encoding="utf-8"))
        item["text"] += "changed"
        path.write_text(json.dumps(item), encoding="utf-8")
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": sid, "mode": "search", "query": "正文"})

    async def test_unselected_url_and_search_before_full_are_rejected(self):
        self.tools.public_web = self.service()
        _, runner = self.runner(WebModel(), includeMarket=False)
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": "web-"+"a"*24})
        sid = await self.discovered(runner)
        with self.assertRaises(ToolError):
            await runner.dispatch("read_web_document", {"sourceId": sid, "mode": "search", "query": "收入"})

    async def test_disabled_tools_not_advertised(self):
        self.tools.public_web = PublicWeb(self.tools.store.root, MCPGateway(WebSettings(enabled=False)))
        _, runner = self.runner()
        self.assertNotIn("search_public_information", [d["function"]["name"] for d in runner.declarations()])
        with self.assertRaises(ToolError) as error:
            await runner.dispatch("search_public_information", {"query": "公开测试"})
        self.assertEqual(error.exception.code, "MCP_DISABLED")

    async def test_no_arbitrary_tools(self):
        service = self.service()
        async with service.gateway.connect("search") as (client, schemas):
            with self.assertRaises(ToolError):
                await service.gateway.call(client, schemas, "bash", {"command": "no"})

    def test_url_boundaries(self):
        for value in ["file:///a", "http://example.org/a", "https://127.0.0.1/a", "https://10.0.0.1/a", "https://localhost/a", "https://a:b@example.org/a", "https://example.org:444/a"]:
            with self.subTest(value=value), self.assertRaises(ToolError):
                public_url(value)
        self.assertEqual(public_url("https://example.org/a#x"), "https://example.org/a")

    async def test_agent_loop_search_read_write(self):
        self.tools.public_web = self.service(body="公司经营变化：收入100亿元。")
        from app.tools.public_web import identifier
        sid = identifier("https://example.org/news")
        final = {"title": "隔离公开研究", "summary": "只使用隔离来源", "sections": [
            {"heading": "业务", "content": "公司收入100亿元。", "citations": [{"sourceId": sid, "page": None}]},
            {"heading": "局限", "content": "网页提取文字，无图片识别。", "citations": [{"sourceId": sid, "page": None}]},
        ]}
        model = WebModel(script=[[("search_public_information", {"query": "隔离研究", "numResults": 8})],
                                 [("read_web_document", {"sourceId": sid})], "final"], final=final)
        job, runner = self.runner(model, includeMarket=False)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(job.report["sources"][0]["kind"], "web")
        self.assertTrue(job.report["coverage"][0]["textComplete"])


if __name__ == "__main__":
    unittest.main()
