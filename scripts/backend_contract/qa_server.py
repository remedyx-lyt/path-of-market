"""隔离 HTTP 验收共用的客户端和历史样本。"""
import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid


def start_python(args, *, env, **options):
    executable = sys.executable
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        # 与 multiprocessing 相同，直接管理 venv 的实际解释器。等待它退出后文件锁才已释放。
        env = {**env, "__PYVENV_LAUNCHER__": executable}
        executable = sys._base_executable
    return subprocess.Popen([executable, *args], env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, **options)


def request(base, path, method="GET", body=None):
    req = Request(base + path, method=method, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


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
