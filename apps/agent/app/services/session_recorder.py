"""研究会话记录（M2-1）：把一次研究的事件、模型消息、报告按顺序提交给 Java SessionStore，写成 JSONL。

参照 Pi SessionManager 的条目结构：首条会话头，之后每条都有 id 与 parentId（指向上一条，形成当前分支），
另有 timestamp、sessionId、runId。条目类型：
- session：会话头（研究对象、问题、截止日等请求参数）
- event：活动流事件（data 为原事件）
- message：发给模型或模型返回的消息，含完整工具结果（恢复上下文、侧边聊天用）
- context_edit：作废的消息（如未通过核查的报告草稿），replacement 为 null，原行不删
- report：报告及版本号
- run_state：结束状态、用量、错误

提交在后台按批进行，失败保留并重试，不阻塞研究；状态在任务快照的 persistence 字段里如实显示。
"""

import asyncio
import json
import logging
import os
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.runtime import now

logger = logging.getLogger("path_of_market.session")
DEFAULT_URL = "http://127.0.0.1:8080/internal/sessions"


class SessionRecorder:
    def __init__(self, session_id, run_id, base_url=None, interval=1.0):
        self.session_id, self.run_id = session_id, run_id
        self.base_url = (base_url or os.environ.get("SESSION_STORE_URL") or DEFAULT_URL).rstrip("/")
        self.interval = interval
        self.pending, self.last_id = [], None
        self.sent, self.failures, self.last_error = 0, 0, None
        self.task = None

    def header(self, request):
        self.pending.append(
            {
                "type": "session",
                "version": 1,
                "id": self.session_id,
                "timestamp": now(),
                "sessionId": self.session_id,
                "runId": self.run_id,
                "request": request,
            }
        )

    def add(self, entry_type, **fields):
        """追加一条；返回条目 id（context_edit 用它指向被作废的消息）。"""
        entry_id = str(uuid4())
        self.pending.append(
            {
                "type": entry_type,
                "id": entry_id,
                "parentId": self.last_id,
                "timestamp": now(),
                "sessionId": self.session_id,
                "runId": self.run_id,
                **fields,
            }
        )
        self.last_id = entry_id
        return entry_id

    def status(self):
        unsent = len(self.pending)
        return {
            "store": "session_jsonl",
            "status": "ok" if not unsent and not self.last_error else "pending" if unsent else "ok",
            "sent": self.sent,
            "unsent": unsent,
            "lastError": self.last_error,
        }

    def post(self, batch):
        body = json.dumps({"entries": batch}, ensure_ascii=False, default=str).encode("utf-8")
        request = Request(
            f"{self.base_url}/{self.session_id}/entries", data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    async def flush(self):
        """把已有条目按顺序提交；成功才移出队列，失败保留到下次（Java 端按 id 去重，重发不会写重复行）。"""
        while self.pending:
            batch = self.pending[:200]
            try:
                await asyncio.to_thread(self.post, batch)
            except (HTTPError, URLError, OSError, ValueError) as error:
                if isinstance(error, HTTPError):
                    error.close()
                self.failures += 1
                self.last_error = f"会话存储暂不可用：{type(error).__name__}"
                if self.failures in (1, 10, 100):
                    logger.warning("session %s flush failed (%s attempts): %s", self.session_id, self.failures, error)
                return False
            del self.pending[: len(batch)]
            self.sent += len(batch)
            self.last_error = None
        return True

    def start(self):
        async def loop():
            while True:
                await asyncio.sleep(self.interval)
                await self.flush()

        self.task = asyncio.get_running_loop().create_task(loop())

    async def close(self, attempts=5):
        """研究结束：停后台循环，再尽力提交剩余条目（短暂重试）。"""
        if self.task:
            self.task.cancel()
        for attempt in range(attempts):
            if await self.flush():
                return True
            await asyncio.sleep(min(2 ** attempt * 0.2, 2))
        return False


class RecordedMessages(list):
    """runner.messages 的记录版：每次 append 记一条 message；pop 记一条 context_edit（原消息不删，标为作废）。"""

    def __init__(self, messages, recorder, *, record_initial=True, entry_ids=None):
        super().__init__()
        self.recorder, self.entry_ids = recorder, []
        if record_initial:
            for message in messages:
                self.append(message)
        else:
            super().extend(messages)
            self.entry_ids = list(entry_ids) if entry_ids and len(entry_ids) == len(messages) else [None] * len(messages)

    def append(self, message):
        super().append(message)
        self.entry_ids.append(self.recorder.add("message", message=message))

    def pop(self, index=-1):
        message = super().pop(index)
        target = self.entry_ids.pop(index)
        self.recorder.add("context_edit", targetId=target, replacement=None)
        return message
