"""实际 HTTP 验证 Java → Python；--check-errors 另启动临时 Java 和本地故障模拟服务。"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MISSING = object()
HTTP_COUNT = 0
EXAMPLE = {
    "target": "示例公司",
    "question": "如何研究它的研发投入变化？",
    "userStyle": "关注长期增长和风险验证",
    "omens": ["opportunity", "abyssal_echoes"],
}


def request(base_url, path, payload=MISSING, *, raw=None, method=None, content_type="application/json"):
    global HTTP_COUNT
    data = raw
    if payload is not MISSING:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = content_type + "; charset=utf-8"
    http_request = Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    HTTP_COUNT += 1
    try:
        with urlopen(http_request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def check_bridge(server_url, agent_url):
    start_count = HTTP_COUNT
    status, body = request(server_url, "/api/health")
    assert status == 200 and body == {"status": "ok", "service": "server"}

    examples = [
        ("Chinese request", EXAMPLE),
        ("trimmed input and defaults", {"target": "  示例公司  ", "question": "  研究问题  "}),
        ("all four omens", {**EXAMPLE, "omens": ["exalted", "ancient", "opportunity", "abyssal_echoes"]}),
        ("Unicode code-point boundary", {**EXAMPLE, "target": "🚀" * 120}),
    ]
    for label, payload in examples:
        status, report = request(server_url, "/api/research/mock", payload)
        direct_status, direct_report = request(agent_url, "/research/mock", payload)
        assert status == direct_status == 200 and report == direct_report, label
        assert report["mode"] == "mock" and report["isMock"] is True
        assert report["sections"] and report["sources"] == report["toolCalls"] == []
        assert report["target"] == payload["target"].strip()
        assert report["question"] == payload["question"].strip()
        assert report["userStyle"] == payload.get("userStyle", "").strip()
        assert report["omens"] == payload.get("omens", [])
        print(f"PASS real Python round trip: {label}")

    invalid_requests = [
        ("empty target", {**EXAMPLE, "target": ""}),
        ("blank target", {**EXAMPLE, "target": " \t\n "}),
        ("empty question", {**EXAMPLE, "question": ""}),
        ("blank question", {**EXAMPLE, "question": " \n "}),
        ("missing question", {"target": "示例公司"}),
        ("wrong target type", {**EXAMPLE, "target": 123}),
        ("wrong question type", {**EXAMPLE, "question": False}),
        ("wrong preference type", {**EXAMPLE, "userStyle": ["growth"]}),
        ("unknown omen", {**EXAMPLE, "omens": ["unknown"]}),
        ("wrong omens type", {**EXAMPLE, "omens": "opportunity"}),
        ("target too long", {**EXAMPLE, "target": "a" * 121}),
        ("question too long", {**EXAMPLE, "question": "a" * 2001}),
        ("preference too long", {**EXAMPLE, "userStyle": "a" * 501}),
        ("too many omens", {**EXAMPLE, "omens": ["exalted"] * 5}),
        ("unknown field", {**EXAMPLE, "unexpected": "value"}),
        ("null field", {**EXAMPLE, "target": None}),
        ("array body", [EXAMPLE]),
        ("null body", None),
    ]
    for label, invalid in invalid_requests:
        status, error = request(server_url, "/api/research/mock", invalid)
        assert status == 422 and isinstance(error["detail"], list) and error["detail"], label
        print(f"PASS Python validation forwarded: {label}")

    invalid = {**EXAMPLE, "target": 123}
    status, error = request(server_url, "/api/research/mock", invalid)
    direct_status, direct_error = request(agent_url, "/research/mock", invalid)
    assert status == direct_status == 422 and error == direct_error
    print("PASS validation detail preserved")

    for raw in (b'{"target":', b""):
        status, error = request(server_url, "/api/research/mock", raw=raw, method="POST")
        assert status == 400 and error["error"]["code"] == "INVALID_JSON"
    status, _ = request(server_url, "/api/research/mock", EXAMPLE, content_type="text/plain")
    assert status == 415
    status, _ = request(server_url, "/api/research/mock", method="GET")
    assert status == 405
    print("PASS malformed/empty JSON, media type and HTTP method")
    print(f"M0-3 real-service checks passed ({HTTP_COUNT - start_count} HTTP requests).")


class FixtureHandler(BaseHTTPRequestHandler):
    """仅用于故障验收，所有正常结果明确标记为 mock。"""

    def log_message(self, *_):
        pass

    def do_POST(self):
        mode = self.server.mode
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if mode == "disconnect":
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        report = {
            "mode": "mock", "isMock": True,
            "target": payload["target"], "question": payload["question"],
            "userStyle": payload.get("userStyle", ""), "omens": payload.get("omens", []),
            "title": "故障验收演示", "summary": "本地测试数据",
            "sections": [{"heading": "测试", "content": "仅用于接口故障验收"}],
            "sources": [], "toolCalls": [],
        }
        status = 200
        body = report
        if mode == "upstream-error":
            status, body = 500, {"internal": "do-not-forward-this-fixture-detail"}
        elif mode == "redirect":
            status, body = 302, {"detail": "unexpected redirect"}
        elif mode == "invalid-report":
            body = {**report, "isMock": False}
        elif mode == "invalid-validation":
            status, body = 422, {"detail": "invalid format"}
        elif mode == "validation":
            status, body = 422, {"detail": [{"loc": ["body", "target"], "msg": "fixture validation", "type": "fixture"}]}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if mode == "non-json":
            data = b"<html>unexpected response</html>"
        if mode == "slow-headers":
            time.sleep(1)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            if mode == "redirect":
                self.send_header("Location", "/research/mock")
            self.end_headers()
            if mode == "slow-body":
                self.wfile.write(data[:10])
                self.wfile.flush()
                time.sleep(1)
                self.wfile.write(data[10:])
            else:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def check_errors(java_command=None):
    project = Path(__file__).resolve().parents[1]
    jar = project / "apps/server/target/path-of-market-server.jar"
    if not jar.is_file():
        raise RuntimeError("先运行 start-server.ps1 或 Maven package 生成 JAR。")
    if java_command is None:
        java_home = os.environ.get("JAVA_HOME")
        java_command = str(Path(java_home) / "bin/java.exe") if os.name == "nt" and java_home else shutil.which("java")
    if not java_command:
        raise RuntimeError("没有找到 Java，请检查 JDK 安装。")

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    fixture.daemon_threads = True
    fixture.mode = "normal"
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        java_port = port_probe.getsockname()[1]
    server_url = f"http://127.0.0.1:{java_port}"
    run_directory = jar.parent / "bridge-checks" / str(time.time_ns())
    run_directory.mkdir(parents=True)
    fixture_open = True
    process = None
    start_count = HTTP_COUNT
    try:
        with (run_directory / "java.log").open("wb") as log:
            process = subprocess.Popen(
                [java_command, "-Dfile.encoding=UTF-8", "-jar", str(jar),
                 f"--server.port={java_port}", f"--agent.base-url=http://127.0.0.1:{fixture.server_port}",
                 "--agent.connect-timeout=300ms", "--agent.request-timeout=500ms"],
                cwd=project / "apps/server", stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"临时 Java 启动失败，日志：{run_directory / 'java.log'}")
                try:
                    with urlopen(server_url + "/api/health", timeout=1) as response:
                        assert json.load(response)["status"] == "ok"
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("临时 Java 启动超时。")
                    time.sleep(0.2)

            cases = [
                ("upstream-error", 502, "AGENT_ERROR"),
                ("redirect", 502, "AGENT_ERROR"),
                ("non-json", 502, "AGENT_INVALID_RESPONSE"),
                ("invalid-report", 502, "AGENT_INVALID_RESPONSE"),
                ("invalid-validation", 502, "AGENT_INVALID_RESPONSE"),
                ("slow-headers", 504, "AGENT_TIMEOUT"),
                ("slow-body", 504, "AGENT_TIMEOUT"),
                ("disconnect", 503, "AGENT_UNAVAILABLE"),
            ]
            for mode, expected_status, expected_code in cases:
                fixture.mode = mode
                started = time.monotonic()
                status, body = request(server_url, "/api/research/mock", EXAMPLE)
                elapsed = time.monotonic() - started
                assert status == expected_status and body["error"]["code"] == expected_code, (mode, status, body)
                assert "do-not-forward-this-fixture-detail" not in json.dumps(body)
                if mode.startswith("slow-"):
                    assert elapsed < 0.9, f"Timeout not enforced: {mode}, {elapsed}"
                print(f"PASS isolated failure: {mode} -> {status} {expected_code}")

            fixture.mode = "validation"
            status, body = request(server_url, "/api/research/mock", EXAMPLE)
            assert status == 422 and body["detail"][0]["msg"] == "fixture validation"
            fixture.mode = "normal"
            status, body = request(server_url, "/api/research/mock", EXAMPLE)
            assert status == 200 and body["target"] == EXAMPLE["target"] and body["isMock"] is True
            print("PASS validation forwarding and recovery after failures")

            fixture.shutdown()
            fixture.server_close()
            fixture_open = False
            status, body = request(server_url, "/api/research/mock", EXAMPLE)
            assert status == 503 and body["error"]["code"] == "AGENT_UNAVAILABLE"
            status, body = request(server_url, "/api/health")
            assert status == 200 and body == {"status": "ok", "service": "server"}
            print("PASS connection refused and independent Java health")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if fixture_open:
            fixture.shutdown()
            fixture.server_close()
        fixture_thread.join(timeout=2)
    print(f"M0-3 isolated error checks passed ({HTTP_COUNT - start_count} HTTP requests); temporary services stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", default="http://127.0.0.1:8080")
    parser.add_argument("--agent-url", default="http://127.0.0.1:8000")
    parser.add_argument("--check-errors", action="store_true", help="另启动隔离的 Java 与故障服务，验收错误处理")
    parser.add_argument("--java-command", help="故障验收所用 Java 可执行文件")
    args = parser.parse_args()
    check_bridge(args.server_url, args.agent_url)
    if args.check_errors:
        check_errors(args.java_command)
