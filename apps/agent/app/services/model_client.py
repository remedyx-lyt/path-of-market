"""有限等待、无自动重试、无重定向；上游错误正文不传给网页或日志。"""

import asyncio
import http.client
import json
import socket
import time
from urllib.parse import urlsplit
from app.core.config import ModelServiceError, ModelSettings
from app.schemas.research import ModelContent

MAX_RESPONSE_BYTES = 1_048_576
# DeepSeek 自动前缀缓存：命中/未命中分别计价（命中约为未命中的 1/50），见 api-docs.deepseek.com/guides/kv_cache。
USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


def usage_counts(usage) -> dict:
    """只保留供应商返回的非负整数用量字段；其他内容不进入任务记录。

    缓存命中统一记成 DeepSeek 的扁平字段：OpenAI 报在 usage.prompt_tokens_details.cached_tokens，换算成命中/未命中。
    """
    if not isinstance(usage, dict):
        return {}
    counts = {name: value for name in USAGE_FIELDS if type(value := usage.get(name)) is int and value >= 0}
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if "prompt_cache_hit_tokens" not in counts and type(cached) is int and 0 <= cached <= counts.get("prompt_tokens", -1):
        counts.update(prompt_cache_hit_tokens=cached, prompt_cache_miss_tokens=counts["prompt_tokens"] - cached)
    return counts


def provider_options(settings: ModelSettings) -> dict:
    """服务商特有的请求参数（见 config.PROVIDERS）。DeepSeek 关闭思考模式；OpenAI 新模型调工具需 reasoning_effort=none。"""
    if settings.reasoning_mode == "deepseek":
        return {"thinking": {"type": "disabled"}}
    if settings.reasoning_mode == "reasoning_effort" and settings.reasoning_effort:
        return {"reasoning_effort": settings.reasoning_effort}
    return {}


def _request_payload(settings: ModelSettings, payload: dict) -> dict:
    url = urlsplit(settings.base_url)
    connection_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(url.hostname, url.port, timeout=min(10, settings.timeout_seconds))
    deadline = time.monotonic() + settings.timeout_seconds
    response = None
    try:
        connection.connect()

        def remaining() -> None:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError
            # HTTP/1.0 或 Connection: close 时，响应持有读取句柄，connection.sock 已被释放。
            if connection.sock is not None:
                connection.sock.settimeout(seconds)

        remaining()
        connection.request(
            "POST",
            url.path.rstrip("/") + "/chat/completions",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json", "Accept": "application/json"},
        )
        remaining()
        response = connection.getresponse()
        if response.status != 200:
            errors = {
                401: ("MODEL_AUTH_FAILED", "模型密钥验证失败，请检查 .env 中的密钥。"),
                403: ("MODEL_AUTH_FAILED", "模型接口拒绝访问，请检查密钥和账户权限。"),
                402: ("MODEL_BALANCE_INSUFFICIENT", "模型账户余额或额度不足，请到供应商平台检查。"),
                429: ("MODEL_RATE_LIMITED", "模型调用过于频繁或额度受限，请稍后再试。"),
            }
            code, message = errors.get(response.status, ("MODEL_UPSTREAM_ERROR", "模型接口暂时无法完成请求，请检查模型配置或稍后重试。"))
            raise ModelServiceError(code, message, 503 if response.status in errors else 502)
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining()
            chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError
            chunks.append(chunk)
        body = json.loads(b"".join(chunks))
        if not isinstance(body, dict):
            raise ValueError
        return body
    except ModelServiceError:
        raise
    except (TimeoutError, socket.timeout):
        raise ModelServiceError("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。", 504) from None
    except (OSError, http.client.HTTPException):
        raise ModelServiceError("MODEL_UNAVAILABLE", "无法连接模型接口，请检查网络和接口地址。") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的报告，请重试或调整输出长度。", 502) from None
    finally:
        if response is not None:
            response.close()
        connection.close()


def _stream_payload(settings: ModelSettings, payload: dict, on_text) -> dict:
    """流式请求：按 SSE 逐行读取 `data:` 块，文字增量交给 on_text，最后拼成与非流式相同结构的 body。

    依据 DeepSeek Chat Completion 文档：data-only SSE、`data: [DONE]` 结束；stream_options.include_usage 时最后一块带用量；
    工具调用首块带 id/type/function，后续块只带 arguments。非 `data:` 行（如 keep-alive 注释）忽略。
    """
    url = urlsplit(settings.base_url)
    connection_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(url.hostname, url.port, timeout=min(10, settings.timeout_seconds))
    deadline = time.monotonic() + settings.timeout_seconds
    response = None
    content, calls, finish_reason, usage, size = [], {}, None, None, 0
    try:
        connection.connect()

        def remaining() -> None:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(seconds)

        remaining()
        connection.request(
            "POST",
            url.path.rstrip("/") + "/chat/completions",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        remaining()
        response = connection.getresponse()
        if response.status != 200:
            errors = {
                401: ("MODEL_AUTH_FAILED", "模型密钥验证失败，请检查 .env 中的密钥。"),
                403: ("MODEL_AUTH_FAILED", "模型接口拒绝访问，请检查密钥和账户权限。"),
                402: ("MODEL_BALANCE_INSUFFICIENT", "模型账户余额或额度不足，请到供应商平台检查。"),
                429: ("MODEL_RATE_LIMITED", "模型调用过于频繁或额度受限，请稍后再试。"),
            }
            code, message = errors.get(response.status, ("MODEL_UPSTREAM_ERROR", "模型接口暂时无法完成请求，请检查模型配置或稍后重试。"))
            raise ModelServiceError(code, message, 503 if response.status in errors else 502)
        while True:
            remaining()
            line = response.readline(MAX_RESPONSE_BYTES)
            if not line:
                break
            size += len(line)
            if size > MAX_RESPONSE_BYTES * 2:
                raise ValueError
            text = line.decode("utf-8").strip()
            if not text.startswith("data:"):
                continue
            data = text[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    content.append(delta["content"])
                    on_text(delta["content"])
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(call.get("index", 0), {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                    slot["id"] = call.get("id") or slot["id"]
                    function = call.get("function") or {}
                    slot["function"]["name"] += function.get("name") or ""
                    slot["function"]["arguments"] += function.get("arguments") or ""
                finish_reason = choice.get("finish_reason") or finish_reason
        message = {"role": "assistant", "content": "".join(content) or None}
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return {"choices": [{"message": message, "finish_reason": finish_reason}], "usage": usage}
    except ModelServiceError:
        raise
    except (TimeoutError, socket.timeout):
        raise ModelServiceError("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。", 504) from None
    except (OSError, http.client.HTTPException):
        raise ModelServiceError("MODEL_UNAVAILABLE", "无法连接模型接口，请检查网络和接口地址。") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, UnicodeDecodeError):
        raise ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的报告，请重试或调整输出长度。", 502) from None
    finally:
        if response is not None:
            response.close()
        connection.close()


async def complete_turn(
    settings: ModelSettings,
    messages: list[dict],
    *,
    tools: list | None = None,
    max_tokens: int | None = None,
    json_mode: bool = True,
    tool_choice: str | dict = "auto",
    on_text=None,
) -> tuple[dict, dict]:
    """标准 assistant/tool 协议；工具执行留给 Runner，截断的工具参数不执行。

    on_text 不为空时改用流式输出（见 _stream_payload），逐段把文字交给 on_text。
    tool_choice="none" 用于写作阶段：仍发送同一组工具定义，使提示开头与研究轮次一致（前缀缓存可命中），但不允许调用工具。
    """
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        **provider_options(settings),
        settings.max_tokens_field: max_tokens or settings.max_tokens,
    }
    if tools:
        payload.update(tools=tools, tool_choice=tool_choice)
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if on_text:
        # 流式输出：写作阶段边写边显示进度；返回结构与非流式相同，后续校验不变。
        payload.update(stream=True, stream_options={"include_usage": True})
    body, choice = None, None
    try:
        async with asyncio.timeout(settings.timeout_seconds):
            if on_text:
                body = await asyncio.to_thread(_stream_payload, settings, payload, on_text)
            else:
                body = await asyncio.to_thread(_request_payload, settings, payload)
        choice = body["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if (
            choice.get("finish_reason") not in {"stop", "tool_calls"}
            or not isinstance(calls, list)
            or len(calls) > 6
            or calls
            and (not tools or choice.get("finish_reason") != "tool_calls")
            or not calls
            and choice.get("finish_reason") != "stop"
        ):
            raise ValueError
        clean = {"role": "assistant", "content": message.get("content")}
        if clean["content"] is not None and not isinstance(clean["content"], str):
            raise ValueError
        if calls:
            normalized, ids = [], set()
            for call in calls:
                identifier, function = call["id"], call["function"]
                if (
                    not isinstance(identifier, str)
                    or not 1 <= len(identifier) <= 200
                    or identifier in ids
                    or call.get("type") != "function"
                    or not isinstance(function["name"], str)
                    or not isinstance(function["arguments"], str)
                    or len(function["arguments"]) > 16000
                ):
                    raise ValueError
                ids.add(identifier)
                normalized.append(
                    {"id": identifier, "type": "function", "function": {"name": function["name"], "arguments": function["arguments"]}}
                )
            clean["tool_calls"] = normalized
        elif not clean["content"]:
            raise ValueError
        return clean, usage_counts(body.get("usage"))
    except TimeoutError:
        raise ModelServiceError("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。", 504) from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        error = ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的工具消息或内容。", 502)
        error.finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        error.usage = usage_counts(body.get("usage") if isinstance(body, dict) else None)
        raise error from None


async def generate_content(settings: ModelSettings, messages: list[dict[str, str]]) -> tuple[ModelContent, dict[str, int]]:
    message, usage = await complete_turn(settings, messages)
    try:
        return ModelContent.model_validate_json(message["content"]), usage
    except ValueError:
        raise ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的报告，请重试或调整输出长度。", 502) from None
