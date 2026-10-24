"""离线真实 HTTP 验收 Java 异步任务代理；不连接真实模型。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TASK = "11111111-1111-4111-8111-111111111111"
state = {"mode": "queued", "method": None, "path": None}


def request(base, path, method="GET", body=None):
    req = Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as response: return response.status, json.load(response)
    except HTTPError as error:
        with error: return error.code, json.load(error)


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self): self.respond()
    def do_GET(self): self.respond()
    def do_DELETE(self): self.respond()
    def respond(self):
        state["method"], state["path"] = self.command, self.path
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        mode = state["mode"]
        body = {"taskId": TASK, "sessionId": TASK, "status": mode if mode in {"queued", "running", "cancelled"} else "completed",
                "progress": "fixture", "events": [], "toolCalls": [], "sources": [], "coverage": [], "modelCalls": 0,
                "usage": {}, "report": None, "error": None}
        status = 202 if self.command == "POST" else 200
        if self.path.endswith("/continue"):
            body["parentTaskId"] = TASK if mode != "wrong-parent" else "wrong-parent"
            body["taskId"] = "22222222-2222-4222-8222-222222222222"
        if mode == "complete":
            body["report"] = {"mode": "agent", "isMock": False, "title": "报告", "summary": "完成",
                "sections": [{"heading": "一", "content": "内容", "citations": []}, {"heading": "二", "content": "内容", "citations": []}],
                "sources": [], "coverage": []}
        if mode == "wrong-id": body["taskId"] = "22222222-2222-4222-8222-222222222222"
        if mode == "bad-state": body["status"] = "imagined"
        if mode == "bad-report": body["report"] = {"mode": "agent", "isMock": True}
        if mode in {"busy", "not-found", "unknown-error", "not-resumable"}:
            status = {"busy": 409, "not-found": 404, "unknown-error": 503, "not-resumable": 409}[mode]
            body = {"error": {"code": {"busy": "RESEARCH_BUSY", "not-found": "RESEARCH_NOT_FOUND", "unknown-error": "PRIVATE_CODE", "not-resumable": "RESEARCH_NOT_RESUMABLE"}[mode],
                              "message": "private-fixture-body-must-not-leak"}}
        if mode == "validation":
            status = 422
            body = {"detail": [{"loc": ["body", "asOfDate"], "msg": "fixture validation", "type": "value_error"}]}
        if mode == "slow": time.sleep(1.2)
        encoded = b"not-json" if mode == "bad-json" else json.dumps(body).encode()
        try:
            self.send_response(status); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider); provider.daemon_threads = True
    thread = threading.Thread(target=provider.serve_forever, daemon=True); thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    java = shutil.which("java")
    if not java: raise SystemExit("需要 JDK java。")
    folder = ROOT / ".runtime/qa/m1-3-job-bridge"
    folder.mkdir(parents=True, exist_ok=True)
    log = (folder / "java.log").open("wb")
    process = subprocess.Popen([java, "-Dfile.encoding=UTF-8", "-jar", str(ROOT / "apps/server/target/path-of-market-server.jar"),
        f"--server.port={port}", f"--agent.base-url=http://127.0.0.1:{provider.server_port}", "--agent.request-timeout=500ms"],
        cwd=ROOT / "apps/server", stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base, checks = f"http://127.0.0.1:{port}", []
    try:
        for _ in range(150):
            if process.poll() is not None: raise RuntimeError("临时 Java 未能启动，见忽略目录日志。")
            try:
                if request(base, "/api/health")[0] == 200: break
            except (URLError, TimeoutError): time.sleep(0.2)
        else: raise RuntimeError("临时 Java 启动超时。")
        for mode, method, path, expected in [
            ("queued", "POST", "", 202), ("running", "GET", "/" + TASK, 200),
            ("cancelled", "DELETE", "/" + TASK, 200), ("complete", "GET", "/" + TASK, 200),
            ("wrong-id", "GET", "/" + TASK, 502), ("bad-state", "GET", "/" + TASK, 502),
            ("bad-report", "GET", "/" + TASK, 502), ("bad-json", "GET", "/" + TASK, 502),
            ("busy", "POST", "", 409), ("not-found", "GET", "/" + TASK, 404),
            ("unknown-error", "GET", "/" + TASK, 502), ("validation", "POST", "", 422),
            ("slow", "GET", "/" + TASK, 504),
            ("queued", "POST", "/" + TASK + "/continue", 202),
            ("wrong-parent", "POST", "/" + TASK + "/continue", 502),
            ("not-resumable", "POST", "/" + TASK + "/continue", 409)]:
            state["mode"] = mode
            status, body = request(base, "/api/research/jobs" + path, method, {"target": "fixture"} if method == "POST" else None)
            assert status == expected, (mode, status, body)
            assert "private-fixture" not in json.dumps(body)
            assert state["method"] == method
            checks.append(mode); print("PASS", mode, status, flush=True)
        (folder / "summary.json").write_text(json.dumps({"checks": checks, "passed": len(checks)}, indent=2), encoding="utf-8")
        print(f"PASS {len(checks)} job bridge cases; no real model calls")
    finally:
        process.terminate()
        try: process.wait(timeout=8)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        log.close(); provider.shutdown(); provider.server_close(); thread.join(timeout=2)
