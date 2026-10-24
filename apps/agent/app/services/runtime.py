"""AgentRunner 各部分共用的运行边界与时间函数。"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 18
    max_model_calls: int = 72
    # 累计 token 预算。上下文上限翻倍、写作分正文与数据表两步后，单次研究约 0.9–1.3M（多数为缓存命中，约 1/50 价格）。
    max_tokens: int = 2_000_000
    max_seconds: float = 1200
    # 程序自设的单次请求文字上限（不是模型窗口；deepseek-flash 窗口 100 万 token）。2026-10-24 用户要求由 16 万翻倍。
    max_context_characters: int = 320000
    # 决策上下文超过 max_context_characters - context_reserve_characters 时停止取证、转入写作（参照 Pi 的 reserveTokens）；
    # 预留量要容纳写作规则与一次工具结果，避免写作请求本身越过上限。
    context_reserve_characters: int = 32000
    report_tokens: int = 14000
    read_characters: int = 26000
    max_visual_pages: int = 12


class BudgetStop(Exception):
    """达到步数/调用/时间/token/上下文等边界；保留部分结果并说明停止原因。"""


def now():
    return datetime.now(timezone.utc).isoformat()
