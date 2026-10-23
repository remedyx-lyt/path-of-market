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


def _request(settings: ModelSettings, messages: list[dict[str, str]]) -> tuple[ModelContent, dict[str, int]]:
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
        payload = {"model": settings.model, "messages": messages, "stream": False,
                   "thinking": {"type": "disabled"}, "max_tokens": settings.max_tokens,
                   "response_format": {"type": "json_object"}}
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
        choice = body["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("tool_calls"):
            raise ValueError
        content = ModelContent.model_validate_json(choice["message"]["content"])
        usage = body.get("usage") or {}
        counts = {name: value for name in ("prompt_tokens", "completion_tokens", "total_tokens")
                  if type(value := usage.get(name)) is int and value >= 0}
        return content, counts
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


async def generate_content(settings: ModelSettings, messages: list[dict[str, str]]) -> tuple[ModelContent, dict[str, int]]:
    try:
        async with asyncio.timeout(settings.timeout_seconds):
            return await asyncio.to_thread(_request, settings, messages)
    except TimeoutError:
        raise ModelServiceError("MODEL_TIMEOUT", "模型响应超时，请重试或缩短问题。", 504) from None
