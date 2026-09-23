from pydantic import BaseModel, ConfigDict

from astock.domain.market import Timeframe
from astock.screening.evaluator import TruthValue, evaluate_tree
from astock.screening.models import Node


class WaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tree: Node


def scan_waves(rows: list[dict], request: WaveRequest) -> dict:
    """Evaluate newest-first daily history without exposing later rows to a condition."""
    matches = []
    unknown = matched_days = 0
    interval = None
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        result = evaluate_tree(request.tree, {Timeframe.DAY: rows[index:]}).result
        if result != TruthValue.TRUE:
            unknown += result == TruthValue.UNKNOWN
            interval = None
            continue
        matched_days += 1
        stamp, price = str(row["feature_date"]), row.get("close")
        if interval is None:
            interval = {"start": stamp, "end": stamp, "days": 0,
                        "start_price": price, "end_price": price, "gain": None}
            matches.append(interval)
        interval.update(end=stamp, end_price=price, days=interval["days"] + 1)
        start_price = interval["start_price"]
        interval["gain"] = ((price / start_price - 1) * 100
                            if price is not None and start_price is not None and start_price > 0 else None)
    return {"matches": list(reversed(matches)), "total": len(matches), "matched_days": matched_days,
            "bars": len(rows), "unknown": unknown,
            "start": str(rows[-1]["feature_date"]) if rows else None,
            "end": str(rows[0]["feature_date"]) if rows else None}
