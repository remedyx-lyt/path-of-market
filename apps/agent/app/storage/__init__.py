"""共享会话索引和记忆锁，由 FastAPI 启动时初始化。"""
from contextlib import contextmanager
from functools import cache
import os
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.storage.memory import MemoryStore
from app.storage.sessions import SessionStore


def sessions_directory() -> Path:
    return PROJECT_ROOT / (os.environ.get("SESSIONS_DIR") or "storage/sessions")


@contextmanager
def writer_lease():
    """同一会话目录只允许一个在线后端。操作系统会在进程退出时释放锁。"""
    directory = sessions_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".writer.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("无法独占会话目录，请检查权限及是否已有后端在使用此目录。") from error
        yield


@cache
def get_storage() -> MemoryStore:
    return MemoryStore(SessionStore(sessions_directory()))
