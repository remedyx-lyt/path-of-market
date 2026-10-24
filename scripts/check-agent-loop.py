"""M1-3 离线验收：动态工具协议、全文覆盖、恢复/停止边界与行情口径。"""

import asyncio
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent"))
from pypdf import PdfReader, PdfWriter
from app.core.config import ModelSettings, ModelServiceError
from app.schemas.agent import AgentResearchRequest
from app.services.agent_runner import AgentRunner, RunLimits, declarations
from app.services.model_client import complete_turn
from app.services.research_jobs import ResearchJob, JobStore
from app.tools.cninfo import CninfoProvider
from app.tools.market import MarketArguments, MarketProvider, compute_metrics, validate_rows
from app.tools.registry import ResearchTools
from app.tools.contracts import ToolError

spec = importlib.util.spec_from_file_location("tool_fixtures", ROOT / "scripts/check-tools.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
SETTINGS = ModelSettings("isolated-test-key-only", "http://127.0.0.1:1", "isolated-test", 1, 1800)
REQUEST = {"target": "同花顺", "question": "研究经营变化与行情，使用真实工具证据。", "asOfDate": "2026-10-23", "includeMarket": True, "includeCurrentPeriod": False, "includeFinancials": False}


def stock_data():
    series = [{"date": f"2024-01-0{i+2}", "open": raw, "close": raw, "high": raw, "low": raw,
               "volume": 100.0, "adjustedClose": adjusted} for i, (raw, adjusted) in enumerate([(100, 100), (50, 100), (55, 110)])]
    return {"series": series, "metrics": compute_metrics(series), "provider": "isolated", "currency": "CNY",
            "actualStart": series[0]["date"], "actualEnd": series[-1]["date"], "retrievedAt": "2026-10-23T00:00:00Z",
            "sourceUrls": ["https://example.com/raw", "https://example.com/hfq"], "limitations": ["隔离测试数据，不用于投资研究。"]}


class FakeMarket:
    def history(self, company, start, end):
        return {"company": company, "requestedStart": start, "requestedEnd": end, **stock_data()}


class ScriptedModel:
    def __init__(self, *, invalid_note=False, invalid_final=False, unknown_tool=False):
        self.decisions = 0
        self.readings = 0
        self.invalid_note, self.invalid_final, self.unknown_tool = invalid_note, invalid_final, unknown_tool
        self.received = []

    async def __call__(self, settings, messages, **kwargs):
        self.received.append(messages)
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        if not kwargs.get("tools"):
            task = json.loads(messages[1]["content"])
            if "references" in task:
                # 研究前的方法计划（M1-4 起每次研究都会按问题/预兆选择方法）。
                check = {"topic": "business", "question": "经营变化来自哪里", "evidenceNeeded": "年报原文",
                         "figureIdea": "无", "methodReference": task["references"][0]["reference"]}
                return {"role": "assistant", "content": json.dumps({"focus": "经营变化", "checks": [check] * 3, "unavailable": []},
                                                                   ensure_ascii=False)}, usage
            if "candidate" in task:
                return {"role": "assistant", "content": json.dumps(task["candidate"], ensure_ascii=False)}, usage
            self.readings += 1
            note = {"summary": "已检查本批所有原文。", "facts": [{"text": "本批含原文数字和研究费用，需核对实际单位。",
                "pages": [999 if self.invalid_note and self.readings == 1 else task["pages"][0]["page"]]}], "gaps": []}
            return {"role": "assistant", "content": json.dumps(note, ensure_ascii=False)}, usage
        if kwargs.get("tool_choice") == "none" and str(messages[-1].get("content", "")).startswith("报告正文已写好"):
            # 写作第二步：单独生成数据表（本脚本不关心表格内容）。
            return {"role": "assistant", "content": json.dumps({"tables": []})}, usage
        self.decisions += 1
        if self.unknown_tool and self.decisions == 1:
            calls = [("bash", {"command": "must-not-execute"})]
        elif self.decisions == (2 if self.unknown_tool else 1):
            calls = [("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"}),
                     ("get_market_data", {"company": "同花顺", "startDate": "2024-01-01", "endDate": "2026-10-23"})]
        elif self.decisions == (3 if self.unknown_tool else 2):
            calls = [("read_document", {"documentId": "cninfo-1234567890", "mode": "full"})]
        else:
            page = 999 if self.invalid_final and self.decisions == 3 else 1
            content = {"title": "隔离研究报告", "summary": "依据实际工具流程验证。", "sections": [
                {"heading": "经营证据", "content": "原文记录需结合单位与年度解释。", "citations": [{"sourceId": "cninfo-1234567890", "page": page}]},
                {"heading": "行情口径", "content": "实际价格变化与复权序列不同。", "citations": [{"sourceId": "market-300033", "page": None}]}]}
            return {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)}, usage
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{self.decisions}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
            for i, (name, args) in enumerate(calls)]}, usage


class LoopChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        transport = fixtures.FakeTransport()
        reader = PdfReader(BytesIO(transport.data))
        writer = PdfWriter()
        for page in list(reader.pages)[:2]:
            writer.add_page(page)
        output = BytesIO(); writer.write(output); transport.data = output.getvalue()
        self.tools = ResearchTools(Path(self.tmp.name), CninfoProvider(transport), FakeMarket())

    def runner(self, model=None, **limits):
        job = ResearchJob(AgentResearchRequest(**REQUEST))
        runner = AgentRunner(job, self.tools, SETTINGS, limits=replace(RunLimits(), **limits), completion=model or ScriptedModel())
        return job, runner

    async def test_01_dynamic_loop_complete_and_tool_id_pairing(self):
        model = ScriptedModel()
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual([c["name"] for c in job.tool_calls], ["find_documents", "get_market_data", "read_document"])
        self.assertTrue(all(c["textComplete"] for c in job.coverage))
        self.assertEqual(job.report["marketData"]["metrics"]["adjustedChangePct"], 10)
        for i, event in enumerate(job.events):
            self.assertEqual(event["parentId"], job.events[i-1]["id"] if i else None)
        for message in runner.messages:
            if message["role"] == "assistant" and message.get("tool_calls"):
                ids = {c["id"] for c in message["tool_calls"]}
                self.assertTrue(ids <= {m.get("tool_call_id") for m in runner.messages if m["role"] == "tool"})
        self.assertEqual(len(declarations()), 6)

    async def test_02_full_read_tracks_split_page_without_skipping(self):
        model = ScriptedModel()
        job, runner = self.runner(model, read_characters=1000)
        await runner.run()
        self.assertEqual(job.status, "completed")
        coverage = job.coverage[0]
        original = self.tools.store.loaded("cninfo-1234567890")[1]
        self.assertEqual(coverage["processedCharacters"], sum(len(p["text"]) for p in original))
        self.assertEqual(coverage["processedPages"], [1, 2])
        self.assertGreater(model.readings, 2)

    async def test_03_bad_reading_citation_repaired_before_coverage(self):
        model = ScriptedModel(invalid_note=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed")
        self.assertEqual(model.readings, 2)
        self.assertEqual(job.coverage[0]["batches"], 1)

    async def test_04_bad_final_citation_requires_correction(self):
        model = ScriptedModel(invalid_final=True)
        job, runner = self.runner(model)
        await runner.run()
        self.assertEqual(job.status, "completed")
        self.assertEqual(model.decisions, 4)
        self.assertTrue(any("尚未通过程序核查" in m.get("content", "") for m in runner.messages if m["role"] == "user"))

    async def test_05_unknown_tool_returned_as_error_then_recovers(self):
        job, runner = self.runner(ScriptedModel(unknown_tool=True))
        await runner.run()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.tool_calls[0]["errorCode"], "UNKNOWN_TOOL")

    async def test_06_call_and_context_budget_preserve_partial(self):
        for limits, reason in [({"max_model_calls": 2}, "model_call_budget"), ({"max_context_characters": 10}, "context_budget")]:
            job, runner = self.runner(**limits)
            await runner.run()
            self.assertEqual(job.status, "partial")
            self.assertEqual(job.report["run"]["stopReason"], reason)

    async def test_07_timeout_and_cancellation(self):
        async def slow(*_args, **_kwargs):
            await asyncio.sleep(30)
        job, runner = self.runner(slow, max_seconds=0.02)
        await runner.run()
        self.assertEqual(job.status, "partial")
        self.assertEqual(job.report["run"]["stopReason"], "time_budget")
        job, runner = self.runner(slow)
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.01)
        job.cancel_requested = True
        task.cancel()
        await task
        self.assertEqual(job.status, "cancelled")

    async def test_08_read_cache_reuses_model_output_with_source_identity(self):
        first_model = ScriptedModel()
        first, runner = self.runner(first_model)
        await runner.run()
        second_model = ScriptedModel()
        second, runner = self.runner(second_model)
        await runner.run()
        self.assertEqual(second.status, "completed")
        self.assertEqual(second_model.readings, 0)
        self.assertTrue(any(e["type"] == "reading_cache_reused" for e in second.events))

    async def test_09_cutoff_and_full_read_enforced(self):
        job, runner = self.runner()
        self.tools.execute("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        with self.assertRaises(ToolError) as error:
            await runner.read({"documentId": "cninfo-1234567890", "mode": "page", "page": 1})
        self.assertEqual(error.exception.code, "FULL_READ_REQUIRED")
        with self.assertRaises((ToolError, ValueError)):
            await runner.dispatch("get_market_data", {"company": "同花顺", "startDate": "2024-01-01", "endDate": "2026-10-24"})

    async def test_10_job_busy_and_cancel_without_paid_model(self):
        class FakeRunner:
            def __init__(self, job, *_): self.job = job
            async def run(self):
                self.job.status = "running"
                try: await asyncio.sleep(30)
                except asyncio.CancelledError: self.job.status = "cancelled"
        store = JobStore()
        with patch("app.services.research_jobs.AgentRunner", FakeRunner), patch("app.services.research_jobs.get_research_tools", return_value=self.tools):
            request = AgentResearchRequest(**REQUEST)
            job = store.start(request, SETTINGS)
            self.assertIsNone(store.start(request, SETTINGS))
            await asyncio.sleep(0)
            store.cancel(job)
            await job.task
            self.assertEqual(job.status, "cancelled")

    async def test_16_current_year_report_cannot_be_silently_omitted(self):
        transport = self.tools.provider.transport
        transport.items.append(fixtures.announcement("1234567999", year=2026, title="2026年半年度报告", published="2026-08-20"))
        job, runner = self.runner()
        job.request.include_current_period = True
        found = await runner.dispatch("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        self.assertEqual(runner.required_current["documentId"], "cninfo-1234567999")
        self.assertTrue(any(d["documentId"] == "cninfo-1234567999" for d in found["documents"]))
        await runner.read({"documentId": "cninfo-1234567890", "mode": "full"})
        await runner.dispatch("get_market_data", {"company": "同花顺", "startDate": "2024-01-01", "endDate": "2026-10-23"})
        content = {"title": "测试", "summary": "缺少当年报告", "sections": [
            {"heading": "经营", "content": "旧报告", "citations": [{"sourceId": "cninfo-1234567890", "page": 1}]},
            {"heading": "行情", "content": "指标", "citations": []}]}
        with self.assertRaises(ValueError) as error:
            runner.validate_content({"content": json.dumps(content)})
        self.assertIn("当年最新", str(error.exception))


class MarketChecks(unittest.TestCase):
    def test_11_split_does_not_create_false_loss(self):
        data = stock_data()
        self.assertEqual(data["metrics"]["adjustedChangePct"], 10)
        self.assertEqual(data["metrics"]["maxCloseDrawdownPct"], 0)
        self.assertEqual(data["metrics"]["lastRawClose"], 55)

    def test_12_known_drawdown(self):
        rows = [{"date": str(i), "close": p, "adjustedClose": p} for i, p in enumerate([100, 120, 90, 108])]
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["maxCloseDrawdownPct"], -25)
        self.assertEqual(metrics["adjustedChangePct"], 8)
        self.assertEqual(metrics["drawdownPeakDate"], "1")
        self.assertEqual(metrics["drawdownTroughDate"], "2")

    def test_13_invalid_dates_nan_duplicates_and_future_filter(self):
        for args in [{"company": "x", "startDate": "2026-10-23", "endDate": "2024-01-01"},
                     {"company": "x", "startDate": "2024-02-30", "endDate": "2026-10-23"}]:
            with self.assertRaises(ValueError): MarketArguments.model_validate(args)
        rows = [{"date": f"2024-01-0{i+2}", "open": 10, "close": 10, "low": 9, "high": 11, "volume": 100} for i in range(3)]
        self.assertEqual(len(validate_rows(rows, "2024-01-02", "2024-01-03")), 2)
        with self.assertRaises(ToolError): validate_rows([{**r, "close": "NaN"} for r in rows], "2024-01-01", "2024-01-31")
        with self.assertRaises(ToolError): validate_rows(rows + [{**rows[0], "volume": 200}], "2024-01-01", "2024-01-31")

    def test_14_primary_source_failure_falls_back_without_mixing(self):
        class Transport:
            def get_json(self, url):
                if "eastmoney" in url: raise ToolError("SOURCE_UNAVAILABLE", "fixture")
                adjusted = "hfq" in url
                key = "hfqday" if adjusted else "day"
                return {"data": {"sz300033": {key: [[r["date"], str(r["adjustedClose"] if adjusted else r["close"]),
                        str(r["adjustedClose"] if adjusted else r["close"]), str(r["adjustedClose"] if adjusted else r["close"]),
                        str(r["adjustedClose"] if adjusted else r["close"]), "100"] for r in stock_data()["series"]]}}}
        result = MarketProvider(Transport()).history({"code": "300033", "exchange": "SZSE"}, "2024-01-01", "2024-02-01")
        self.assertEqual(result["provider"], "tencent")
        self.assertEqual(result["metrics"]["adjustedChangePct"], 10)
        self.assertEqual(result["providerFailures"][0]["provider"], "eastmoney")


class NativeProtocolChecks(unittest.IsolatedAsyncioTestCase):
    async def test_15_real_http_native_tool_calls_and_truncation(self):
        state = {"mode": "tool", "payload": None}
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                state["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls = [{"id": "call_native", "type": "function", "function": {"name": "find_documents", "arguments": "{}"}}]
                if state["mode"] == "duplicate": calls += calls
                body = {"choices": [{"finish_reason": "length" if state["mode"] == "length" else "tool_calls",
                        "message": {"role": "assistant", "content": None, "tool_calls": calls}}], "usage": {"total_tokens": 100}}
                encoded = json.dumps(body).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        settings = replace(SETTINGS, base_url=f"http://127.0.0.1:{server.server_port}")
        try:
            message, _ = await complete_turn(settings, [{"role": "user", "content": "test"}], tools=declarations(), json_mode=False)
            self.assertEqual(message["tool_calls"][0]["id"], "call_native")
            self.assertEqual(len(state["payload"]["tools"]), 6)
            self.assertEqual(state["payload"]["thinking"]["type"], "disabled")
            for mode in ["length", "duplicate"]:
                state["mode"] = mode
                with self.assertRaises(ModelServiceError):
                    await complete_turn(settings, [{"role": "user", "content": "test"}], tools=declarations(), json_mode=False)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
