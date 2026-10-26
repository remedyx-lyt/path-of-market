"""多服务商模型接口：.env 配置解析、各家请求参数差异、用量换算，以及对本地模拟 OpenAI 服务的工具调用与流式往返。不联网、不用真实密钥。"""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

import support  # noqa: F401  （设置导入路径）

from app.core.config import ModelServiceError, ModelSettings, load_model_settings
from app.services.model_client import complete_turn, usage_counts

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "DEEPSEEK_", "OPENAI_"))}


def settings_from(values):
    with patch.dict(os.environ, CLEAN_ENV, clear=True), patch("app.core.config.read_env_file", return_value=values):
        return load_model_settings()


class Config(unittest.TestCase):
    def test_old_deepseek_env_still_works(self):
        s = settings_from({"DEEPSEEK_API_KEY": "k", "DEEPSEEK_MODEL": "deepseek-flash"})
        self.assertEqual((s.provider, s.base_url, s.model, s.max_tokens_field, s.reasoning_mode),
                         ("deepseek", "https://api.deepseek.com", "deepseek-flash", "max_tokens", "deepseek"))
        self.assertIn("deepseek-flash", s.vision_models)

    def test_openai_needs_only_key_and_model(self):
        s = settings_from({"LLM_PROVIDER": "openai", "LLM_API_KEY": "k", "LLM_MODEL": "gpt-6-luna"})
        self.assertEqual((s.base_url, s.max_tokens_field, s.reasoning_effort, s.vision_models),
                         ("https://api.openai.com/v1", "max_completion_tokens", "none", ()))
        self.assertEqual(settings_from({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k", "LLM_MODEL": "m"}).api_key, "k")
        self.assertEqual(settings_from({"LLM_PROVIDER": "openai", "LLM_API_KEY": "k", "LLM_MODEL": "m", "LLM_REASONING_EFFORT": "omit"}).reasoning_effort, "")
        with self.assertRaises(ModelServiceError) as caught:
            settings_from({"LLM_PROVIDER": "openai", "LLM_API_KEY": "k"})
        self.assertIn("LLM_MODEL", caught.exception.message)

    def test_compatible_service_needs_base_url(self):
        with self.assertRaises(ModelServiceError) as caught:
            settings_from({"LLM_PROVIDER": "openai-compatible", "LLM_API_KEY": "k", "LLM_MODEL": "qwen"})
        self.assertIn("LLM_BASE_URL", caught.exception.message)
        s = settings_from({"LLM_PROVIDER": "openai-compatible", "LLM_API_KEY": "k", "LLM_MODEL": "qwen", "LLM_BASE_URL": "https://example.com/v1/"})
        self.assertEqual((s.base_url, s.reasoning_mode, s.max_tokens_field), ("https://example.com/v1", "none", "max_tokens"))

    def test_missing_key_and_unknown_provider(self):
        with self.assertRaises(ModelServiceError) as caught:
            settings_from({"LLM_PROVIDER": "openai", "LLM_MODEL": "m"})
        self.assertEqual(caught.exception.code, "MODEL_NOT_CONFIGURED")
        self.assertIn("OPENAI_API_KEY", caught.exception.message)
        with self.assertRaises(ModelServiceError) as caught:
            settings_from({"LLM_PROVIDER": "claude", "LLM_API_KEY": "k"})
        self.assertEqual(caught.exception.code, "MODEL_CONFIG_ERROR")


class Usage(unittest.TestCase):
    def test_openai_cached_tokens_become_hit_and_miss(self):
        counts = usage_counts({"prompt_tokens": 2006, "completion_tokens": 300, "total_tokens": 2306, "prompt_tokens_details": {"cached_tokens": 1920}})
        self.assertEqual((counts["prompt_cache_hit_tokens"], counts["prompt_cache_miss_tokens"]), (1920, 86))

    def test_deepseek_fields_unchanged(self):
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}
        self.assertEqual(usage_counts(usage), usage)


class FakeOpenAI(BaseHTTPRequestHandler):
    """本地模拟 Chat Completions：记下收到的请求；有 tools 时回一个工具调用，stream=true 时按 SSE 分片返回。"""

    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        usage = {"prompt_tokens": 2006, "completion_tokens": 30, "total_tokens": 2036, "prompt_tokens_details": {"cached_tokens": 1920}}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ['{"ok"', ': true}']:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": piece}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
            self.wfile.write(b"data: " + json.dumps({"choices": [], "usage": usage}).encode() + b"\n\ndata: [DONE]\n\n")
            return
        if body.get("tools") and body.get("tool_choice") != "none":
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "find_documents", "arguments": '{"company":"x"}'}}]}
            reason = "tool_calls"
        else:
            message, reason = {"role": "assistant", "content": '{"ok": true}'}, "stop"
        data = json.dumps({"choices": [{"index": 0, "message": message, "finish_reason": reason}], "usage": usage}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MockServer(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeOpenAI.requests.clear()
        self.openai = ModelSettings("test-key", self.base, "gpt-6-luna", 5, 1800, (), 30, 3600,
                                    "openai", "max_completion_tokens", "reasoning_effort", "none")

    async def test_openai_tool_call_round_trip(self):
        tools = [{"type": "function", "function": {"name": "find_documents", "parameters": {"type": "object"}}}]
        message, usage = await complete_turn(self.openai, [{"role": "user", "content": "找年报"}], tools=tools, max_tokens=500, json_mode=False)
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "find_documents")
        self.assertEqual(usage["prompt_cache_hit_tokens"], 1920)
        sent = FakeOpenAI.requests[-1]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["auth"], "Bearer test-key")
        body = sent["body"]
        self.assertEqual((body["max_completion_tokens"], body["reasoning_effort"]), (500, "none"))
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("thinking", body)  # DeepSeek 私有参数不发给其他服务商

    async def test_openai_streaming_and_json_mode(self):
        pieces = []
        message, usage = await complete_turn(self.openai, [{"role": "user", "content": "只输出 JSON"}], on_text=pieces.append)
        self.assertEqual(json.loads(message["content"]), {"ok": True})
        self.assertEqual("".join(pieces), '{"ok": true}')
        self.assertEqual(usage["prompt_cache_miss_tokens"], 86)
        body = FakeOpenAI.requests[-1]["body"]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["stream_options"], {"include_usage": True})

    async def test_deepseek_request_is_unchanged(self):
        deepseek = replace(self.openai, provider="deepseek", max_tokens_field="max_tokens", reasoning_mode="deepseek", reasoning_effort="")
        await complete_turn(deepseek, [{"role": "user", "content": "JSON"}], max_tokens=700)
        body = FakeOpenAI.requests[-1]["body"]
        self.assertEqual((body["thinking"], body["max_tokens"]), ({"type": "disabled"}, 700))
        self.assertNotIn("reasoning_effort", body)
        self.assertNotIn("max_completion_tokens", body)

    async def test_compatible_service_sends_no_private_parameters(self):
        compatible = replace(self.openai, provider="openai-compatible", max_tokens_field="max_tokens", reasoning_mode="none", reasoning_effort="")
        await complete_turn(compatible, [{"role": "user", "content": "JSON"}], max_tokens=300)
        body = FakeOpenAI.requests[-1]["body"]
        self.assertEqual(body["max_tokens"], 300)
        self.assertFalse({"thinking", "reasoning_effort", "max_completion_tokens"} & set(body))


if __name__ == "__main__":
    unittest.main()
