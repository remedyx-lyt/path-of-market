"""F8：默认五年、远古十年的年报范围；用户明确指定的短专题仍优先。"""
import re


def history_count(request):
    question = request.question
    numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    # 只接受明确的研究年限；“未来两年”或“增长两年”不触发。
    match = re.search(r"(?:最近|过去|近)\s*(10|[1-9]|[一二两三四五六七八九十])\s*(?:个)?\s*(?:会计)?(?:年|份年报)", question)
    if match:
        raw = match[1]
        return int(raw) if raw.isdigit() else numbers[raw]
    return 10 if "ancient" in request.omens else 5


def history_scope(request):
    count = history_count(request)
    latest = request.as_of_date.year - 1
    return {"count": count, "years": list(range(latest-count+1, latest+1)),
            "instruction": "按截止日前已披露完整年报逐年取证；未找到的年度明确缺口。会计年度不是披露年份，最新定期报告另查。年报年限与行情区间分别选择。"}
