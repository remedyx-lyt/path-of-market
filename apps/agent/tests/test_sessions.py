"""M2-1 会话持久化（Python 侧）：条目结构与顺序、消息记录与作废、后台提交与失败重试。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.storage.sessions import SessionStore
import unittest

from support import FakeModel, RunnerFixture, report

from app.services.session_recorder import RecordedMessages, SessionRecorder


class Sessions(RunnerFixture, unittest.IsolatedAsyncioTestCase):
    async def run_recorded(self, model, fail_first=0):
        directory = self.enterContext(TemporaryDirectory())
        store = SessionStore(Path(directory))
        append = store.append

        def write(session_id, batch):
            nonlocal fail_first
            if fail_first:
                fail_first -= 1
                raise OSError("storage offline")
            return append(session_id, batch)

        self.enterContext(patch.object(store, "append", write))
        job, runner = self.runner(model)
        job.recorder = SessionRecorder(job.session_id, job.task_id, store, interval=0.05)
        job.recorder.header(job.request.model_dump(mode="json", by_alias=True))
        runner.messages = RecordedMessages(runner.messages, job.recorder)
        job.recorder.start()
        await runner.run()
        return job, store.load(job.session_id)

    async def test_entries_form_one_chain_with_messages_events_and_report(self):
        job, entries = await self.run_recorded(FakeModel(ready=True))
        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(entries[0]["type"], "session")
        self.assertEqual(entries[0]["id"], job.session_id)
        chain = entries[1:]
        self.assertIsNone(chain[0]["parentId"])
        self.assertTrue(all(b["parentId"] == a["id"] for a, b in zip(chain, chain[1:])))  # 当前分支：沿 parentId 首尾相接
        types = {e["type"] for e in chain}
        self.assertTrue({"message", "event", "report", "run_state"} <= types)
        tool_results = [e for e in chain if e["type"] == "message" and e["message"]["role"] == "tool"]
        self.assertTrue(tool_results and all(e["runId"] == job.task_id for e in chain))
        self.assertEqual(chain[-1]["type"], "run_state")
        self.assertEqual(chain[-1]["status"], "completed")
        self.assertEqual(job.snapshot()["persistence"]["unsent"], 0)

    async def test_rejected_draft_is_recorded_as_context_edit(self):
        bad = report()
        bad["sections"][0]["citations"] = [{"sourceId": "nope", "page": 1}]  # 引用不存在的来源，必然被退回

        class TwoDrafts(FakeModel):
            async def __call__(self, settings, messages, **kwargs):
                if self.kind(messages, kwargs) == "decision" and self.count("decision") >= 2:
                    self.final = bad if not getattr(self, "used_bad", False) else report()
                    self.used_bad = True
                return await super().__call__(settings, messages, **kwargs)

        job, entries = await self.run_recorded(TwoDrafts())
        self.assertEqual(job.status, "completed", job.error)
        edits = [e for e in entries if e["type"] == "context_edit"]
        self.assertEqual(len(edits), 1)
        target = next(e for e in entries if e["id"] == edits[0]["targetId"])
        self.assertIn("nope", target["message"]["content"])  # 作废的正是那份草稿；原行仍在，只是被标记

    async def test_store_outage_does_not_block_research_and_is_retried(self):
        job, entries = await self.run_recorded(FakeModel(ready=True), fail_first=3)
        self.assertEqual(job.status, "completed", job.error)
        ids = [e["id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)))  # 重发不产生重复
        self.assertEqual(entries[-1]["type"], "run_state")
        self.assertEqual(job.snapshot()["persistence"]["unsent"], 0)

    async def test_recorded_messages_track_pop(self):
        recorder = SessionRecorder("s", "r")
        messages = RecordedMessages([{"role": "system", "content": "a"}], recorder)
        messages.append({"role": "assistant", "content": "draft"})
        draft_id = recorder.last_id
        messages.pop()
        self.assertEqual([m["content"] for m in messages], ["a"])
        self.assertEqual(recorder.pending[-1]["type"], "context_edit")
        self.assertEqual(recorder.pending[-1]["targetId"], draft_id)
        self.assertFalse(asyncio.iscoroutine(recorder.status()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
