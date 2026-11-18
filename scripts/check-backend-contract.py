"""在一次性数据副本上验收迁移前的公开 API。运行方式见 docs/backend-compatibility.md。"""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import URLError

from backend_contract.scenarios import (
    Api, JOBS, MEMORY, check_first_start, check_saved_history,
    resume_and_chat, resume_frozen_checkpoint, start_and_cancel,
)

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "scripts/backend_contract"
JAR = ROOT / "apps/server/target/path-of-market-server.jar"


@contextmanager
def process(args, directory, name, env):
    with (directory / f"{name}.log").open("wb") as log:
        child = subprocess.Popen(args, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def wait_ready(child, api, path):
    deadline = time.monotonic() + 45
    while child.poll() is None and time.monotonic() < deadline:
        try:
            api.request("GET", path)
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.1)
    raise RuntimeError(f"启动失败或超时：{path}，退出码 {child.poll()}")


@contextmanager
def reference_backend(directory):
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0))
        b.bind(("127.0.0.1", 0))
        port, agent_port = a.getsockname()[1], b.getsockname()[1]
    api = Api(f"http://127.0.0.1:{port}")
    agent = Api(f"http://127.0.0.1:{agent_port}")
    env = {**os.environ, "SESSION_STORE_URL": api.base + "/internal/sessions",
           "NO_PROXY": "localhost,127.0.0.1", "PYTHONUTF8": "1"}
    java = [shutil.which("java"), "-Dfile.encoding=UTF-8", "-jar", str(JAR), f"--server.port={port}",
            f"--agent.base-url={agent.base}", f"--sessions.dir={directory / 'sessions'}"]
    with ExitStack() as stack:
        try:
            worker = stack.enter_context(process([sys.executable, str(TESTS / "legacy_agent.py"), str(agent_port),
                                                  str(directory)], directory, "agent", env))
            wait_ready(worker, agent, "/health")
            server = stack.enter_context(process(java, directory, "java", env))
            wait_ready(server, api, "/api/health")
            yield api
        except Exception:
            for log in directory.glob("*.log"):
                print(log.name, log.read_bytes()[-3000:].decode("utf-8", errors="replace"), file=sys.stderr)
            raise


def model_calls(directory):
    path = directory / "model-calls.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def check():
    if not __debug__:
        raise SystemExit("请使用普通 Python 模式运行，检查依赖 assert。")
    if not JAR.is_file() or not shutil.which("java"):
        raise SystemExit("需要已构建的 Java JAR 和 java，请先按 docs/backend-compatibility.md 构建。")
    with TemporaryDirectory(prefix="pom-contract-") as temp:
        directory = Path(temp)
        fixtures = TESTS / "fixtures"
        shutil.copytree(fixtures, directory, dirs_exist_ok=True)
        with reference_backend(directory) as api:
            check_first_start(api)
            assert model_calls(directory) == ["analysis"]
            task, coverage = start_and_cancel(api)
            assert model_calls(directory).count("reading") > 0
            print("PASS 旧会话与记忆、报告接口、错误格式、创建、互斥、取消", flush=True)
        before = model_calls(directory)
        with reference_backend(directory) as api:
            check_saved_history(api)
            profile = api.request("GET", MEMORY)
            assert profile["revision"] == 4 and profile["enabled"] is False
            assert model_calls(directory) == before
            resume_frozen_checkpoint(api)
            assert "reading" not in model_calls(directory)[len(before):]
            path, body = resume_and_chat(api, task, coverage)
            new_calls = model_calls(directory)[len(before):]
            assert "reading" not in new_calls and new_calls.count("discussion") == 1
            print("PASS 冷启动、检查点接续、已读资料零次重读、重复追问只执行一次", flush=True)
        before = model_calls(directory)
        with reference_backend(directory) as api:
            assert api.request("POST", path, 409, body)["error"]["code"] == "RESEARCH_NOT_RESUMABLE"
            turn, = api.request("GET", path.removesuffix("/chat") + "/discussion")["turns"]
            assert turn["requestId"] == body["requestId"]
            assert api.request("GET", f"{JOBS}/{turn['runId']}")["status"] == "completed"
            assert model_calls(directory) == before
        immutable_files = [*fixtures.glob("sessions/*.jsonl"), *fixtures.glob("evidence/run-checkpoints/*.json")]
        for source in immutable_files:
            assert (directory / source.relative_to(fixtures)).read_bytes() == source.read_bytes(), source.name
        print("PASS 再次重启后重发不调用模型，旧会话逐字节一致；12 个公开 HTTP 操作通过。")


if __name__ == "__main__":
    check()
