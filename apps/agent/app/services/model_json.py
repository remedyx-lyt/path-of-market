"""模型 JSON 输出的统一重试与派生结果缓存。

此前阅读、视觉、取数和方法计划各自复制了“调用 → 解析 → 失败修复一次 → 写缓存”的流程；
这里集中实现，行为保持一致：最多修复一次，失败抛出最后一次解析错误，由调用方转换为业务错误。
缓存只是派生资料（阅读笔记、视觉观察、取数结果），不是会话记忆。
"""

from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.tools.documents import write_json

ModelCall = Callable[[list[dict]], Awaitable[dict]]


def escape_inner_quotes(raw):
    """修复长篇 JSON 中正文里未转义的英文双引号（如 不是"AI需求好不好"，而是）。

    字符串内遇到 `"` 时看后面第一个非空白字符：是 , : } ] 或文本结束才视为字符串结束，否则视为正文里的引号并转义。
    只在原文无法解析时使用；修复后仍须通过 schema 与程序核查。
    """
    out, in_string, i, n = [], False, 0, len(raw)
    while i < n:
        ch = raw[i]
        if in_string and ch == "\\":
            out.append(raw[i : i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_string:
                in_string = True
            else:
                j = i + 1
                while j < n and raw[j] in " \t\r\n":
                    j += 1
                if j < n and raw[j] not in ",:}]":
                    out.append('\\"')
                    i += 1
                    continue
                in_string = False
        out.append(ch)
        i += 1
    return "".join(out)


def stable_key(payload: Any) -> str:
    """对任意 JSON 结构计算稳定哈希；键排序，保证同一输入得到同一缓存文件名。"""
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def ask_json(
    call: ModelCall,
    messages: list[dict],
    parse: Callable[[str], Any],
    repair: str | Callable[[Exception], str],
    *,
    attempts: int = 2,
    on_invalid: Callable[[dict, Exception, int], None] | None = None,
) -> tuple[Any, dict]:
    """请求模型返回 JSON 并解析；解析失败时把错误说明追加给模型再试，最多 attempts 次。

    parse 抛出 ValueError（含 Pydantic ValidationError）视为格式问题；其他异常照常上抛。
    返回 (解析结果, 最后一次模型消息)。
    """
    conversation = list(messages)
    for attempt in range(attempts):
        message = await call(conversation)
        try:
            return parse(message.get("content") or ""), message
        except ValueError as error:
            if on_invalid:
                on_invalid(message, error, attempt)
            if attempt == attempts - 1:
                raise
            hint = repair(error) if callable(repair) else repair
            conversation = conversation + [message, {"role": "user", "content": hint}]
    raise AssertionError("unreachable")


class DerivedCache:
    """按内容哈希保存模型派生结果，记录首次产生它的运行 ID，便于标注“复用自哪次运行”。"""

    def __init__(self, folder: Path, field: str):
        self.folder, self.field = folder, field

    def path(self, key: str) -> Path:
        return self.folder / (key + ".json")

    def load(self, key: str, parse: Callable[[Any], Any]) -> tuple[Any, str | None]:
        """读取并重新校验缓存；文件缺失、损坏或校验失败都当作未命中。"""
        path = self.path(key)
        if not path.exists():
            return None, None
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            return parse(saved[self.field]), saved.get("runId")
        except (ValueError, KeyError, TypeError, OSError):
            return None, None

    def save(self, key: str, value: Any, **metadata) -> None:
        write_json(self.path(key), {self.field: value, **metadata})
