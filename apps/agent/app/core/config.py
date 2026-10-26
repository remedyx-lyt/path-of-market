"""仅 Python 读取根目录 .env；每次调用重新读取，密钥不进入响应或日志。

模型服务商用“档案”描述差异（参考 Pi pi-ai 的 openai-completions compat 字段：maxTokensField、thinkingFormat 等）：
用户只需在 .env 填 LLM_PROVIDER / LLM_API_KEY / LLM_MODEL（兼容服务另填 LLM_BASE_URL）。旧的 DEEPSEEK_* 写法继续有效。
本版只走 Chat Completions 格式；只能经 OpenAI Responses 接口调工具的模型（如 GPT-6 Astra）尚不支持。
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ModelServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


DEFAULT_VISION_MODELS = ("deepseek-flash", "deepseek-v4-flash-vision-exp")


@dataclass(frozen=True)
class ProviderProfile:
    """一家服务商与 OpenAI Chat Completions 格式的差异。"""

    label: str
    base_url: str | None  # None：必须由 LLM_BASE_URL 提供
    default_model: str | None  # None：必须由 LLM_MODEL 提供
    key_names: tuple[str, ...]  # LLM_API_KEY 之外，按顺序兼容的旧密钥变量
    legacy_prefix: str | None  # 旧变量前缀（DEEPSEEK_BASE_URL / _MODEL / _VISION_MODELS）
    max_tokens_field: str  # 输出上限参数名：OpenAI 新模型只认 max_completion_tokens
    reasoning_mode: str  # deepseek：发 thinking.disabled；reasoning_effort：发 reasoning_effort；none：不发
    default_reasoning_effort: str = ""
    default_vision: tuple[str, ...] = ()


PROVIDERS = {
    "deepseek": ProviderProfile("DeepSeek", "https://api.deepseek.com", "deepseek-flash", ("DEEPSEEK_API_KEY",), "DEEPSEEK",
                                "max_tokens", "deepseek", default_vision=DEFAULT_VISION_MODELS),
    # OpenAI 自 GPT-5.4 起，Chat Completions 里调工具要求 reasoning_effort=none（官方迁移指南）；不支持该参数的旧模型填 LLM_REASONING_EFFORT=omit。
    "openai": ProviderProfile("OpenAI", "https://api.openai.com/v1", None, ("OPENAI_API_KEY",), None,
                              "max_completion_tokens", "reasoning_effort", default_reasoning_effort="none"),
    "openai-compatible": ProviderProfile("OpenAI 兼容服务", None, None, (), None, "max_tokens", "none"),
}


@dataclass(frozen=True)
class ModelSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60
    max_tokens: int = 1800
    # 声明支持图片输入的模型；原页视觉工具只对这些模型开放。可用 LLM_VISION_MODELS（或旧的 DEEPSEEK_VISION_MODELS）逗号分隔覆盖。
    vision_models: tuple[str, ...] = DEFAULT_VISION_MODELS
    # 写作与复核一次输出整篇报告（多预兆时上万 token），比研究轮次慢得多；单独设等待上限，整个任务仍受总时间预算约束。
    report_timeout_seconds: float = 180
    # 通读笔记有独立输出预算，不再受简单“模型思路”报告的 1800 token 上限影响。
    reading_max_tokens: int = 3600
    provider: str = "deepseek"
    max_tokens_field: str = "max_tokens"
    reasoning_mode: str = "deepseek"
    reasoning_effort: str = ""


def read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, separator, value = line.partition("=")
                if separator:
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    values[name.strip()] = value
    except (OSError, UnicodeError):
        raise ModelServiceError("MODEL_CONFIG_ERROR", "无法读取根目录 .env，请检查文件权限和 UTF-8 编码。") from None
    return values


def load_model_settings() -> ModelSettings:
    values = read_env_file()

    def setting(name: str, default: str = "") -> str:
        return os.environ.get(name, values.get(name, default)).strip()

    provider = setting("LLM_PROVIDER", "deepseek").lower()
    profile = PROVIDERS.get(provider)
    if profile is None:
        raise ModelServiceError("MODEL_CONFIG_ERROR", "LLM_PROVIDER 只能是 " + "、".join(PROVIDERS) + "。")

    def legacy(suffix: str, default: str = "") -> str:
        """LLM_* 优先；DeepSeek 继续认旧的 DEEPSEEK_* 变量。"""
        value = setting("LLM_" + suffix)
        if not value and profile.legacy_prefix:
            value = setting(f"{profile.legacy_prefix}_{suffix}")
        return value or default

    key = setting("LLM_API_KEY") or next((v for name in profile.key_names if (v := setting(name))), "")
    key_hint = "LLM_API_KEY" + "".join(f"（或 {name}）" for name in profile.key_names)
    if not key or key in {"你的密钥", "your-api-key", "<your api key>"}:
        raise ModelServiceError("MODEL_NOT_CONFIGURED", f"请在项目根目录 .env 的 {key_hint}= 后填写{profile.label}密钥并保存。")
    base_url = legacy("BASE_URL", profile.base_url or "").rstrip("/")
    model = legacy("MODEL", profile.default_model or "")
    if not base_url or not model:
        missing = "、".join(n for n, v in [("LLM_BASE_URL", base_url), ("LLM_MODEL", model)] if not v)
        raise ModelServiceError("MODEL_NOT_CONFIGURED", f"使用{profile.label}时请在 .env 填写 {missing}。")
    try:
        url = urlsplit(base_url)
        if (
            not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or any(char.isspace() or ord(char) < 32 for char in base_url)
            or not (url.scheme == "https" or url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})
        ):
            raise ValueError
        _ = url.port
        timeout = float(setting("LLM_TIMEOUT_SECONDS", "60"))
        report_timeout = float(setting("LLM_REPORT_TIMEOUT_SECONDS", "180"))
        max_tokens = int(setting("LLM_MAX_TOKENS", "1800"))
        reading_tokens = int(setting("LLM_READING_MAX_TOKENS", "3600"))
        vision = tuple(v.strip() for v in legacy("VISION_MODELS", ",".join(profile.default_vision)).split(",") if v.strip())
        max_tokens_field = setting("LLM_MAX_TOKENS_FIELD", profile.max_tokens_field)
        effort = setting("LLM_REASONING_EFFORT", profile.default_reasoning_effort)
        effort = "" if effort == "omit" else effort
        if any(len(v) > 120 for v in vision) or max_tokens_field not in {"max_tokens", "max_completion_tokens"} or len(effort) > 20:
            raise ValueError
        if (len(model) > 120 or not 0 < timeout <= 60 or not timeout <= report_timeout <= 600
                or not 64 <= max_tokens <= 4096 or not 512 <= reading_tokens <= 8192):
            raise ValueError
    except ValueError:
        raise ModelServiceError(
            "MODEL_CONFIG_ERROR", "模型配置无效，请检查地址、模型名称、等待上限和输出长度（阅读笔记 512–8192 token）。"
        ) from None
    return ModelSettings(key, base_url, model, timeout, max_tokens, vision, report_timeout, reading_tokens,
                         provider, max_tokens_field, profile.reasoning_mode, effort)
