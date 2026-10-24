"""M2-9 过程实时可见：阶段事件、可读的工具与模型事件、写作流式输出（“正在写：××”）。"""

import asyncio
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from support import SETTINGS, FakeModel, RunnerFixture

from app.core.config import ModelServiceError
from app.services.model_client import complete_turn


def sse_server(chunks):
    """本地假供应商：按 DeepSeek 文档格式发出 data-only SSE，中间夹一条 keep-alive 注释，以 [DONE] 结束。"""
    received = {}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            received["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": keep-alive\n\n")
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def delta(text, finish=None, usage=None):
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}], "usage": usage}


class Streaming(unittest.IsolatedAsyncioTestCase):
    async def test_stream_reassembles_message_and_reports_text(self):
        report = '{"title":"t","sections":[{"heading":"收入"},{"heading":"现金流"}]}'
        pieces = [report[i : i + 9] for i in range(0, len(report), 9)]
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        chunks = [delta(p) for p in pieces[:-1]] + [delta(pieces[-1], "stop", usage)]
        server, received = sse_server(chunks)
        seen = []
        try:
            settings = replace(SETTINGS, base_url=f"http://127.0.0.1:{server.server_port}", timeout_seconds=5)
            message, counted = await complete_turn(settings, [{"role": "user", "content": "写"}], on_text=seen.append)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        self.assertEqual(message["content"], report)
        self.assertEqual("".join(seen), report)
        self.assertEqual(counted["total_tokens"], 15)
        self.assertEqual((received["payload"]["stream"], received["payload"]["stream_options"]), (True, {"include_usage": True}))

    async def test_truncated_stream_is_rejected(self):
        server, _ = sse_server([delta('{"title":"t"', "length")])
        try:
            settings = replace(SETTINGS, base_url=f"http://127.0.0.1:{server.server_port}", timeout_seconds=5)
            with self.assertRaises(ModelServiceError):
                await complete_turn(settings, [{"role": "user", "content": "写"}], on_text=lambda _: None)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()


class ActivityEvents(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_run_reports_phases_tools_and_plan(self):
        job, runner = self.runner(FakeModel(ready=True))
        await runner.run()
        self.assertEqual(job.status, "completed", job.error)
        phases = [e["phase"] for e in job.events if e["type"] == "phase_changed"]
        self.assertEqual(phases, ["methods", "research", "writing", "tables", "review", "done"])
        self.assertEqual(job.snapshot()["phase"], "done")
        started = {e["toolCallId"]: e for e in job.events if e["type"] == "tool_started"}
        finished = [e for e in job.events if e["type"] == "tool_finished"]
        self.assertTrue(finished and all(f["toolCallId"] in started and f["durationMs"] >= 0 for f in finished))
        read = next(e for e in started.values() if e["name"] == "read_document")
        self.assertEqual(read["label"], "阅读资料")
        self.assertTrue(read["summary"].startswith("通读 "))
        self.assertTrue(any(f["result"].startswith("找到 ") for f in finished if f["name"] == "find_documents"))
        planned = next(e for e in job.events if e["type"] == "methods_planned")
        self.assertTrue(planned["checks"] and planned["focus"])
        purposes = {e["purpose"] for e in job.events if e["type"] == "model_finished"}
        self.assertTrue({"形成研究计划", "决定下一步", "撰写正文", "整理数据表", "复核报告"} <= purposes)
        decided = next(e for e in job.events if e["type"] == "assistant_message")
        self.assertTrue(decided["message"].startswith("模型决定："))


if __name__ == "__main__":
    unittest.main(verbosity=2)
