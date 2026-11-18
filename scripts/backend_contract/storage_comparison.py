"""在一次性副本上交替运行 Java 与 Python 存储，逐字段比较双向读写结果。"""
from pathlib import Path
import sys
from uuid import uuid4

from backend_contract.scenarios import CHECKPOINTED, INTERRUPTED, JOBS, MEMORY, OLD_FOLLOWUP, OLD_ROOT, SESSIONS, resume_frozen_checkpoint

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/agent"))
from app.storage.memory import MemoryStore
from app.storage.sessions import SessionStore


def java_views(api, runs):
    return {
        "tasks": [api.request("GET", f"{JOBS}/{run}") for run in runs],
        "discussions": [api.request("GET", f"{JOBS}/{run}/discussion") for run in runs],
        "entries": [api.request("GET", f"/internal/sessions/runs/{run}")["entries"] for run in runs],
        "recent": api.request("GET", SESSIONS)["sessions"],
        "memory": api.request("GET", MEMORY),
        "filtered": api.request("GET", MEMORY + f"?query=sample&limit=1&excludeRoot={OLD_ROOT}"),
    }


def python_views(sessions, memory, runs):
    return {
        "tasks": [sessions.snapshot(run) for run in runs],
        "discussions": [sessions.discussion(run) for run in runs],
        "entries": [sessions.entries_for_run(run) for run in runs],
        "recent": sessions.recent(), "memory": memory.snapshot(),
        "filtered": memory.snapshot("sample", 1, OLD_ROOT),
    }


def compare_storage(directory, reference_backend):
    session, run = str(uuid4()), str(uuid4())
    runs = [OLD_ROOT, OLD_FOLLOWUP, INTERRUPTED, CHECKPOINTED, run]
    common = {"sessionId": session, "runId": run, "timestamp": "2026-11-01T00:00:00Z"}
    header = {**common, "type": "session", "id": session, "version": 1,
              "request": {"target": "sample", "question": "先看现金流和负债，列出风险。", "userStyle": "按期比较"}}
    entries = [header, {**common, "type": "event", "id": str(uuid4()), "parentId": None,
                        "data": {"id": "e1", "type": "model_finished", "message": "完成一次取证"}}]
    endpoint = f"/internal/sessions/{session}/entries"
    suggestions = "/internal/research/memory/suggestions"
    old_note = {"runId": run, "text": "优先检查现金流", "quote": "先看现金流", "category": "risk_focus"}
    py_note = {**old_note, "text": "列出负债变化", "quote": "负债"}
    with reference_backend(directory) as api:
        assert api.request("POST", endpoint, body={"entries": entries})["written"] == 2
        note = api.request("POST", suggestions, body=old_note)["note"]
        revision = api.request("GET", MEMORY)["revision"]
        api.request("POST", MEMORY, body={"action": "forget", "revision": revision, "id": note["id"]})
        expected = java_views(api, runs)

    sessions = SessionStore(directory / "sessions")
    memory = MemoryStore(sessions)
    assert python_views(sessions, memory, runs) == expected, "Python 读取 Java 写入的历史或记忆存在差异"
    assert memory.suggest(old_note) == {"status": "already_recorded"}
    assert sessions.append(session, entries) == 0
    final = {**common, "type": "run_state", "id": str(uuid4()), "parentId": entries[-1]["id"],
             "status": "completed", "modelCalls": 2, "usage": {"total_tokens": 120}, "finishedAt": common["timestamp"]}
    assert sessions.append(session, [*entries, final]) == 1
    note = memory.suggest(py_note)["note"]
    memory.edit({"action": "forget", "revision": memory.snapshot()["revision"], "id": note["id"]})
    memory.edit({"action": "save", "category": "research_preference", "text": "检查样本现金流", "revision": memory.snapshot()["revision"]})
    expected = python_views(sessions, memory, runs)
    assert expected["filtered"]["matchedEpisodes"] == 1 and expected["tasks"][-1]["status"] == "completed"

    with reference_backend(directory) as api:
        assert java_views(api, runs) == expected, "Java 读取 Python 写入的历史或记忆存在差异"
        assert api.request("POST", endpoint, body={"entries": [final]})["written"] == 0
        assert api.request("POST", suggestions, body=py_note) == {"status": "already_recorded"}
        resume_frozen_checkpoint(api)
    print("PASS Java → Python → Java，任务、对话版本、原始条目、最近记录与记忆逐字段相等；双向去重与旧检查点接续通过。")
