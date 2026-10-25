"""执行检查点与旧 JSONL 接续。会话由 Java 保存；Python 另存可重建的执行状态，不保存密钥。

沿用 Pi 当前 parentId 分支，context_edit 生效；参考 LangGraph 的成功步骤保留与检查点恢复。
旧任务没有检查点时，仅恢复实际落盘的消息、覆盖和已核对数值，不把缓存目录当已读证明。
"""

from copy import deepcopy
import json
import os
from uuid import UUID
from urllib.request import urlopen

from app.core.config import ModelServiceError
from app.services.session_recorder import DEFAULT_URL
from app.tools.documents import write_json

STATE_FIELDS = (
    "notes", "sources", "coverage", "discovered", "web_discovered", "current_period_checked", "required_current", "current_period_gap",
    "market_data", "visual_readings", "extraction_readings", "financial_points", "financial_gaps", "segment_points",
    "business_gaps", "method_usage", "action_counts", "report_candidate", "table_gaps", "wrapup_gaps", "restored_financial",
    "writing_state", "writer_tools_rejected", "report_stage",
    "compaction_state", "compaction_count",
    "history_checked", "required_annual", "history_gap",
)
SET_FIELDS = ("financial_checked", "detail_checked")


def recovery_error(message):
    return ModelServiceError("RESEARCH_NOT_RESUMABLE", message, 409)


def checkpoint_path(tools, task_id):
    return tools.store.root / "run-checkpoints" / f"{UUID(task_id)}.json"


def save_checkpoint(runner):
    state = {name: getattr(runner, name) for name in STATE_FIELDS}
    state.update({name: sorted(getattr(runner, name)) for name in SET_FIELDS})
    write_json(checkpoint_path(runner.tools, runner.job.task_id), {
        "version": 1, "taskId": runner.job.task_id, "sessionId": runner.job.session_id,
        "status": runner.job.status, "model": runner.settings.model, "baseUrl": runner.settings.base_url,
        "request": runner.job.request.model_dump(mode="json", by_alias=True), "state": state,
        "messages": list(runner.messages), "modelCalls": runner.job.model_calls, "usage": runner.job.usage,
        "messageEntryIds": list(getattr(runner.messages, "entry_ids", [])),
    })


def current_message_entries(entries):
    """只走最后节点的父链；不把其他分支/作废草稿混进模型上下文。"""
    nodes = {e["id"]: e for e in entries if e.get("type") != "session" and e.get("id")}
    chain, seen = [], set()
    leaf = entries[-1].get("id") if len(entries) > 1 else None
    while leaf:
        if leaf in seen or leaf not in nodes:
            raise recovery_error("会话父链损坏，不能安全恢复上下文。")
        seen.add(leaf)
        entry = nodes[leaf]
        chain.append(entry)
        leaf = entry.get("parentId")
    chain.reverse()
    removed = {e.get("targetId") for e in chain if e.get("type") == "context_edit"}
    return [e for e in chain if e.get("type") == "message" and e["id"] not in removed]


def current_messages(entries):
    return [entry["message"] for entry in current_message_entries(entries)]


def legacy_recovery(entries, task_id, *, allow_completed=False):
    header = entries[0]
    if header.get("type") != "session" or header.get("runId") != task_id:
        raise recovery_error("会话与请求的任务不一致。")
    latest = next((e for e in reversed(entries) if e.get("type") == "run_state"), {})
    if latest.get("status") == "completed" and not allow_completed:
        raise recovery_error("研究已经完成，无需从未完成位置接续。")
    report = next((e["report"] for e in reversed(entries) if e.get("type") == "report"), None)
    if not report:
        raise recovery_error("旧任务缺少已保存的证据状态，无法安全接续。")
    messages = current_messages(entries)
    if not messages:
        raise recovery_error("会话未保存模型上下文，无法安全接续。")
    sources = {s["sourceId"]: s for s in report.get("sources", [])}
    state = {
        "sources": sources, "coverage": {c["sourceId"]: c for c in report.get("coverage", [])},
        "notes": {}, "discovered": {}, "web_discovered": {}, "current_period_checked": False, "required_current": None,
        "market_data": report.get("marketData"), "method_usage": report.get("methodUsage"),
        "visual_readings": report.get("visualReadings", []), "extraction_readings": report.get("extractionReadings", []),
        "financial_points": [], "segment_points": [], "financial_checked": [], "detail_checked": [],
        "financial_gaps": (report.get("financialData") or {}).get("gaps", []),
        "restored_financial": report.get("financialData"),
        "business_gaps": (report.get("businessData") or {}).get("gaps", []),
    }
    compaction = next((e for e in reversed(entries) if e.get("type") == "compaction"), None)
    if compaction:
        state["compaction_state"] = compaction.get("state")
        state["compaction_count"] = sum(e.get("type") == "compaction" and not e.get("restored") for e in entries)
    draft = next((e.get("writingState") for e in reversed(entries) if e.get("type") == "report_draft"), None)
    if draft:
        state["writing_state"] = draft
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            body = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        data = body.get("data") or {}
        if body.get("status") != "completed":
            continue
        for doc in data.get("documents", []):
            state["discovered"][doc["documentId"]] = doc
        for item in data.get("results", []):
            if isinstance(item, dict) and str(item.get("sourceId", "")).startswith("web-"):
                state["web_discovered"][item["sourceId"]] = item
        query = data.get("currentPeriodQuery")
        if isinstance(query, dict):
            state["current_period_checked"] = bool(query.get("queryComplete"))
            state["required_current"] = query.get("requiredLatestDocument")
        if data.get("sourceId") and data.get("notes"):
            state["notes"][data["sourceId"]] = data["notes"]
    for dataset in (report.get("financialData") or {}).get("datasets", []):
        for row in dataset["rows"]:
            for metric, evidence in row["evidence"].items():
                state["financial_points"].append({
                    **evidence, "metric": metric, "year": row["year"], "period": dataset["id"],
                    "value": row["values"][metric], "publishedAt": sources[evidence["sourceId"]]["publishedAt"],
                })
    for dataset in (report.get("businessData") or {}).get("datasets", []):
        for row in dataset["rows"]:
            state["segment_points"].extend(p for p in row["items"] if not p.get("derived"))
    for sid, coverage in state["coverage"].items():
        if coverage.get("processedCharacters", 0) and not state["notes"].get(sid):
            raise recovery_error("已读覆盖缺少对应阅读笔记，不能冒充上下文已恢复。")
        if coverage.get("textComplete"):
            state["financial_checked"].append(sid)
            state["detail_checked"].append(sid)
    return {
        "version": 1, "taskId": task_id, "sessionId": header["id"], "status": latest.get("status", "failed"),
        "request": header["request"], "state": state, "messages": messages,
        "model": report.get("run", {}).get("model"), "modelCalls": latest.get("modelCalls", 0),
        "usage": latest.get("usage", {}), "legacy": True,
        "messageEntryIds": [e["id"] for e in current_message_entries(entries)],
    }


def load_recovery(tools, task_id, *, allow_completed=False):
    path = checkpoint_path(tools, task_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise recovery_error("执行检查点损坏，未启动新的模型调用。") from None
        if data.get("version") != 1 or data.get("taskId") != task_id:
            raise recovery_error("执行检查点版本或任务标识不匹配。")
        return data
    base = (os.environ.get("SESSION_STORE_URL") or DEFAULT_URL).rstrip("/")
    try:
        with urlopen(f"{base}/runs/{UUID(task_id)}", timeout=10) as response:
            entries = json.load(response)["entries"]
    except (OSError, ValueError, KeyError):
        raise recovery_error("未找到可接续的会话或存储服务不可用。") from None
    return legacy_recovery(entries, task_id, allow_completed=allow_completed)


def restore_runner(runner, recovery):
    for name in STATE_FIELDS:
        if name in recovery["state"]:
            setattr(runner, name, deepcopy(recovery["state"][name]))
    for name in SET_FIELDS:
        setattr(runner, name, set(recovery["state"].get(name, [])))
    runner.job.sources = list(runner.sources.values())
    runner.job.coverage = list(runner.coverage.values())
    # 完整消息和证据继续使用；新一次尝试的调用/时间预算重新计量，旧用量留在旧报告及关联字段中。
    runner.job.emit("run_resumed", "从已保存的阅读与证据继续，成功步骤不重做", parentTaskId=recovery["taskId"],
                    previousModelCalls=recovery.get("modelCalls", 0), restoredSources=len(runner.sources))


def pending_calls(messages):
    """最后一个 assistant 的工具请求可能只执行了一部分；只返回缺少结果的调用。"""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "assistant":
            answered = {m.get("tool_call_id") for m in messages[index + 1:] if m.get("role") == "tool"}
            return [c for c in message.get("tool_calls", []) if c["id"] not in answered]
    return []
