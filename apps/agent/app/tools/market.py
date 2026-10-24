"""日线行情 Provider 与确定性计算；供应商返回字段与模型解释分开。"""

from datetime import date
import math
import statistics
from urllib.parse import urlencode

from app.tools.cninfo import PublicTransport, utc_now
from app.tools.contracts import Arguments, ToolError
from pydantic import Field, model_validator


class MarketArguments(Arguments):
    company: str = Field(min_length=1, max_length=120)
    start_date: str = Field(alias="startDate", description="区间起始日期 YYYY-MM-DD。")
    end_date: str = Field(alias="endDate", description="不晚于研究截止日的 YYYY-MM-DD 日期。")

    @model_validator(mode="after")
    def check_dates(self):
        try:
            start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
            if (
                start.isoformat() != self.start_date
                or end.isoformat() != self.end_date
                or not start <= end <= date.today()
                or (end - start).days > 1100
            ):
                raise ValueError
        except ValueError:
            raise ValueError("需要有效的起止日期；最多约三年，不晚于今天") from None
        return self


class MarketTransport(PublicTransport):
    hosts = {"push2his.eastmoney.com", "web.ifzq.gtimg.cn"}


def parse_number(value, *, positive=False):
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError
    return number


def validate_rows(rows: list[dict], start: str, end: str) -> list[dict]:
    found = {}
    try:
        for row in rows:
            day = date.fromisoformat(row["date"]).isoformat()
            if not start <= day <= end:
                continue
            item = {"date": day, **{k: parse_number(row[k], positive=k != "volume") for k in ("open", "close", "high", "low", "volume")}}
            if item["low"] > min(item["open"], item["close"]) or item["high"] < max(item["open"], item["close"]):
                raise ValueError
            if row.get("amount") is not None:
                item["amount"] = parse_number(row["amount"])
            if day in found and found[day] != item:
                raise ValueError
            found[day] = item
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ToolError("MARKET_INVALID_RESPONSE", "行情日期、数值或 OHLC 关系异常，未用于分析。") from None
    result = sorted(found.values(), key=lambda r: r["date"])
    if len(result) < 2:
        raise ToolError("MARKET_NO_DATA", "指定区间没有足够日线数据。")
    return result


class MarketProvider:
    def __init__(self, transport=None):
        self.transport = transport or MarketTransport()

    def eastmoney(self, company: dict, start: str, end: str, adjusted: bool):
        params = {
            "secid": ("1." if company["exchange"] == "SSE" else "0.") + company["code"],
            "klt": "101",
            "fqt": "2" if adjusted else "0",
            "beg": start.replace("-", ""),
            "end": end.replace("-", ""),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urlencode(params)
        result = self.transport.get_json(url)
        if not isinstance(result, dict):
            raise ToolError("MARKET_INVALID_RESPONSE", "行情来源返回格式无效。")
        data = result.get("data") or {}
        if not isinstance(data, dict) or str(data.get("code")) != company["code"] or not isinstance(data.get("klines"), list):
            raise ToolError("MARKET_INVALID_RESPONSE", "行情来源没有返回对应证券的数据。")
        try:
            rows = []
            for line in data["klines"]:
                fields = line.split(",")
                rows.append(dict(zip(("date", "open", "close", "high", "low", "volume", "amount"), fields, strict=True)))
        except (ValueError, TypeError, AttributeError):
            raise ToolError("MARKET_INVALID_RESPONSE", "行情字段格式发生变化。") from None
        return validate_rows(rows, start, end), url

    def tencent(self, company: dict, start: str, end: str, adjusted: bool):
        symbol = ("sh" if company["exchange"] == "SSE" else "sz") + company["code"]
        mode = "hfq" if adjusted else ""
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urlencode({"param": f"{symbol},day,{start},{end},800,{mode}"})
        result = self.transport.get_json(url)
        if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
            raise ToolError("MARKET_INVALID_RESPONSE", "备用行情来源返回格式无效。")
        stock = result["data"].get(symbol) or {}
        key = "hfqday" if adjusted else "day"
        if not isinstance(stock.get(key), list):
            raise ToolError("MARKET_INVALID_RESPONSE", "备用行情来源缺少指定复权口径。")
        rows = []
        try:
            for row in stock[key]:
                rows.append(dict(zip(("date", "open", "close", "high", "low", "volume"), row[:6], strict=True)))
        except (ValueError, TypeError):
            raise ToolError("MARKET_INVALID_RESPONSE", "备用行情来源格式异常。") from None
        return validate_rows(rows, start, end), url

    def history(self, company: dict, start: str, end: str) -> dict:
        failures = []
        for name, fetch in (("eastmoney", self.eastmoney), ("tencent", self.tencent)):
            try:
                raw, raw_url = fetch(company, start, end, False)
                adjusted, adjusted_url = fetch(company, start, end, True)
                by_day = {r["date"]: r for r in adjusted}
                if set(r["date"] for r in raw) != set(by_day):
                    raise ToolError("MARKET_DATE_MISMATCH", "不复权与后复权交易日不一致，未混合计算。")
                series = [{**r, "adjustedClose": by_day[r["date"]]["close"]} for r in raw]
                return {
                    "company": company,
                    "provider": name,
                    "currency": "CNY",
                    "frequency": "daily",
                    "volumeUnit": "手（100股）",
                    "amountUnit": "元",
                    "adjustment": "hfq",
                    "requestedStart": start,
                    "requestedEnd": end,
                    "actualStart": series[0]["date"],
                    "actualEnd": series[-1]["date"],
                    "retrievedAt": utc_now(),
                    "series": series,
                    "sourceUrls": [raw_url, adjusted_url],
                    "metrics": compute_metrics(series),
                    "providerFailures": failures,
                    "limitations": [
                        "日线不是实时行情；当日未收盘时日线字段可能变化。",
                        "实际价格使用不复权字段，区间变化与回撤使用同源后复权收盘序列；复权价格不是实际成交价。",
                        "复权因子按供应商本次返回口径，未取得历史时点因子快照，不作为严格时点回测。",
                        "价格与经营变化并列观察不证明因果，不据此给出买卖指令。",
                    ],
                }
            except ToolError as error:
                failures.append({"provider": name, "code": error.code})
        raise ToolError("MARKET_UNAVAILABLE", "主备行情来源均未取得可用数据。", {"sources": failures})


def compute_metrics(series):
    closes = [r["adjustedClose"] for r in series]
    peak, drawdown = closes[0], 0.0
    peak_date = series[0]["date"]
    worst_peak, worst_trough = peak_date, peak_date
    for row in series:
        value = row["adjustedClose"]
        if value > peak:
            peak, peak_date = value, row["date"]
        change = value / peak - 1
        if change < drawdown:
            drawdown, worst_peak, worst_trough = change, peak_date, row["date"]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    month_ends = {}
    for row in series:
        month_ends[row["date"][:7]] = row
    monthly, previous = [], closes[0]
    for month, row in month_ends.items():
        monthly.append(
            {
                "month": month,
                "date": row["date"],
                "adjustedClose": row["adjustedClose"],
                "changePct": round((row["adjustedClose"] / previous - 1) * 100, 4),
            }
        )
        previous = row["adjustedClose"]
    return {
        "tradingDays": len(series),
        "firstRawClose": series[0]["close"],
        "lastRawClose": series[-1]["close"],
        "adjustedChangePct": round((closes[-1] / closes[0] - 1) * 100, 4),
        "maxCloseDrawdownPct": round(drawdown * 100, 4),
        "drawdownPeakDate": worst_peak,
        "drawdownTroughDate": worst_trough,
        "annualizedDailyVolatilityPct": round(statistics.stdev(returns) * math.sqrt(252) * 100, 4) if len(returns) > 1 else None,
        "adjustedMa20": round(statistics.mean(closes[-20:]), 4) if len(closes) >= 20 else None,
        "adjustedMa60": round(statistics.mean(closes[-60:]), 4) if len(closes) >= 60 else None,
        "monthly": monthly,
        "formula": "区间变化=(末/初-1)×100%；收盘回撤=min(当日/此前最高收盘-1)×100%；波动率=日收益样本标准差×sqrt(252)",
    }
