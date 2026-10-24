"""M2-1 会话持久化：真实 HTTP 验收 Java SessionStore（追加、去重、残行、还原、列表、重启后索引）。不连接真实模型。

用法：先构建 apps/server（scripts/start-server.ps1 或 mvnw package），再运行本脚本。临时会话目录在 .runtime/qa/sessions。
"""

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
import uuid

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / ".runtime/qa/sessions"


def request(base, path, method="GET", body=None):
    req = Request(base + path, method=method, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


class Python(BaseHTTPRequestHandler):
    """假的 Python 研究服务：任何任务都“已不在内存里”（模拟 Python 重启）。"""

    def log_message(self, *_):
        pass

    def do_GET(self):
        encoded = json.dumps({"error": {"code": "RESEARCH_NOT_FOUND", "message": "x"}}).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def start_java(port, provider_port):
    java = shutil.which("java")
    if not java:
        raise SystemExit("需要 JDK java。")
    log = (FOLDER / "java.log").open("ab")
    process = subprocess.Popen(
        [java, "-Dfile.encoding=UTF-8", "-jar", str(ROOT / "apps/server/target/path-of-market-server.jar"), f"--server.port={port}",
         f"--agent.base-url=http://127.0.0.1:{provider_port}", f"--sessions.dir={FOLDER / 'store'}"],
        cwd=ROOT / "apps/server", stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        if process.poll() is not None:
            raise RuntimeError("临时 Java 未能启动，见 .runtime/qa/sessions/java.log")
        try:
            if request(base, "/api/health")[0] == 200:
                return process, base, log
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("临时 Java 启动超时。")


def stop_java(process, log):
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log.close()


def entries_for(session, run, *, finished=True):
    chain, parent = [], None
    def add(kind, **fields):
        nonlocal parent
        entry = {"type": kind, "id": str(uuid.uuid4()), "parentId": parent, "timestamp": "2026-10-24T00:00:00Z",
                 "sessionId": session, "runId": run, **fields}
        chain.append(entry)
        parent = entry["id"]
    header = {"type": "session", "version": 1, "id": session, "timestamp": "2026-10-24T00:00:00Z", "sessionId": session,
              "runId": run, "request": {"target": "中际旭创", "question": "研究经营变化"}}
    add("event", data={"id": "e1", "parentId": None, "type": "phase_changed", "phase": "research", "message": "阶段：取证", "timestamp": "t"})
    add("message", message={"role": "assistant", "content": "{\"ready\":true}"})
    add("report_draft", writingState={"outline": {"title": "分节草稿"}, "sections": [], "metadata": None})
    add("event", data={"id": "e2", "parentId": "e1", "type": "model_finished", "message": "撰写正文完成", "timestamp": "t", "purpose": "撰写正文"})
    if finished:
        add("report", reportId=run, reportVersion=1, report={"mode": "agent", "title": "测试报告", "sections": [], "coverage": [], "sources": []})
        add("run_state", status="completed", modelCalls=3, usage={"total_tokens": 100}, error=None, finishedAt="2026-10-24T00:10:00Z")
    return [header] + chain


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not FOLDER.resolve().is_relative_to((ROOT / ".runtime/qa").resolve()):
        raise SystemExit("拒绝清理测试目录外的路径")
    shutil.rmtree(FOLDER, ignore_errors=True)
    FOLDER.mkdir(parents=True)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Python)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    session, run = str(uuid.uuid4()), str(uuid.uuid4())
    broken_session, broken_run = str(uuid.uuid4()), str(uuid.uuid4())
    checks = []

    def check(name, condition, detail=""):
        assert condition, f"{name} 未通过 {detail}"
        checks.append(name)
        print("PASS", name, flush=True)

    process, base, log = start_java(port, provider.server_port)
    try:
        entries = entries_for(session, run)
        status, body = request(base, f"/internal/sessions/{session}/entries", "POST", {"entries": entries})
        check("写入整批条目", status == 200 and body["written"] == len(entries), body)
        status, body = request(base, f"/internal/sessions/{session}/entries", "POST", {"entries": entries})
        check("重复提交按 id 去重", status == 200 and body["written"] == 0, body)
        status, body = request(base, f"/internal/sessions/{uuid.uuid4()}/entries", "POST", {"entries": entries[1:2]})
        check("新会话首条须为会话头", status == 400, body)
        status, _ = request(base, "/internal/sessions/not-a-uuid/entries", "POST", {"entries": entries[:1]})
        check("会话 id 校验", status == 400)
        file = FOLDER / "store" / f"{session}.jsonl"
        lines = file.read_text(encoding="utf-8").splitlines()
        check("JSONL 一行一条且首行是会话头", len(lines) == len(entries) and json.loads(lines[0])["type"] == "session")
        status, body = request(base, f"/internal/sessions/runs/{run}")
        check("接续服务可读取原会话完整上下文", status == 200 and body["entries"] == entries, body)
        status, _ = request(base, f"/internal/sessions/runs/{uuid.uuid4()}")
        check("接续读取未知任务返回404", status == 404)

        # 一批中后面的条目无效时，之前的合法条目不能提前占用“已落盘 id”，否则重试会被错误去重，整批丢失。
        retry_session, retry_run = str(uuid.uuid4()), str(uuid.uuid4())
        retry_entries = entries_for(retry_session, retry_run)
        status, _ = request(base, f"/internal/sessions/{retry_session}/entries", "POST", {"entries": retry_entries[:2] + [{"id": "bad", "type": "invalid"}]})
        check("含无效条目的整批拒绝", status == 400)
        status, body = request(base, f"/internal/sessions/{retry_session}/entries", "POST", {"entries": retry_entries})
        restored = (FOLDER / "store" / f"{retry_session}.jsonl").read_text(encoding="utf-8").splitlines()
        check("拒绝后的合法重试不丢行", status == 200 and body["written"] == len(retry_entries)
              and len(restored) == len(retry_entries) and json.loads(restored[0])["type"] == "session", body)

        status, snap = request(base, f"/api/research/jobs/{run}")
        check("Python 无此任务时从 JSONL 还原快照", status == 200 and snap["status"] == "completed" and snap["report"]["title"] == "测试报告"
              and len(snap["events"]) == 2 and snap["phase"] == "research" and snap["modelCalls"] == 3 and snap["storage"] == "session_jsonl", snap)

        partial = entries_for(broken_session, broken_run, finished=False)
        request(base, f"/internal/sessions/{broken_session}/entries", "POST", {"entries": partial[:2]})
        broken = FOLDER / "store" / f"{broken_session}.jsonl"
        with broken.open("a", encoding="utf-8") as handle:
            handle.write('{"type":"event","id":"half-written')  # 模拟写到一半崩溃的残行
        status, body = request(base, f"/internal/sessions/{broken_session}/entries", "POST", {"entries": partial[2:]})
        check("残行之后继续追加", status == 200 and body["written"] == len(partial) - 2, body)
        status, snap = request(base, f"/api/research/jobs/{broken_run}")
        check("中途中断的运行如实标为中断", status == 200 and snap["status"] == "failed" and snap["error"]["code"] == "RESEARCH_INTERRUPTED"
              and len(snap["events"]) == 2, snap)

        status, body = request(base, "/api/research/sessions")
        listed = {s["runId"]: s for s in body["sessions"]}
        check("最近研究列表", status == 200 and listed[run]["title"] == "测试报告" and listed[run]["status"] == "completed"
              and listed[broken_run]["status"] == "failed", body)
        status, _ = request(base, f"/api/research/jobs/{uuid.uuid4()}")
        check("未记录的任务仍返回 404", status == 404)
    finally:
        stop_java(process, log)

    process, base, log = start_java(port, provider.server_port)
    try:
        status, snap = request(base, f"/api/research/jobs/{run}")
        check("Java 重启后重建索引并还原", status == 200 and snap["report"]["title"] == "测试报告", snap)
    finally:
        stop_java(process, log)
        provider.shutdown()
        provider.server_close()
    (FOLDER / "summary.json").write_text(json.dumps({"checks": checks, "passed": len(checks)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS {len(checks)} session store checks; no real model calls")
