"""追加式 JSONL。读写使用相同的会话锁；索引只包含已经写入的条目。"""
import json
import os
from pathlib import Path
import re
from threading import Lock

from app.storage import projections

SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
ENTRY_TYPES = {"session", "event", "message", "context_edit", "report", "run_state", "continuation",
               "report_draft", "followup", "chat_turn", "compaction"}
MEMORY_TYPES = {"session", "run_state", "chat_turn", "followup"}
MEMORY_LINE = re.compile(rb'"type"\s*:\s*"(?:session|run_state|chat_turn|followup)"')


def _rows(path: Path, *, memory_only=False):
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return
    with stream:
        for line in stream:
            # 用户记忆只需少量条目，避免反序列化整份报告与工具正文。
            if memory_only and not MEMORY_LINE.search(line) and b"\\u" not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:  # 包括截断 UTF-8 造成的 UnicodeDecodeError。
                continue
            if isinstance(entry, dict) and (not memory_only or isinstance(entry.get("type"), str) and entry["type"] in MEMORY_TYPES):
                yield entry


def _append_bytes(path: Path, payload: bytes):
    with path.open("a+b") as stream:
        if payload and stream.tell():
            stream.seek(-1, os.SEEK_END)
            add_newline = stream.read(1) != b"\n"
            stream.seek(0, os.SEEK_END)
            if add_newline:
                stream.write(b"\n")
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _new_entries(session_id, entries, known):
    batch = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str) or entry["type"] not in ENTRY_TYPES:
            raise ValueError("条目须为带 id 与已知 type 的对象")
        key = entry.get("id")
        if not isinstance(key, str) or not key or len(key.encode("utf-16-le")) // 2 > 80:
            raise ValueError("条目须为带 id 与已知 type 的对象")
        if not (known or batch) and entry["type"] != "session":
            raise ValueError("新会话的第一条必须是会话头")
        if entry["type"] == "session" and key != session_id:
            raise ValueError("会话头 id 与会话不一致")
        if key not in known:
            batch.setdefault(key, entry)
    return batch


class SessionStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._guard = Lock()
        self._locks = {}
        self._by_run = {}
        self._ids = {}  # 只缓存有追加操作的会话。
        for path in sorted(self.directory.glob("*.jsonl")):
            if SESSION_ID.fullmatch(path.stem):
                try:
                    self._index(path)
                except OSError:
                    continue  # 单个不可读的历史文件不阻止打开其他研究。

    def _index(self, path: Path, *, collect_ids=False):
        ids, runs = set(), set()
        for row in _rows(path):
            if isinstance(row.get("runId"), str) and row["runId"]:
                runs.add(row["runId"])
            if collect_ids and isinstance(row.get("id"), str):
                ids.add(row["id"])
        with self._guard:
            self._by_run.update(dict.fromkeys(runs, path.stem))
        return ids

    def _lock(self, session_id):
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise ValueError("会话 id 无效")
        with self._guard:
            return self._locks.setdefault(session_id, Lock())

    def _sessions(self):
        with self._guard:
            return sorted(set(self._by_run.values()))

    def session_for_run(self, run_id: str) -> str | None:
        with self._guard:
            return self._by_run.get(run_id)

    def append(self, session_id: str, entries: list[dict]) -> int:
        if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
            raise ValueError("entries 须为 1 至 500 条的数组。")
        with self._lock(session_id):
            path = self.directory / f"{session_id}.jsonl"
            known = self._ids.get(session_id)
            cold = known is None
            if cold:
                known = self._index(path, collect_ids=True)
            batch = _new_entries(session_id, entries, known)
            # 先校验并编码整批。若前次 fsync 失败，即使所有行都可见也要重新刷盘再确认。
            if batch or cold:
                payload = b"".join(json.dumps(e, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
                                   for e in batch.values())
                try:
                    _append_bytes(path, payload)
                except OSError:
                    self._ids.pop(session_id, None)
                    raise
                known.update(batch)
                self._ids[session_id] = known
                with self._guard:
                    self._by_run.update({e["runId"]: session_id for e in batch.values() if isinstance(e.get("runId"), str) and e["runId"]})
            return len(batch)

    def load(self, session_id: str, *, memory_only=False) -> list[dict] | None:
        with self._lock(session_id):
            entries = list(_rows(self.directory / f"{session_id}.jsonl", memory_only=memory_only))
        return entries if entries and entries[0].get("type") == "session" else None

    def entries_for_run(self, run_id: str) -> list[dict] | None:
        session = self.session_for_run(run_id)
        return self.load(session) if session else None

    def snapshot(self, run_id: str) -> dict | None:
        entries = self.entries_for_run(run_id)
        return projections.task_snapshot(entries, run_id) if entries else None

    def discussion(self, run_id: str) -> dict | None:
        entries = self.entries_for_run(run_id)
        return projections.discussion(entries) if entries else None

    def recent(self, limit: int = 20) -> list[dict]:
        summaries = []
        for session in self._sessions():
            with self._lock(session):
                rows = _rows(self.directory / f"{session}.jsonl")
                header = next(rows, {})
                if header.get("type") == "session":
                    summaries.append(projections.session_summary(header, rows))
        summaries.sort(key=lambda s: s["createdAt"], reverse=True)
        return summaries[:max(1, min(limit, 100))]

    def memory_inputs(self) -> list[dict]:
        episodes = []
        for session in self._sessions():
            if entries := self._memory_entries(session):
                episodes.extend(projections.memory_episodes(entries))
        return sorted(episodes, key=lambda e: e["timestamp"], reverse=True)

    def memory_source(self, run_id: str) -> str | None:
        session = self.session_for_run(run_id)
        if not session or not (entries := self._memory_entries(session)):
            return None
        header = entries[0]
        if run_id == header.get("runId"):
            request = header.get("request", {})
            return request.get("question", "") + "\n" + request.get("userStyle", "")
        return next((e.get("userMessage", "") for e in entries if e.get("runId") == run_id and e.get("type") == "followup"), None)

    def _memory_entries(self, session_id):
        try:
            return self.load(session_id, memory_only=True)
        except OSError:
            # 记忆是可选的视图，一个不可读的会话不影响其他会话的偏好与经历。
            return None
