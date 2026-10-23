"""仅 Python 读取根目录 .env；每次调用重新读取，密钥不进入响应或日志。"""

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ModelServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class ModelSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60
    max_tokens: int = 1800


def load_model_settings() -> ModelSettings:
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

    def setting(name: str, default: str = "") -> str:
        return os.environ.get(name, values.get(name, default)).strip()

    key = setting("DEEPSEEK_API_KEY")
    if not key or key in {"你的密钥", "your-api-key", "<your api key>"}:
        raise ModelServiceError("MODEL_NOT_CONFIGURED", "请在项目根目录 .env 的 DEEPSEEK_API_KEY= 后填写密钥并保存。")
    try:
        base_url = setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        url = urlsplit(base_url)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
            or any(char.isspace() or ord(char) < 32 for char in base_url)
            or not (url.scheme == "https" or url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError
        _ = url.port
        model = setting("DEEPSEEK_MODEL", "deepseek-flash")
        timeout = float(setting("LLM_TIMEOUT_SECONDS", "60"))
        max_tokens = int(setting("LLM_MAX_TOKENS", "1800"))
        if not model or len(model) > 120 or not 0 < timeout <= 60 or not 64 <= max_tokens <= 4096:
            raise ValueError
    except ValueError:
        raise ModelServiceError("MODEL_CONFIG_ERROR", "模型配置无效，请检查地址、模型名称、等待上限（不超过 60 秒）和输出长度。") from None
    return ModelSettings(key, base_url, model, timeout, max_tokens)
