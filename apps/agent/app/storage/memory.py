"""单用户记忆 v1。编辑按 revision 比较并替换，候选的原话来自相同运行。"""
from datetime import datetime, timezone
from hashlib import md5
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import UUID, uuid4

from app.storage.sessions import SessionStore

CATEGORIES = {"research_preference", "risk_focus", "watch_company"}
THEMES = {
    "现金流": ("现金流", "回款"), "资产负债": ("应收", "负债", "存货", "资产负债"),
    "业务与竞争": ("业务", "竞争", "客户", "行业"), "成长与研发": ("研发", "成长", "营收", "收入", "利润"),
    "风险": ("风险", "保守", "下行", "反方"), "股价与估值": ("股价", "行情", "估值", "回撤"),
}


class MemoryConflict(ValueError):
    """旧版本编辑，或记忆已关闭。"""


class MemoryUnavailable(OSError):
    """记忆文件无法安全读取或保存。"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _text(body, key, maximum):
    value = body.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key}须为文字")
    value = value.strip()
    # Java String.length 以 UTF-16 码元计数，保留含 emoji 的旧输入边界。
    if not value or len(value.encode("utf-16-le")) > 2 * maximum:
        raise ValueError(f"{key}长度应为1至{maximum}")
    return value


def _category(body):
    value = _text(body, "category", 30)
    if value not in CATEGORIES:
        raise ValueError("category无效")
    return value


def _fingerprint(text):
    # Java UUID.nameUUIDFromBytes 对原始 UTF-8 计算，无 namespace 前缀。
    return str(UUID(bytes=md5(text.encode("utf-8"), usedforsecurity=False).digest(), version=3))


def _find_note(notes, note_id):
    for note in notes:
        if note.get("id") == note_id and note.get("status") != "rejected":
            return note
    raise ValueError("记忆条目不存在或已移除")


def _ensure_room(notes):
    if sum(note.get("status") != "rejected" for note in notes) >= 48:
        raise ValueError("最多保留48条偏好与候选，请先整理旧记忆。")


def _history_view(history, query, limit):
    matching = [e for e in history if query in (e["target"] + " " + e["question"]).lower()]
    companies = {}
    for e in history:
        target = e["target"]
        if target not in companies:
            companies[target] = {"target": target, "researchCount": 0, "followupCount": 0,
                                 "lastSeen": e["timestamp"], "latestTaskId": e["rootTaskId"]}
        companies[target]["researchCount" if e["kind"] == "research" else "followupCount"] += 1

    themes = []
    for name, words in THEMES.items():
        hits = [e for e in history[:30] if any(word in e["question"] for word in words)]
        if hits:
            themes.append({"name": name, "count": len(hits), "evidence": hits[:3]})
    return {
        "episodes": matching[:limit], "totalEpisodes": len(history), "matchedEpisodes": len(matching),
        "companies": [c for c in companies.values() if query in c["target"].lower()][:30],
        "companyCount": len(companies), "themes": themes,
        "observationScope": "最近30次成功研究/追问的任务主题（包含默认问题）；仅表示研究涉及，不据此判断持仓、风险承受力或长期偏好。",
    }


class MemoryStore:
    def __init__(self, sessions: SessionStore):
        self.sessions = sessions
        self.path = sessions.directory / "memory" / "user.json"
        self._lock = Lock()

    def _read(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schemaVersion": 1, "revision": 0, "enabled": True, "notes": [], "ignoredTargets": []}
        except (OSError, ValueError) as error:
            raise MemoryUnavailable("记忆文件暂不可读，原文件保留。") from error
        if not (isinstance(state, dict) and type(state.get("schemaVersion")) is int and state["schemaVersion"] == 1
                and type(state.get("revision")) is int and state["revision"] >= 0 and isinstance(state.get("enabled"), bool)
                and isinstance(state.get("notes"), list) and all(isinstance(n, dict) for n in state["notes"])
                and isinstance(state.get("ignoredTargets"), list) and all(isinstance(t, str) for t in state["ignoredTargets"])):
            raise MemoryUnavailable("记忆文件结构无效，原文件保留。")
        return state

    def _write(self, state):
        active = [n for n in state["notes"] if n.get("status") != "rejected"]
        rejected = [n for n in state["notes"] if n.get("status") == "rejected"]
        state.update(notes=active + rejected[-256:], revision=state["revision"] + 1, updatedAt=_now())
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as output:
                temp = Path(output.name)
                json.dump(state, output, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, self.path)
        except OSError as error:
            raise MemoryUnavailable("记忆保存失败，原文件保留。") from error
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def _view(self, state, query="", limit=20, exclude_root=""):
        ignored = set(state["ignoredTargets"])
        history = [e for e in self.sessions.memory_inputs() if e["target"] not in ignored and e["rootTaskId"] != exclude_root]
        return {**state, "notes": [n for n in state["notes"] if n.get("status") != "rejected"],
                **_history_view(history, query.strip().lower(), limit)}

    def snapshot(self, query: str = "", limit: int = 20, exclude_root: str = "") -> dict:
        if len(query.encode("utf-16-le")) > 240:
            raise ValueError("检索词最多120字")
        if exclude_root:
            UUID(exclude_root)
        with self._lock:
            return self._view(self._read(), query, max(1, min(limit, 30)), exclude_root)

    def edit(self, body: dict) -> dict:
        with self._lock:
            state = self._read()
            if not isinstance(body, dict) or type(body.get("revision")) is not int or body["revision"] != state["revision"]:
                raise MemoryConflict("记忆已更新，请刷新后再保存，避免覆盖另一处修改。")
            notes = state["notes"]
            action = _text(body, "action", 30)
            match action:
                case "toggle":
                    if not isinstance(body.get("enabled"), bool):
                        raise ValueError("enabled须为布尔值")
                    state["enabled"] = body["enabled"]
                case "save":
                    text, category = _text(body, "text", 500), _category(body)
                    if str(body.get("id") or "").strip():
                        note = _find_note(notes, body["id"])
                    else:
                        _ensure_room(notes)
                        note = {"id": str(uuid4())}
                        notes.append(note)
                    note.update(text=text, category=category, status="confirmed", updatedAt=_now(), confirmedBy="local_user")
                case "forget":
                    note_id = _text(body, "id", 80)
                    note = _find_note(notes, note_id)
                    fingerprint = _fingerprint(note.get("text", ""))
                    notes.remove(note)
                    notes.append({"id": note_id, "status": "rejected", "fingerprint": fingerprint})
                case "ignore_company" | "restore_company":
                    target = _text(body, "target", 120)
                    ignored = dict.fromkeys(state["ignoredTargets"])
                    if action == "ignore_company":
                        ignored[target] = None
                    else:
                        ignored.pop(target, None)
                    if len(ignored) > 100:
                        raise ValueError("忽略列表最多100个对象")
                    state["ignoredTargets"] = list(ignored)
                case _:
                    raise ValueError("未知记忆操作")
            self._write(state)
            return self._view(state)

    def suggest(self, body: dict) -> dict:
        with self._lock:
            state = self._read()
            if not state["enabled"]:
                raise MemoryConflict("研究记忆已关闭，未保存建议。")
            if not isinstance(body, dict):
                raise ValueError("建议须为对象")
            run = _text(body, "runId", 80)
            UUID(run)
            text, quote, category = _text(body, "text", 500), _text(body, "quote", 500), _category(body)
            source = self.sessions.memory_source(run)
            if source is None:
                raise ValueError("找不到当前运行的真实用户输入")
            if quote not in source:
                raise ValueError("quote须逐字出现在本次用户问题或研究风格中，不能来自报告/模型回复。")
            fingerprint = _fingerprint(text)
            if any(n.get("fingerprint") == fingerprint or n.get("text") == text for n in state["notes"]):
                return {"status": "already_recorded"}
            _ensure_room(state["notes"])
            note = {"id": str(uuid4()), "text": text, "category": category, "status": "suggested",
                    "runId": run, "quote": quote, "updatedAt": _now()}
            state["notes"].append(note)
            self._write(state)
            return {"status": "suggested", "note": note}
