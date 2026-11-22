"""迁移后的本地存储：固定 v1 样本、故障重试与同进程并发。只使用临时目录。"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))
from app.storage import writer_lease
from app.storage.memory import MemoryConflict, MemoryStore, MemoryUnavailable
from app.storage.sessions import SessionStore

FIXTURES = AGENT.parents[1] / "scripts/backend_contract/fixtures/sessions"


class LocalStorage(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name) / "sessions"
        self.sessions = SessionStore(self.directory)
        self.memory = MemoryStore(self.sessions)
        self.session, self.run = str(uuid4()), str(uuid4())
        self.header = {"type": "session", "version": 1, "id": self.session, "sessionId": self.session, "runId": self.run,
                       "timestamp": "2026-09-10T09:30:00Z", "request": {"target": "样本", "question": "先看现金流和应收", "userStyle": "解释风险"}}
        self.row = {"type": "event", "id": "event-1", "runId": self.run, "parentId": None,
                    "data": {"type": "model_finished", "message": "已取证", "id": "e1"}}
        self.file = self.directory / (self.session + ".jsonl")

    def test_only_one_backend_can_open_a_session_directory(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"SESSIONS_DIR": directory}):
            with writer_lease():
                with self.assertRaises(RuntimeError), writer_lease():
                    pass
            with writer_lease():
                self.assertTrue(Path(directory, ".writer.lock").is_file())

    def test_reads_frozen_files_without_rewriting(self):
        shutil.copytree(FIXTURES, self.directory, dirs_exist_ok=True)
        sessions = SessionStore(self.directory)
        for path in FIXTURES.glob("*.jsonl"):
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            for run in {e["runId"] for e in rows}:
                self.assertEqual(sessions.entries_for_run(run), rows)
                self.assertEqual(sessions.discussion(run)["sessionId"], path.stem)
                self.assertEqual(sessions.snapshot(run)["taskId"], run)
            self.assertEqual((self.directory / path.name).read_bytes(), path.read_bytes())
        self.assertEqual(len(sessions.recent()), 3)
        profile = MemoryStore(sessions).snapshot()
        self.assertEqual(profile["revision"], 3)
        self.assertEqual((self.directory / "memory/user.json").read_bytes(), (FIXTURES / "memory/user.json").read_bytes())

    def test_reject_whole_batch_before_any_write(self):
        for rows in ([], [self.row], [self.header, {"type": "unknown", "id": "bad"}],
                     [{**self.header, "id": self.run}], [self.header] * 501):
            with self.assertRaises(ValueError):
                self.sessions.append(self.session, rows)
        with self.assertRaises(ValueError):
            self.sessions.append("../outside", [self.header])
        self.assertFalse(self.file.exists())
        self.assertEqual(self.sessions.append(self.session, [self.header, self.row, self.row]), 2)
        self.assertEqual(self.sessions.append(self.session, [self.row]), 0)
        self.assertEqual(self.sessions.load(self.session), [self.header, self.row])

    def test_retry_after_partially_written_batch_and_split_utf8(self):
        def interrupted(path, payload):
            header, rest = payload.split(b"\n", 1)
            with path.open("ab") as stream:
                stream.write(header + b"\n" + rest[:rest.index("取".encode()) + 1])
            raise OSError("injected short write")

        with patch("app.storage.sessions._append_bytes", side_effect=interrupted), self.assertRaises(OSError):
            self.sessions.append(self.session, [self.header, self.row])
        original = self.file.read_bytes()
        self.assertEqual(self.sessions.append(self.session, [self.header, self.row]), 1)
        self.assertTrue(self.file.read_bytes().startswith(original + b"\n"))
        reopened = SessionStore(self.directory)
        self.assertEqual(reopened.entries_for_run(self.run), [self.header, self.row])
        self.assertEqual(reopened.snapshot(self.run)["modelCalls"], 1)

    def test_failed_fsync_is_retried_even_when_all_lines_are_visible(self):
        with patch("app.storage.sessions.os.fsync", side_effect=OSError("disk")), self.assertRaises(OSError):
            self.sessions.append(self.session, [self.header, self.row])
        before = self.file.read_bytes()
        with patch("app.storage.sessions.os.fsync") as sync:
            self.assertEqual(self.sessions.append(self.session, [self.header, self.row]), 0)
            sync.assert_called_once()
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.sessions.session_for_run(self.run), self.session)

    def test_concurrent_appends_do_not_interleave_or_duplicate(self):
        barrier = Barrier(6)
        def submit(i):
            barrier.wait()
            return self.sessions.append(self.session, [self.header, self.row, {**self.row, "id": f"thread-{i}"}])
        with ThreadPoolExecutor(max_workers=6) as workers:
            self.assertEqual(sum(workers.map(submit, range(6))), 8)
        rows = self.sessions.load(self.session)
        self.assertEqual(rows[:2], [self.header, self.row])
        self.assertEqual(len({r["id"] for r in rows}), 8)

    def test_only_completed_user_inputs_contribute_to_memory(self):
        child = str(uuid4())
        rows = [
            self.header, self.row,
            {"type": "followup", "id": "pending", "runId": child, "userMessage": "回查客户风险", "parentTurnId": "n1"},
            {"type": "message", "id": "m", "runId": child, "message": {"role": "assistant", "content": "不属于用户的原话"}},
        ]
        self.sessions.append(self.session, rows)
        self.assertEqual(self.sessions.discussion(child)["turns"][0]["status"], "pending")
        self.assertEqual(self.memory.snapshot()["episodes"], [])
        self.sessions.append(self.session, [
            {"type": "run_state", "id": "root-end", "runId": self.run, "status": "completed"},
            {"type": "chat_turn", "id": "turn-end", "runId": child, "userMessage": "回查客户风险", "status": "completed",
             "timestamp": "2026-09-11T00:00:00Z", "answer": "模型答复"},
        ])
        profile = self.memory.snapshot(query="风", limit=1)
        self.assertEqual([e["nodeId"] for e in profile["episodes"]], ["turn-end"])
        self.assertEqual(profile["totalEpisodes"], 2)
        self.assertEqual(profile["themes"][0]["name"], "现金流")
        self.assertEqual(self.memory.snapshot(exclude_root=self.run)["episodes"], [])
        self.assertEqual(self.sessions.memory_source(child), "回查客户风险")
        suggestion = {"runId": child, "text": "观察客户", "category": "risk_focus"}
        for quote in ("不属于用户的原话", "模型答复", "先看现金流"):
            with self.assertRaises(ValueError):
                self.memory.suggest({**suggestion, "quote": quote})
        self.assertEqual(self.memory.suggest({**suggestion, "quote": "客户风险"})["status"], "suggested")

    def test_pending_confirmed_forgotten_and_duplicate(self):
        self.sessions.append(self.session, [self.header])
        self.assertFalse(self.memory.path.exists())
        self.assertEqual(self.memory.snapshot()["revision"], 0)
        self.assertFalse(self.memory.path.exists())
        suggestion = {"runId": self.run, "text": "看现金流", "quote": "先看现金流", "category": "risk_focus"}
        note = self.memory.suggest(suggestion)["note"]
        self.assertEqual(note["status"], "suggested")
        self.assertEqual(self.memory.suggest(suggestion)["status"], "already_recorded")
        saved = self.memory.edit({"revision": 1, "action": "save", "id": note["id"], "category": "risk_focus", "text": "看现金流"})
        self.assertEqual(saved["notes"][0]["status"], "confirmed")
        self.assertEqual(saved["notes"][0]["quote"], suggestion["quote"])
        self.memory.edit({"revision": 2, "action": "forget", "id": note["id"]})
        restarted = MemoryStore(SessionStore(self.directory))
        self.assertEqual(restarted.snapshot()["notes"], [])
        self.assertNotIn("现金流", self.memory.path.read_text(encoding="utf-8"))
        self.assertEqual(restarted.suggest(suggestion)["status"], "already_recorded")
        self.assertEqual(restarted.snapshot()["revision"], 3)

    def test_concurrent_edits_compare_revision_inside_the_lock(self):
        barrier = Barrier(2)
        def edit(name):
            barrier.wait()
            try:
                self.memory.edit({"action": "save", "revision": 0, "text": name, "category": "watch_company"})
            except MemoryConflict:
                return "conflict"
            return "saved"
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(workers.map(edit, ["甲", "乙"]), ["saved", "conflict"])
        saved = self.memory.snapshot()
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(len(saved["notes"]), 1)

    def test_failed_sync_or_replace_preserves_file_and_allows_retry(self):
        self.memory.edit({"revision": 0, "action": "toggle", "enabled": False})
        before = self.memory.path.read_bytes()
        edit = {"revision": 1, "action": "toggle", "enabled": True}
        for failure in ("fsync", "replace"):
            with patch(f"app.storage.memory.os.{failure}", side_effect=OSError("disk")), self.assertRaises(MemoryUnavailable):
                self.memory.edit(edit)
            self.assertEqual(self.memory.path.read_bytes(), before)
            self.assertEqual(list(self.memory.path.parent.iterdir()), [self.memory.path])
        self.assertEqual(self.memory.edit(edit)["revision"], 2)

    def test_corrupt_memory_is_preserved_on_read_and_edit(self):
        self.memory.path.parent.mkdir()
        for body in (b"broken", b'{"schemaVersion":2}', b"\xff"):
            self.memory.path.write_bytes(body)
            with self.assertRaises(MemoryUnavailable):
                self.memory.snapshot()
            with self.assertRaises(MemoryUnavailable):
                self.memory.edit({"revision": 0, "action": "toggle", "enabled": False})
            self.assertEqual(self.memory.path.read_bytes(), body)

    def test_ignore_restore_disabled_and_input_limits(self):
        self.sessions.append(self.session, [self.header, {"type": "run_state", "runId": self.run, "id": "end", "status": "completed"}])
        for revision, (action, count) in enumerate([("ignore_company", 0), ("restore_company", 1)]):
            profile = self.memory.edit({"revision": revision, "action": action, "target": "样本"})
            self.assertEqual(profile["companyCount"], count)
        self.memory.edit({"revision": 2, "action": "toggle", "enabled": False})
        with self.assertRaises(MemoryConflict):
            self.memory.suggest({"runId": self.run, "text": "现在关注", "quote": "应收", "category": "risk_focus"})
        for body in ({"action": "save", "category": "risk_focus", "text": "💡" * 251},
                     {"action": "save", "category": "bad", "text": "A"}, {"action": "toggle", "enabled": 1}):
            with self.assertRaises(ValueError):
                self.memory.edit({"revision": 3, **body})
        self.assertEqual(self.memory.snapshot()["revision"], 3)

    def test_note_capacity_and_tombstone_retention(self):
        self.sessions.append(self.session, [self.header])
        active = [{"id": f"active-{i}", "text": f"偏好{i}", "category": "risk_focus", "status": "confirmed"} for i in range(48)]
        rejected = [{"id": f"old-{i}", "fingerprint": str(i), "status": "rejected"} for i in range(256)]
        state = {"schemaVersion": 1, "enabled": True, "revision": 8, "ignoredTargets": [], "notes": active + rejected}
        self.memory.path.parent.mkdir()
        self.memory.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.memory.edit({"revision": 8, "action": "save", "text": "额外偏好", "category": "risk_focus"})
        with self.assertRaises(ValueError):
            self.memory.suggest({"runId": self.run, "text": "额外偏好", "quote": "应收", "category": "risk_focus"})
        self.memory.edit({"revision": 8, "action": "forget", "id": "active-0"})
        result = self.memory.edit({"revision": 9, "action": "save", "text": "新的偏好", "category": "risk_focus"})
        self.assertEqual(len(result["notes"]), 48)
        on_disk = json.loads(self.memory.path.read_bytes())["notes"]
        self.assertEqual(len(on_disk), 48 + 256)
        fingerprints = [n["id"] for n in on_disk if n["status"] == "rejected"]
        self.assertEqual(fingerprints, [n["id"] for n in rejected[1:]] + ["active-0"])
        self.assertEqual(self.memory.suggest({"runId": self.run, "text": "偏好0", "quote": "应收", "category": "risk_focus"}),
                         {"status": "already_recorded"})
