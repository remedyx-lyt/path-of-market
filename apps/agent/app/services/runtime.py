"""AgentRunner 各部分共用的运行边界与时间函数。"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 18
    # 包含方法、分批通读、取数、决策与写作。三份无缓存长报告实测取证已需72次；
    # 除提高长资料容量，还单独保留收尾空间，防止所有调用在正文前用完。
    max_model_calls: int = 144
    report_reserve_calls: int = 24  # 大纲、最多12节、摘要、数据表与复核，以及局部重试
    report_reserve_tokens: int = 200_000
    # 累计 token 预算。上下文上限翻倍、写作分正文与数据表两步后，单次研究约 0.9–1.3M（多数为缓存命中，约 1/50 价格）。
    max_tokens: int = 2_000_000
    max_seconds: float = 1200
    # 程序自设的单次请求文字上限（不是模型窗口；deepseek-flash 窗口 100 万 token）。2026-10-24 用户要求由 16 万翻倍。
    max_context_characters: int = 320000
    # 接近上限先摘要较早历史；仍不能腾出空间时，研究阶段停止取证、转入写作。
    # 预留量要容纳写作规则与一次工具结果；字符预算不是模型的精确token窗口。
    context_reserve_characters: int = 32000
    compaction_keep_characters: int = 48000
    compaction_chunk_characters: int = 64000
    max_compaction_chunks: int = 8
    max_compactions_per_run: int = 4
    compaction_tokens: int = 3500
    report_tokens: int = 14000
    read_characters: int = 26000
    max_visual_pages: int = 12

    @classmethod
    def for_history(cls, years):
        """容量按明确资料范围扩展，写作预留、逐批缓存与断点规则不变；不是无限重试。"""
        extra = max(0, years-2)
        return replace(cls(), max_model_calls=144+32*extra, max_tokens=2_000_000+700_000*extra,
                       max_seconds=1200+240*extra, max_steps=18+2*extra, max_visual_pages=max(12, years+4))


class BudgetStop(Exception):
    """达到步数/调用/时间/token/上下文等边界；保留部分结果并说明停止原因。"""


def now():
    return datetime.now(timezone.utc).isoformat()
