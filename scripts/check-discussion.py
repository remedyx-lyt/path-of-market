"""真实 Java→FastAPI→Agent工具→JSONL 集成检查，使用隔离资料/脚本模型，绝不读取真实密钥。

临时服务只绑定127.0.0.1随机端口；隔离会话和检查点在.runtime/qa/discussion。
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / ".runtime/qa/discussion"
sys.path.insert(0, str(ROOT / "apps/agent/tests"))


def worker(port):
    from support import FakeModel, SETTINGS, make_tools, BASE_REQUEST, DOC_ID, USAGE, tool_call
    from app.main import app
    from app.api.routes import jobs
    from app.schemas.agent import AgentResearchRequest
    from app.services.agent_runner import AgentRunner
    from app.services import agent_runner
    from app.services.research_jobs import ResearchJob, job_store
    from app.services.session_recorder import SessionRecorder
    from app.services.report_discussion import load_entries
    from app.core.config import ModelServiceError
    import uvicorn

    tools = make_tools(FOLDER / "evidence")
    state = {"calls": 0, "transient": 0}

    async def completion(settings, messages, **kwargs):
        state["calls"] += 1
        assert settings.api_key == "isolated-test-key-only"
        queries = [m.get("content", "") for m in messages if m["role"] == "user" and isinstance(m.get("content"), str) and m["content"].startswith("QA_")]
        query = queries[-1]
        if query == "QA_INTERRUPT":
            await asyncio.sleep(45)
        if query == "QA_FAIL_AUTH":
            raise ModelServiceError("MODEL_AUTH_FAILED", "隔离测试：账户不可用", 503)
        if query == "QA_TRANSIENT" and not state["transient"]:
            state["transient"] += 1
            raise ModelServiceError("MODEL_TIMEOUT", "隔离测试：临时超时", 504)
        if query == "QA_TOOL" and not any(m["role"] == "tool" for m in messages):
            return {"role": "assistant", "content": None, "tool_calls": [tool_call(1, 0, "read_document", {"documentId": DOC_ID, "mode": "page", "page": 1})]}, USAGE
        revise = "当前操作：revise" in messages[-1]["content"]
        edits = []
        if revise:
            edits = [{"index": 2 if query == "QA_APPEND" else 0, "heading": "新增补充" if query == "QA_APPEND" else "经营证据（修订）",
                      "content": "**更保守的判断。**\n\n经营与风险需要结合实际来源解释。", "citations": [{"sourceId": DOC_ID, "page": 1}]}]
        answer = {"answer": "当前分支的问题：" + " → ".join(queries), "citations": [{"sourceId": DOC_ID, "page": 1}], "sectionEdits": edits, "summary": None}
        if query == "QA_BAD_CITATION" and not any("请修正回复" in str(m.get("content")) for m in messages):
            answer["citations"][0]["page"] = 999
        return {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}, USAGE

    jobs.load_model_settings = lambda: SETTINGS
    jobs.get_research_tools = lambda: tools
    agent_runner.complete_turn = completion

    @app.post("/qa/seed")
    async def seed():
        job = ResearchJob(AgentResearchRequest.model_validate(BASE_REQUEST))
        job.recorder = SessionRecorder(job.session_id, job.task_id)
        job.recorder.header(job.request.model_dump(mode="json", by_alias=True))
        job.recorder.start()
        runner = AgentRunner(job, tools, SETTINGS, completion=FakeModel(ready=True))
        await runner.run()
        assert job.status == "completed", job.error
        job_store.jobs[job.task_id] = job
        entries = await asyncio.to_thread(load_entries, job.task_id)
        report_node = next(e for e in entries if e["type"] == "report")
        return {"taskId": job.task_id, "nodeId": report_node["id"]}

    @app.get("/qa/calls")
    def calls():
        return state

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    spec = importlib.util.spec_from_file_location("session_checks", ROOT / "scripts/check-sessions.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    bridge.FOLDER = FOLDER
    FOLDER.mkdir(parents=True, exist_ok=True)
    # 隔离服务使用JAR副本，避免Windows锁住正式构建产物，影响应用启动/打包。
    bridge.JAR_PATH = FOLDER / "server.jar"
    shutil.copy2(ROOT / "apps/server/target/path-of-market-server.jar", bridge.JAR_PATH)
    provider_port, java_port = free_port(), free_port()
    provider_base = f"http://127.0.0.1:{provider_port}"
    environment = {**os.environ, "SESSION_STORE_URL": f"http://127.0.0.1:{java_port}/internal/sessions"}
    agent_log = (FOLDER / "agent.log").open("ab")
    process, log, agent = None, None, None

    def start_agent():
        result = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(provider_port)], cwd=ROOT,
            env=environment, stdout=agent_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(100):
            if result.poll() is not None:
                raise RuntimeError("隔离Python启动失败，见.runtime/qa/discussion/agent.log")
            try:
                if bridge.request(provider_base, "/qa/calls")[0] == 200:
                    return result
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError("隔离Python启动超时")

    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
        print("PASS", name, flush=True)

    try:
        agent = start_agent()
        process, base, log = bridge.start_java(java_port, provider_port)
        _, seed = bridge.request(provider_base, "/qa/seed", "POST", {})
        task, root = seed["taskId"], seed["nodeId"]
        prefix = f"/api/research/jobs/{task}"
        _, original = bridge.request(base, prefix + "/discussion")
        check("初版报告可读取，查看不调用模型", len(original["versions"]) == 1 and bridge.request(provider_base, "/qa/calls")[1]["calls"] == 0)

        def send(message, node=root, action="ask", body=None):
            body = body or {"message": message, "parentId": node, "action": action, "requestId": str(uuid4())}
            status, snapshot = bridge.request(base, prefix + "/chat", "POST", body)
            assert status in (200, 202), (status, snapshot)
            for _ in range(180):
                _, snapshot = bridge.request(base, f"/api/research/jobs/{snapshot['taskId']}")
                if snapshot["status"] not in {"queued", "running"} and not (snapshot.get("persistence") or {}).get("unsent"):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("对话未按时结束")
            _, discussion = bridge.request(base, prefix + "/discussion")
            turn = next(t for t in discussion["turns"] if t["runId"] == snapshot["taskId"])
            return snapshot, turn, discussion

        first, first_turn, discussion = send("QA_FIRST")
        check("Java→Python异步追问完成并落盘", first["status"] == "completed" and first_turn["answer"] and len(discussion["versions"]) == 1)
        revised, revised_turn, discussion = send("QA_REVISE", first_turn["id"], "revise")
        v2 = discussion["versions"][-1]
        check("局部修订另存V2，原报告逐字段不变", revised["status"] == "completed" and v2["reportVersion"] == 2 and discussion["versions"][0] == original["versions"][0])
        check("V2保留图表与数据表、记录修改位置", v2["changedSections"] == [0] and v2["report"]["figurePlan"] == original["versions"][0]["report"]["figurePlan"])
        _, sibling, _ = send("QA_SIBLING")
        check("从初版分支不混入另一分支追问", "QA_FIRST" not in sibling["answer"] and "QA_REVISE" not in sibling["answer"])
        _, follow, _ = send("QA_FOLLOW", revised_turn["id"])
        check("沿当前父链保留多轮历史", all(x in follow["answer"] for x in ("QA_FIRST", "QA_REVISE", "QA_FOLLOW")) and "QA_SIBLING" not in follow["answer"])
        tool_job, _, _ = send("QA_TOOL")
        check("模型自主回查PDF原页，记录真实工具事件", tool_job["status"] == "completed" and any(e["type"] == "tool_finished" and e["status"] == "completed" for e in tool_job["events"]))
        transient, _, _ = send("QA_TRANSIENT")
        check("暂时模型超时在当前节点重试", transient["status"] == "completed" and any(e["type"] == "writing_unit_retry" for e in transient["events"]))
        invalid, invalid_turn, _ = send("QA_BAD_CITATION")
        check("未读页引用被拒绝，修正后才保存", invalid["status"] == "completed" and invalid_turn["citations"][0]["page"] == 1 and any(e["type"] == "report_validation_failed" for e in invalid["events"]))
        failed, failure, discussion = send("QA_FAIL_AUTH")
        check("账户错误停止，原报告及版本保留", failed["status"] == "failed" and failure["status"] == "failed" and len(discussion["versions"]) == 2)
        recovered, _, _ = send("QA_RECOVER", failure["id"])
        check("失败对话从已保存证据节点重新尝试", recovered["status"] == "completed" and recovered["coverage"] == first["coverage"])
        appended, _, discussion = send("QA_APPEND", root, "revise")
        check("新增章节同时补齐图表计划，避免前端拒收", appended["status"] == "completed" and len(discussion["versions"][-1]["report"]["sections"]) == len(discussion["versions"][-1]["report"]["figurePlan"]) == 3)
        body = {"message": "QA_DEDUPE", "parentId": root, "action": "ask", "requestId": str(uuid4())}
        deduped, _, _ = send("", body=body)
        before = bridge.request(provider_base, "/qa/calls")[1]["calls"]
        repeated, _, _ = send("", body=body)
        check("POST重复投递复用原任务、不重复计费", repeated["taskId"] == deduped["taskId"] and bridge.request(provider_base, "/qa/calls")[1]["calls"] == before)
        status, _ = bridge.request(base, prefix + "/chat", "POST", {**body, "requestId": str(uuid4()), "parentId": str(uuid4())})
        check("不存在的分支在调用模型前拒绝", status == 409 and bridge.request(provider_base, "/qa/calls")[1]["calls"] == before)
        status, _ = bridge.request(base, prefix + "/chat", "POST", {**body, "message": " "})
        check("空问题在边界返回422", status == 422)

        agent.terminate(); agent.wait(timeout=10)
        agent = start_agent()
        bridge.stop_java(process, log); process, log = None, None
        process, base, log = bridge.start_java(java_port, provider_port)
        _, saved = bridge.request(base, prefix + "/discussion")
        _, restored = bridge.request(base, f"/api/research/jobs/{deduped['taskId']}")
        check("Java/Python重启后报告版本、对话与任务均可恢复查看", len(saved["versions"]) == 3 and restored["status"] == "completed" and restored["followup"]["answer"])
        restart_job, restart_turn, _ = send("QA_AFTER_RESTART", revised_turn["id"])
        check("重启后沿旧分支继续问，复用证据与历史", restart_job["status"] == "completed" and "QA_FIRST" in restart_turn["answer"] and "QA_SIBLING" not in restart_turn["answer"])
        before = bridge.request(provider_base, "/qa/calls")[1]["calls"]
        status, _ = bridge.request(base, prefix + "/chat", "POST", body)
        check("重启后相同请求标识也不会重启收费调用", status == 409 and bridge.request(provider_base, "/qa/calls")[1]["calls"] == before)
        _, interrupted = bridge.request(base, prefix + "/chat", "POST", {"message": "QA_INTERRUPT", "parentId": root, "action": "ask", "requestId": str(uuid4())})
        agent.kill(); agent.wait(timeout=10)
        _, saved_pending = bridge.request(base, prefix + "/discussion")
        pending = next(t for t in saved_pending["turns"] if t["runId"] == interrupted["taskId"])
        _, interrupted_snapshot = bridge.request(base, f"/api/research/jobs/{interrupted['taskId']}")
        check("进程硬中断后，已提交的请求仍可查看且标明中断", pending["status"] == "pending" and interrupted_snapshot["status"] == "failed")
        agent = start_agent()
        recovered_interrupt, _, _ = send("QA_INTERRUPT_RECOVER", pending["id"])
        check("硬中断请求可从保存节点恢复，缺少新检查点时复用基础报告", recovered_interrupt["status"] == "completed")
        _, cancellable = bridge.request(base, prefix + "/chat", "POST", {"message": "QA_INTERRUPT", "parentId": root, "action": "ask", "requestId": str(uuid4())})
        status, cancelled = bridge.request(base, f"/api/research/jobs/{cancellable['taskId']}", "DELETE")
        for _ in range(60):
            _, cancelled = bridge.request(base, f"/api/research/jobs/{cancellable['taskId']}")
            if cancelled["status"] == "cancelled" and not (cancelled.get("persistence") or {}).get("unsent"):
                break
            time.sleep(0.1)
        check("停止对话结束活动流并保留原版本", status == 200 and cancelled["status"] == "cancelled")
        (FOLDER / "result.json").write_text(json.dumps({"checks": checks, "discussion": saved}, ensure_ascii=False), encoding="utf-8")
        print(f"{len(checks)}项隔离集成检查通过；真实模型调用0次。", flush=True)
    finally:
        if process:
            bridge.stop_java(process, log)
        if agent and agent.poll() is None:
            agent.terminate(); agent.wait(timeout=10)
        agent_log.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(int(sys.argv[2]))
    else:
        main()
