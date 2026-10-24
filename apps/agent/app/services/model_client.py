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
        connection.request("POST", url.path.rstrip("/") + "/chat/completions",
                           body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           headers={"Authorization": f"Bearer {settings.api_key}",
                                    "Content-Type": "application/json", "Accept": "application/json"})
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


async def complete_turn(settings: ModelSettings, messages: list[dict], *, tools: list | None = None,
                        max_tokens: int | None = None, json_mode: bool = True) -> tuple[dict, dict]:
    """标准 assistant/tool 协议；工具执行留给 Runner，截断的工具参数不执行。"""
    payload = {"model": settings.model, "messages": messages, "stream": False,
               "thinking": {"type": "disabled"}, "max_tokens": max_tokens or settings.max_tokens}
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body, choice = None, None
    try:
        async with asyncio.timeout(settings.timeout_seconds):
            body = await asyncio.to_thread(_request_payload, settings, payload)
        choice = body["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if (choice.get("finish_reason") not in {"stop", "tool_calls"} or not isinstance(calls, list)
                or len(calls) > 6 or calls and (not tools or choice.get("finish_reason") != "tool_calls")
                or not calls and choice.get("finish_reason") != "stop"):
            raise ValueError
        clean = {"role": "assistant", "content": message.get("content")}
        if clean["content"] is not None and not isinstance(clean["content"], str):
            raise ValueError
        if calls:
            normalized, ids = [], set()
            for call in calls:
                identifier, function = call["id"], call["function"]
                if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 200 or identifier in ids
                        or call.get("type") != "function" or not isinstance(function["name"], str)
                        or not isinstance(function["arguments"], str) or len(function["arguments"]) > 16000):
                    raise ValueError
                ids.add(identifier)
                normalized.append({"id": identifier, "type": "function", "function":
                                   {"name": function["name"], "arguments": function["arguments"]}})
            clean["tool_calls"] = normalized
        elif not clean["content"]:
            raise ValueError
        usage = body.get("usage") or {}
        counts = {name: value for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                  if type(value := usage.get(name)) is int and value >= 0}
        return clean, counts
    except TimeoutError:
        raise ModelServiceError("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。", 504) from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        error=ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的工具消息或内容。", 502)
        error.finish_reason=choice.get('finish_reason') if isinstance(choice,dict) else None
        raw_usage=body.get('usage',{}) if isinstance(body,dict) else {}
        if not isinstance(raw_usage,dict): raw_usage={}
        error.usage={k:v for k in ['prompt_tokens','completion_tokens','total_tokens'] if type(v:=raw_usage.get(k)) is int and v>=0}
        raise error from None


async def generate_content(settings: ModelSettings, messages: list[dict[str, str]]) -> tuple[ModelContent, dict[str, int]]:
    message, usage = await complete_turn(settings, messages)
    try:
        return ModelContent.model_validate_json(message["content"]), usage
    except ValueError:
        raise ModelServiceError("MODEL_INVALID_RESPONSE", "模型未返回完整且有效的报告，请重试或调整输出长度。", 502) from None
