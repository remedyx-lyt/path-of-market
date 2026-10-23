"""默认运行隔离的真实 HTTP 验收；--live 才调用本地网页与实际模型账户。"""

import argparse
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = "synthetic-key-for-isolated-check-only"
TASK = {"target": "示例公司", "question": "解释研究研发投入需要哪些资料，不提供未经证实的数字。",
        "userStyle": "关注风险与长期增长", "omens": ["opportunity", "abyssal_echoes"],
        "asOfDate": date.today().isoformat()}


def request(url, data=None, timeout=10):
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = Request(url, data=encoded, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


@contextmanager
def isolated_agent(provider_url, **overrides):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, DEEPSEEK_API_KEY=TEST_KEY, DEEPSEEK_BASE_URL=provider_url,
               DEEPSEEK_MODEL="isolated-check", LLM_TIMEOUT_SECONDS="0.6", LLM_MAX_TOKENS="1800")
    env.update(overrides)
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=ROOT / "apps/agent", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("隔离研究服务启动失败")
            try:
                if request(base + "/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("隔离研究服务未就绪")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def isolated_checks():
    state = {"scenario": "ok", "calls": 0, "last": None}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            state["calls"] += 1
            state["last"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            scenario = state["scenario"]
            if scenario.startswith("status-"):
                status = int(scenario.split("-")[1])
                body = {"error": TEST_KEY}
            else:
                status = 200
                content = {"title": "隔离验收分析", "summary": "未检索资料，仅整理研究方法。",
                           "sections": [{"heading": "需要的资料", "content": "需要历年年报和研发口径。"},
                                        {"heading": "后续验证", "content": "读取真实报告后再验证。"}]}
                if scenario == "invented-sources":
                    content["sources"] = ["虚构来源"]
                body = {"choices": [{"finish_reason": "length" if scenario == "truncated" else "stop",
                                     "message": {"content": "not-json" if scenario == "bad-json" else json.dumps(content, ensure_ascii=False)}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180}}
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                if scenario == "slow-headers":
                    time.sleep(1.2)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                if scenario == "slow-body":
                    self.wfile.write(encoded[:1])
                    self.wfile.flush()
                    time.sleep(1.2)
                    self.wfile.write(encoded[1:])
                else:
                    self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider_url = f"http://127.0.0.1:{server.server_port}"
    checks = 0
    try:
        with isolated_agent(provider_url) as base:
            code, report = request(base + "/research/model", TASK)
            assert code == 200 and report["mode"] == "model" and report["isMock"] is False, (code, report.get("error", {}).get("code"))
            assert report["target"] == TASK["target"] and report["asOfDate"] == TASK["asOfDate"]
            assert report["sources"] == [] and report["toolCalls"] == [] and report["evidenceStatus"] == "not_retrieved"
            assert report["run"]["states"] == ["created", "calling_model", "completed"]
            assert report["run"]["usage"]["total_tokens"] == 180
            user_context = json.loads(state["last"]["messages"][1]["content"])
            assert user_context["研究截止日期"] == TASK["asOfDate"]
            assert user_context["研究偏好"] == TASK["userStyle"] and user_context["已检索证据"] == []
            assert state["last"]["response_format"] == {"type": "json_object"}
            assert "tools" not in state["last"]
            checks += 1
            print("PASS: 中文任务、日期、偏好、状态、用量和无证据边界")

            for scenario, expected in (("status-401", "MODEL_AUTH_FAILED"), ("status-402", "MODEL_BALANCE_INSUFFICIENT"),
                                       ("status-429", "MODEL_RATE_LIMITED"), ("status-500", "MODEL_UPSTREAM_ERROR"),
                                       ("bad-json", "MODEL_INVALID_RESPONSE"), ("truncated", "MODEL_INVALID_RESPONSE"),
                                       ("invented-sources", "MODEL_INVALID_RESPONSE"), ("slow-headers", "MODEL_TIMEOUT"),
                                       ("slow-body", "MODEL_TIMEOUT")):
                state["scenario"] = scenario
                started = time.monotonic()
                code, failure = request(base + "/research/model", TASK)
                assert code in (502, 503, 504) and failure["error"]["code"] == expected, (scenario, code)
                assert failure["run"]["status"] == "failed" and TEST_KEY not in json.dumps(failure)
                if scenario.startswith("slow-"):
                    assert time.monotonic() - started < 1.1
                    assert request(base + "/health")[0] == 200
                checks += 1
                print(f"PASS: {scenario} -> {expected}，不泄漏上游正文")

            state["scenario"] = "ok"
            before = state["calls"]
            for invalid in ("", "2026-02-30", 0, True, "2026-10-23T00:00:00", "2026-W01-1"):
                code, _ = request(base + "/research/model", {**TASK, "asOfDate": invalid})
                assert code == 422, invalid
            assert state["calls"] == before
            checks += 1
            print("PASS: 无效日期在调用模型之前拒绝")
            mock_task = {key: value for key, value in TASK.items() if key != "asOfDate"}
            assert request(base + "/research/mock", mock_task)[1]["isMock"] is True
            assert request(base + "/research/model", TASK)[0] == 200
            checks += 1
            print("PASS: 演示接口保留，失败后模型接口可重试")

        with isolated_agent(provider_url, DEEPSEEK_API_KEY="") as base:
            code, failure = request(base + "/research/model", TASK)
            assert code == 503 and failure["error"]["code"] == "MODEL_NOT_CONFIGURED"
            assert failure["run"]["states"] == ["created", "failed"]
            checks += 1
            print("PASS: 缺少密钥有明确提示，无模型请求")
        with isolated_agent(provider_url, DEEPSEEK_BASE_URL="https://invalid.example/?key=private") as base:
            code, failure = request(base + "/research/model", TASK)
            assert code == 503 and failure["error"]["code"] == "MODEL_CONFIG_ERROR"
            checks += 1
            print("PASS: 无效接口配置被拒绝，地址不回传")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    print(f"PASS: {checks} 组隔离 HTTP 检查；未调用实际模型账户")


def live_check(base_url):
    code, body = request(base_url.rstrip("/") + "/api/research/model", TASK, timeout=95)
    if code != 200:
        print(f"FAIL: HTTP {code}, code={body.get('error', {}).get('code', 'UNKNOWN')}。密钥与响应正文未输出。")
        raise SystemExit(1)
    assert body["mode"] == "model" and body["isMock"] is False and body["run"]["status"] == "completed"
    assert body["sources"] == [] and body["toolCalls"] == []
    print(f"PASS: 网页 -> Java -> Python -> 模型真实调用；章节数={len(body['sections'])}，状态=completed，未检索资料")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="实际调用一次模型账户，会消耗 API 额度")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    args = parser.parse_args()
    live_check(args.base_url) if args.live else isolated_checks()
