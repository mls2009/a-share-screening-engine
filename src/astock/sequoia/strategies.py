"""Daily rules adapted from sngyai/Sequoia-X, commit 444c0db (see docs/sequoia.md)."""

import operator
import re
from datetime import date, timedelta
from math import isfinite

import pandas as pd


def parameter(label, value, minimum, maximum, integer=False):
    return {"label": label, "default": value, "min": minimum, "max": maximum, "integer": integer}


CATALOG = [
    {
        "id": "turtle",
        "name": "海龟突破",
        "description": "收盘突破此前高点，普通突破要求相对放量及阳线，收盘真实涨停（含一字板）豁免这两项；仍须高于昨收，历史按首次突破前高划分阶段。",
        "parameters": {
            "window": parameter("前高窗口（日）", 20, 2, 250, True),
            "volume_window": parameter("均量窗口（日，不含当日）", 20, 2, 250, True),
            "volume_multiple": parameter("相对放量倍数下限", 1.5, 1, 20),
        },
    },
    {
        "id": "ma_volume",
        "name": "均线金叉放量",
        "description": "MA5 严格上穿 MA20，成交量超过含当日的 20 日均量。",
        "parameters": {"volume_multiple": parameter("放量倍数", 1.5, 0.1, 20)},
    },
    {
        "id": "high_flag",
        "name": "高紧旗形",
        "description": "40 日高低比 > 1.6、近 10 日振幅收窄且缩量；原规则不要求突破，也不限定低点在高点之前。",
        "parameters": {
            "rise_ratio": parameter("40 日高低比下限", 1.6, 1, 10),
            "range_ratio": parameter("10 日高低比上限", 1.15, 1, 5),
            "support_ratio": parameter("低点 / 40 日高点下限", 0.8, 0.1, 1),
            "volume_multiple": parameter("缩量倍数上限", 0.6, 0.01, 2),
        },
    },
    {
        "id": "shakeout",
        "name": "大涨后放量阴线",
        "description": "原仓库“涨停洗盘”：昨日涨幅至少 9.5%，今日放量阴线且低点不破昨收。9.5% 是固定阈值，不代表实际涨停。",
        "parameters": {
            "rise_percent": parameter("昨日涨幅下限（%）", 9.5, 0.1, 40),
            "volume_multiple": parameter("较昨日放量倍数", 2, 0.1, 20),
        },
    },
    {
        "id": "trend_drop",
        "name": "上升趋势放量大跌",
        "description": "原仓库“上升趋势跌停”：昨 MA20 > MA60，今日跌幅至少 9.5% 且放量；没有反包条件。",
        "parameters": {
            "drop_percent": parameter("跌幅下限（%）", 9.5, 0.1, 40),
            "volume_multiple": parameter("较 20 日均量倍数", 2, 0.1, 20),
        },
    },
    {
        "id": "rps",
        "name": "RPS 强势近高点",
        "description": "全市场 120 日收益百分位 ≥ 90，收盘 ≥ 近 120 日最高价的 90%；不等同于创新高。自选范围不改变 RPS 母体。",
        "parameters": {
            "percentile": parameter("RPS 下限", 90, 0, 100),
            "high_ratio": parameter("收盘 / 120 日高点下限", 0.9, 0.1, 1.5),
        },
    },
    {
        "id": "placement",
        "name": "近期定向增发",
        "description": "东方财富当前全部增发名单，按发行日期回看 7 个自然日；不是公告发布日期，仅支持今天查询。",
        "parameters": {"days": parameter("回看自然日", 7, 1, 90, True)},
    },
]
BY_ID = {item["id"]: item for item in CATALOG}
OPS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}


def defaults(identifier, overrides=None):
    return {
        **{k: v["default"] for k, v in BY_ID[identifier]["parameters"].items()},
        **(overrides or {}),
    }


def unknown(identifier, reason):
    return {
        "id": identifier,
        "name": BY_ID[identifier]["name"],
        "result": "unknown",
        "reason": reason,
        "checks": [],
    }


def valid(value):
    return isinstance(value, (int, float)) and isfinite(value)


def rps_scores(histories):
    returns = {}
    for symbol, rows in histories.items():
        if len(rows) >= 121 and all(valid(r["close"]) and r["close"] > 0 for r in rows[-121:]):
            returns[symbol] = rows[-1]["close"] / rows[-121]["close"] - 1
    return (pd.Series(returns, dtype=float).rank(method="average", pct=True) * 100).to_dict()


def evaluate(identifier, rows, parameters=None, rps=None, issuance=None, *, strict_volume=False):
    p = defaults(identifier, parameters)
    limit_breakout = identifier == "turtle" and bool(rows) and rows[-1].get("limit_state") == "up"
    n = {
        "turtle": max(int(p.get("window", 20)), 0 if limit_breakout else int(p.get("volume_window", 20))) + 1,
        "ma_volume": 21,
        "high_flag": 40,
        "shakeout": 3,
        "trend_drop": 61,
        "rps": 121,
        "placement": 1,
    }[identifier]
    if len(rows) < n:
        return unknown(identifier, f"需要 {n} 根日线，实际 {len(rows)} 根")
    rows = rows if identifier == "placement" else rows[-n:]
    fields = {
        "turtle": ["close", "high"] if limit_breakout else ["close", "high", "open", "volume"],
        "ma_volume": ["close", "volume"],
        "high_flag": ["high", "low", "volume"],
        "shakeout": ["open", "close", "low", "volume"],
        "trend_drop": ["close", "volume"],
        "rps": ["close", "high"],
        "placement": ["close"],
    }[identifier]
    fields = list(set(fields) | {"close"})
    if any(
        not valid(r.get(k)) or r[k] < 0 or (k not in ("volume", "amount") and r[k] == 0)
        for r in rows
        for k in fields
    ):
        return unknown(identifier, "窗口中有缺失、非有限值或无效价格")
    t = rows[-1]
    checks = []

    def add(label, actual, op, expected, metric="close", window=1, end=None):
        end = end or t["date"]
        result = OPS[op](actual, expected)
        checks.append(
            {
                "label": label,
                "actual": actual,
                "operator": op,
                "expected": expected,
                "result": "true" if result else "false",
                "mark": {
                    "metric": metric,
                    "timeframe": "1d",
                    "date": end,
                    "startDate": rows[max(0, len(rows) - window)]["date"],
                    "periods": window,
                    "label": f"{BY_ID[identifier]['name']} · {label}",
                    "metricLabel": label,
                },
            }
        )

    def mean(key, subset):
        return sum(r[key] for r in subset) / len(subset)

    if identifier == "turtle":
        price_window = int(p['window'])
        volume_window = int(p['volume_window'])
        add("收盘突破前高", t["close"], "gt", max(r["high"] for r in rows[-price_window-1:-1]), window=price_window+1)
        if limit_breakout:
            add("收盘真实涨停（豁免放量及阳线，含一字板）", 1, "gte", 1)
        if not limit_breakout:
            baseline = mean('volume', rows[-volume_window-1:-1])
            if baseline <= 0:
                return unknown(identifier, '此前均量为零，无法计算相对放量')
            add("当日量 / 此前均量", t['volume']/baseline, 'gte', p['volume_multiple'], 'volume', volume_window+1)
        if not limit_breakout:
            add("收盘高于开盘", t["close"], "gt", t["open"])
        add("收盘高于昨收", t["close"], "gt", rows[-2]["close"], window=2)
    elif identifier == "ma_volume":
        add(
            "昨日 MA5 < MA20",
            mean("close", rows[-6:-1]),
            "lt",
            mean("close", rows[:-1]),
            window=21,
            end=rows[-2]["date"],
        )
        add("今日 MA5 > MA20", mean("close", rows[-5:]), "gt", mean("close", rows[-20:]), window=20)
        add(
            "今日量 ≥ 含今日 20 日均量 × 倍数" if strict_volume else "今日量 > 含今日 20 日均量 × 倍数",
            t["volume"],
            "gte" if strict_volume else "gt",
            mean("volume", rows[-20:]) * p["volume_multiple"],
            "volume",
            20,
        )
    elif identifier == "high_flag":
        high = max(r["high"] for r in rows)
        add(
            "40 日最高 / 最低", high / min(r["low"] for r in rows), "gt", p["rise_ratio"], window=40
        )
        add(
            "10 日最高 / 最低",
            max(r["high"] for r in rows[-10:]) / min(r["low"] for r in rows[-10:]),
            "lt",
            p["range_ratio"],
            window=10,
        )
        add(
            "10 日低点守住高位",
            min(r["low"] for r in rows[-10:]),
            "gte",
            high * p["support_ratio"],
            window=10,
        )
        add(
            "今日量 < 此前 20 日均量 × 倍数",
            t["volume"],
            "lt",
            mean("volume", rows[-21:-1]) * p["volume_multiple"],
            "volume",
            21,
        )
    elif identifier == "shakeout":
        add(
            f"昨日收盘 ≥ 前收 × (1 + {p['rise_percent']}%）",
            rows[-2]["close"],
            "gte",
            rows[-3]["close"] * (1 + p["rise_percent"] / 100),
            window=3,
            end=rows[-2]["date"],
        )
        add("今日阴线", t["close"], "lt", t["open"])
        add(
            "今日量 > 昨日量 × 倍数",
            t["volume"],
            "gt",
            rows[-2]["volume"] * p["volume_multiple"],
            "volume",
            2,
        )
        add("今日低点 ≥ 昨收", t["low"], "gte", rows[-2]["close"], window=2)
    elif identifier == "trend_drop":
        add(
            "昨日 MA20 > MA60",
            mean("close", rows[-21:-1]),
            "gt",
            mean("close", rows[:-1]),
            window=61,
            end=rows[-2]["date"],
        )
        add(
            f"今日收盘 ≤ 昨收 × (1 - {p['drop_percent']}%）",
            t["close"],
            "lte",
            rows[-2]["close"] * (1 - p["drop_percent"] / 100),
            window=2,
        )
        add(
            "今日量 ≥ 含今日 20 日均量 × 倍数" if strict_volume else "今日量 > 含今日 20 日均量 × 倍数",
            t["volume"],
            "gte" if strict_volume else "gt",
            mean("volume", rows[-20:]) * p["volume_multiple"],
            "volume",
            20,
        )
    elif identifier == "rps":
        if rps is None:
            return unknown(identifier, "全市场 120 日收益不足，无法计算 RPS")
        add("全市场 RPS 百分位", rps, "gte", p["percentile"], window=121)
        add(
            "收盘接近 120 日高点",
            t["close"],
            "gte",
            max(r["high"] for r in rows[-120:]) * p["high_ratio"],
            window=120,
        )
    elif identifier == "placement":
        # This is an event marker on an actual trading candle, not a price condition.
        check = {
            "label": "近期定向增发发行日期",
            "actual": issuance,
            "expected": f"截至查询日近 {p['days']} 个自然日",
            "operator": "in",
            "result": "true" if issuance else "false",
        }
        if issuance and issuance <= t["date"]:
            candle = next((r for r in rows if r["date"] >= issuance), rows[-1])
            check["mark"] = {
                "metric": "close",
                "timeframe": "1d",
                "date": candle["date"],
                "periods": 1,
                "label": f"定增发行 {issuance}（事件标记，不是价格形态）",
                "metricLabel": "定增发行",
            }
        checks.append(check)
    return {
        "id": identifier,
        "name": BY_ID[identifier]["name"],
        "result": "true" if all(c["result"] == "true" for c in checks) else "false",
        "checks": checks,
    }


def placement_dates(records, as_of: date, days: int):
    result = {}
    for row in records:
        if row.get("发行方式") != "定向增发":
            continue
        try:
            issued = date.fromisoformat(str(row["发行日期"])[:10])
        except (ValueError, KeyError):
            continue
        code = re.search(r"\d{6}", str(row.get("股票代码", "")))
        if code and as_of - timedelta(days=days) <= issued <= as_of:
            symbol = code.group()
            result[symbol] = max(result.get(symbol, ""), issued.isoformat())
    return result
