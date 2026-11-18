"""迁移前后共用的公开 HTTP 检查。此文件不导入任何 Java、FastAPI 或存储实现。"""
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

JOBS = "/api/research/jobs"
MEMORY = "/api/research/memory"
SESSIONS = "/api/research/sessions"
OLD_ROOT = "00000000-0000-4000-8000-000000000011"
OLD_FOLLOWUP = "00000000-0000-4000-8000-000000000012"
INTERRUPTED = "00000000-0000-4000-8000-000000000013"
CHECKPOINTED = "00000000-0000-4000-8000-000000000014"
REQUEST = {"target": "同花顺", "question": "研究最近两年的经营变化与行情。", "asOfDate": "2026-10-23",
           "includeMarket": True, "includeFinancials": False, "includeCurrentPeriod": False}


class Api:
    def __init__(self, base):
        self.base = base

    def request(self, method, path, expected=200, body=None):
        data = body
        if body is not None and not isinstance(body, bytes):
            data = json.dumps(body).encode()
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            assert response.status == expected, (method, path, response.status, expected, raw[:700])
            return json.loads(raw) if raw else None

    def poll(self, task, condition):
        end = time.monotonic() + 25
        while time.monotonic() < end:
            job = self.request("GET", f"{JOBS}/{task}")
            if condition(job):
                return job
            time.sleep(0.05)
        raise AssertionError(f"{task} did not reach expected state: {job['status']}, {job.get('error')}")

    def terminal(self, task, status):
        job = self.poll(task, lambda j: j["status"] not in {"queued", "running"} and
                        not (j.get("persistence") or {}).get("unsent"))
        assert job["status"] == status, (task, job["status"], job.get("error"))
        return job


def check_saved_history(api):
    root = api.request("GET", f"{JOBS}/{OLD_ROOT}")
    assert root["status"] == "completed" and root["report"]["summary"] == "初版判断。"
    assert root["modelCalls"] == 2 and root["usage"] == {"total_tokens": 80}
    assert root["coverage"][0]["processedPages"] == [1]
    child = api.request("GET", f"{JOBS}/{OLD_FOLLOWUP}")
    assert child["report"]["summary"] == "修订判断。" and child["sessionId"] == root["sessionId"]
    discussion = api.request("GET", f"{JOBS}/{OLD_FOLLOWUP}/discussion")
    assert discussion["rootTaskId"] == OLD_ROOT and discussion["sessionId"] == root["sessionId"]
    v1, v2 = discussion["versions"]
    turn, = discussion["turns"]
    assert [v1["reportVersion"], v2["reportVersion"]] == [1, 2]
    assert [v1["report"], v2["report"]] == [root["report"], child["report"]]
    assert turn["baseVersionId"] == turn["parentTurnId"] == v2["parentVersionId"] == v1["id"]
    assert turn["versionId"] == v2["id"] and turn["status"] == "completed"
    assert turn["runId"] == OLD_FOLLOWUP and turn["answer"] == "已修订第一节。"
    stopped = api.request("GET", f"{JOBS}/{INTERRUPTED}")
    assert stopped["status"] == "failed" and stopped["error"]["code"] == "RESEARCH_INTERRUPTED"
    assert stopped["report"] is None and stopped["events"][-1]["message"] == "收集资料"


def check_first_start(api):
    assert api.request("GET", "/api/health") == {"status": "ok", "service": "server"}
    check_saved_history(api)
    recent = api.request("GET", SESSIONS + "?limit=3")["sessions"]
    assert [(s["runId"], s["status"]) for s in recent] == [
        (CHECKPOINTED, "failed"), (INTERRUPTED, "failed"), (OLD_ROOT, "completed"),
    ]
    assert len(api.request("GET", SESSIONS + "?limit=1")["sessions"]) == 1

    profile = api.request("GET", MEMORY)
    assert profile["schemaVersion"] == 1 and profile["revision"] == 3
    assert profile["notes"][0]["text"] == "先看经营现金流"
    change = {"revision": 3, "action": "toggle", "enabled": False}
    saved = api.request("POST", MEMORY, body=change)
    assert saved["revision"] == 4 and saved["enabled"] is False
    conflict = api.request("POST", MEMORY, 409, change)["error"]
    assert conflict["code"] == "MEMORY_CONFLICT" and conflict["message"]
    invalid = api.request("POST", MEMORY, 400, {"revision": 4, "action": "toggle", "enabled": "false"})
    assert invalid["error"]["code"] == "INVALID_MEMORY"
    assert api.request("GET", MEMORY)["revision"] == 4

    simple = {"target": REQUEST["target"], "question": REQUEST["question"], "userStyle": "基线", "omens": ["opportunity"]}
    mock = api.request("POST", "/api/research/mock", body=simple)
    assert mock["mode"] == "mock" and mock["isMock"] is True and mock["userStyle"] == simple["userStyle"]
    assert mock["sections"] and mock["sources"] == mock["toolCalls"] == []
    model = api.request("POST", "/api/research/model", body={**simple, "asOfDate": REQUEST["asOfDate"]})
    assert model["mode"] == "model" and model["isMock"] is False and model["evidenceStatus"] == "not_retrieved"
    assert model["run"]["states"] == ["created", "calling_model", "completed"] and model["limitations"]
    assert model["sources"] == model["toolCalls"] == [] and len(model["sections"]) >= 2

    assert api.request("POST", JOBS, 400, b"{")["error"]["code"] == "INVALID_JSON"
    detail = api.request("POST", JOBS, 422, {**REQUEST, "asOfDate": "2999-01-01"})["detail"]
    assert any(d["loc"] == ["body", "asOfDate"] and d["msg"] and d["type"] for d in detail)
    missing = f"{JOBS}/{uuid4()}"
    assert api.request("GET", missing, 404)["error"]["code"] == "RESEARCH_NOT_FOUND"
    assert api.request("GET", missing + "/discussion", 404) is None
    assert api.request("POST", f"{JOBS}/{INTERRUPTED}/continue", 409)["error"]["code"] == "RESEARCH_NOT_RESUMABLE"


def start_and_cancel(api):
    job = api.request("POST", JOBS, 202, REQUEST)
    task = str(UUID(job["taskId"]))
    assert job["status"] == "queued" and all(isinstance(job[k], list) for k in ("events", "toolCalls", "sources", "coverage"))
    assert api.request("POST", JOBS, 409, REQUEST)["error"]["code"] == "RESEARCH_BUSY"
    api.poll(task, lambda j: j["phase"] == "writing" and any(c["textComplete"] for c in j["coverage"]))
    cancelled = api.request("DELETE", f"{JOBS}/{task}")
    assert cancelled["taskId"] == task
    ended = api.terminal(task, "cancelled")
    return task, ended["coverage"]


def resume_frozen_checkpoint(api):
    source = f"{JOBS}/{CHECKPOINTED}"
    assert api.request("GET", source)["error"]["code"] == "RESEARCH_INTERRUPTED"
    child = api.request("POST", source + "/continue", 202)
    assert child["parentTaskId"] == CHECKPOINTED and child["taskId"] != CHECKPOINTED
    job = api.terminal(child["taskId"], "completed")
    coverage, = job["report"]["coverage"]
    assert coverage["sourceId"] == "cninfo-1234567890" and coverage["processedPages"] == [1, 2]
    assert not any(call["name"] == "read_document" for call in job["toolCalls"])
    assert api.request("GET", source)["error"]["code"] == "RESEARCH_INTERRUPTED"


def resume_and_chat(api, task, coverage):
    assert api.request("GET", f"{JOBS}/{task}")["status"] == "cancelled"
    resumed = api.request("POST", f"{JOBS}/{task}/continue", 202)
    child = str(UUID(resumed["taskId"]))
    assert child != task and resumed["parentTaskId"] == task
    job = api.terminal(child, "completed")
    assert job["report"]["mode"] == "agent" and job["coverage"] == coverage
    assert not any(call["name"] == "read_document" for call in job["toolCalls"])
    assert api.request("GET", f"{JOBS}/{task}")["status"] == "cancelled"
    discussion = api.request("GET", f"{JOBS}/{child}/discussion")
    version, = discussion["versions"]
    assert version["report"] == job["report"]
    path = f"{JOBS}/{child}/chat"
    body = {"parentId": version["id"], "action": "ask", "message": "请解释结论", "requestId": str(uuid4())}
    sent = api.request("POST", path, 202, body)
    assert sent["parentTaskId"] == child
    api.terminal(sent["taskId"], "completed")
    duplicate = api.request("POST", path, 202, body)
    assert duplicate["taskId"] == sent["taskId"]
    turn, = api.request("GET", f"{JOBS}/{child}/discussion")["turns"]
    assert turn["requestId"] == body["requestId"] and turn["status"] == "completed" and turn["answer"]
    return path, body
