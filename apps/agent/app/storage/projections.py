"""从 v1 会话条目还原网页与研究记忆需要的视图。"""
from collections.abc import Iterable


def task_snapshot(entries: list[dict], run_id: str) -> dict:
    header = entries[0]
    events = []
    state = report = followup = parent = None
    phase = "queued"
    calls = 0
    for row in entries:
        if row.get("runId") != run_id:
            continue
        match row.get("type"):
            case "event":
                event = row.get("data")
                if isinstance(event, dict):
                    events.append(event)
                    if event.get("type") == "phase_changed":
                        phase = event.get("phase", phase)
                    if event.get("type") == "model_finished":
                        calls += 1
            case "run_state":
                state = row
            case "report":
                report = row.get("report")
            case "chat_turn":
                followup = row
            case "continuation":
                parent = row.get("parentTaskId")

    if not isinstance(report, dict):
        report = None
    result = {
        "taskId": run_id, "parentTaskId": parent, "followup": followup,
        "sessionId": header["id"], "target": header.get("request", {}).get("target", ""),
        "startedAt": header.get("timestamp", ""), "phase": phase, "events": events,
        "progress": events[-1].get("message", "已记录") if events else "已记录",
        "storage": "session_jsonl", "report": report,
    }
    for key in ("coverage", "sources", "toolCalls"):
        value = (report or {}).get(key)
        result[key] = value if isinstance(value, list) else []
    if state is None:
        return {**result, "status": "failed", "modelCalls": calls, "usage": {},
                "error": {"code": "RESEARCH_INTERRUPTED", "message": "研究在完成前中断（服务重启或异常退出），以下是已记录的过程。"}}
    return {**result, "status": state.get("status", "failed"), "finishedAt": state.get("finishedAt", ""),
            "modelCalls": state.get("modelCalls", calls),
            "usage": state["usage"] if isinstance(state.get("usage"), dict) else {},
            "error": state["error"] if isinstance(state.get("error"), dict) else None}


def discussion(entries: list[dict]) -> dict:
    versions, turns = [], []
    ends = {e["runId"]: e for e in entries if e.get("type") == "chat_turn" and e.get("runId")}
    for e in entries:
        if e.get("type") == "report":
            fields = ("id", "runId", "timestamp", "reportVersion", "parentVersionId", "changedSections", "summaryChanged", "report")
            versions.append({k: e[k] for k in fields if k in e})
        elif e.get("type") == "followup":
            fields = ("runId", "timestamp", "requestId", "parentTurnId", "baseVersionId", "userMessage", "action")
            turn = {k: e.get(k) for k in fields}
            end = ends.get(e.get("runId"))
            if end is None:
                turn.update(id=e["id"], status="pending", answer="", citations=[])
            else:
                turn.update({k: end[k] for k in ("id", "answer", "citations", "sources", "status", "error", "versionId") if k in end})
            turns.append(turn)
    return {"sessionId": entries[0]["id"], "rootTaskId": entries[0]["runId"], "versions": versions, "turns": turns}


def session_summary(header: dict, rows: Iterable[dict]) -> dict:
    request = header.get("request", {})
    result = {"sessionId": header["id"], "runId": header.get("runId", ""), "createdAt": header.get("timestamp", ""),
              "target": request.get("target", ""), "question": request.get("question", ""), "status": "failed"}
    for row in rows:
        if row.get("type") == "run_state" and row.get("runId") == result["runId"]:
            result["status"] = row.get("status", "failed")
        elif row.get("type") == "report":
            result["title"] = (row.get("report") or {}).get("title", "")
    return result


def memory_episodes(rows: list[dict]) -> list[dict]:
    header = rows[0]
    request = header.get("request", {})
    root = header.get("runId", "")
    completed = any(e.get("type") == "run_state" and e.get("runId") == root and e.get("status") == "completed" for e in rows)
    episodes = []
    for e in rows:
        if e is header and completed:
            kind, question = "research", request.get("question", "")
        elif e.get("type") == "chat_turn" and e.get("status") == "completed":
            kind, question = "followup", e.get("userMessage", "")
        else:
            continue
        episodes.append({"runId": e.get("runId", ""), "rootTaskId": root, "nodeId": e.get("id", ""),
                         "target": request.get("target", ""), "question": question, "kind": kind,
                         "timestamp": e.get("timestamp", "")})
    return episodes
