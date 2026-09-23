"""Freeze chart evidence from the successful leaves of a saved screening run."""
import re
from astock.features.chart_shapes import SHAPE_LABELS

from astock.domain.market import Timeframe
from astock.screening.evaluator import TruthValue, evaluate_tree
from astock.screening.models import ConditionNode
from astock.features.price_action import PA_LABELS


def entry_histories(histories: dict, mode: str, as_of, snapshot: dict) -> dict:
    """Keep intraday evidence independent of subsequently downloaded closing bars."""
    if mode != "live":
        return histories
    result = {timeframe: [row for row in rows if row["feature_date"] < as_of]
              for timeframe, rows in histories.items()}
    result[Timeframe.DAY] = [{**snapshot, "feature_date": as_of}, *result.get(Timeframe.DAY, [])]
    return result


def condition_marks(tree: dict, explanation: dict, histories: dict) -> list[dict]:
    marks = []
    active_path = "root"

    def add(metric, timeframe, rows, start, end, label):
        if not rows or start >= len(rows):
            return
        end = min(end, len(rows) - 1)
        marks.append({"metric": metric, "timeframe": timeframe, "path": active_path,
                      "date": str(rows[start]["feature_date"]),
                      "startDate": str(rows[end]["feature_date"]),
                      "periods": end - start + 1, "label": label})

    def visit(node, result, path="root"):
        nonlocal active_path
        active_path = path
        if result["result"] != "true" or node.get("logic") == "not":
            return
        if node["kind"] == "group":
            for index, (child, child_result) in enumerate(zip(node["children"], result["children"], strict=True)):
                visit(child, child_result, f"{path}.children[{index}]")
            return
        metric, timeframe = node["metric"], node["timeframe"]
        rows = histories.get(Timeframe(timeframe), [])
        label = f"实际 {result.get('actual')}，期望 {result.get('expected')}"
        if not rows:
            return
        if metric == "vacuum_reentry_ma120_within_250":
            for hit in rows[0].get("vacuum_year_hits", []):
                zone = hit["zone"]
                marks.append({"metric": "close", "timeframe": timeframe, "path": active_path,
                              "date": zone["end"], "startDate": zone["start"], "periods": 1,
                              "priceLow": zone["lower"], "priceHigh": zone["upper"],
                              "label": f"缩量急跌区间 {zone['lower']:.2f}～{zone['upper']:.2f}；{zone['confirmed']}确认；量比{zone.get('volume_ratio', 0):.2f}"})
                marks.append({"metric": "close", "timeframe": timeframe, "path": active_path,
                              "date": hit["date"], "periods": 1,
                              "label": f"缩量急跌区间重入；收盘{hit['close']:.2f} > 当日MA120 {hit['ma120']:.2f}"})
            return
        if metric.startswith("vacuum_"):
            zone = rows[0].get("vacuum_zone")
            if zone:
                marks.append({"metric": "close", "timeframe": timeframe, "path": active_path,
                              "date": zone["end"], "startDate": zone["start"], "periods": rows[0].get("vacuum_days", 1),
                              "priceLow": zone["lower"], "priceHigh": zone["upper"],
                              "label": f"缩量急跌区间 {zone['lower']:.2f}～{zone['upper']:.2f}；{zone['confirmed']}确认；量比{zone.get('volume_ratio', 0):.2f}"})
                if rows[0].get("vacuum_reentry"):
                    add("close", timeframe, rows, 0, 0, "跌出缩量急跌区间后重新进入")
            return
        if metric in {"limit_up_count_5_max_60", "limit_up_burst_5_count_60"}:
            for index in range(min(56, len(rows) - 4)):
                count = sum(bool(row.get("is_limit_up")) for row in rows[index:index + 5])
                threshold = 2 if metric == "limit_up_burst_5_count_60" else result.get("actual")
                if count >= (threshold or 1):
                    add("close", timeframe, rows, index, index + 4, label)
            return
        if metric == "return_10_max_60":
            candidates = [(row.get("return_10"), index) for index, row in enumerate(rows[:50])
                          if row.get("return_10") is not None and index + 10 < len(rows)]
            if candidates:
                _, index = max(candidates)
                add("close", timeframe, rows, index, index + 10, label)
            return
        if node["operator"] in {"continuous", "at_least"}:
            simple = ConditionNode.model_validate({**node, "operator": node.get("comparison_operator", "gt"), "lookback": None, "occurrences": None})
            for index in range(min(node.get("lookback") or node.get("occurrences") or 1, len(rows))):
                shifted = {key: [row for row in values if row["feature_date"] <= rows[index]["feature_date"]]
                           for key, values in histories.items()}
                if evaluate_tree(simple, shifted).result == TruthValue.TRUE:
                    add(metric, timeframe, rows, index, index, label)
                    right = node.get("right", {})
                    if right.get("kind") == "metric":
                        other = histories.get(Timeframe(right["timeframe"]), [])
                        other = [row for row in other if row["feature_date"] <= rows[index]["feature_date"]]
                        add(right["metric"], right["timeframe"], other, 0, 0, label)
            return
        if metric in SHAPE_LABELS:
            kind = metric.split('_')[1]
            names = {'ascending':'上升三角形','descending':'下降三角形','range':'震荡区间'}
            for hit in rows[0].get('chart_shape_hits', []):
                if hit['kind'] != kind:
                    continue
                marks.append(dict(metric='close',timeframe=timeframe,path=active_path,
                                  date=hit['end_date'],startDate=hit['start_date'],periods=hit['bars'],
                                  label=f"{names[kind]} · {hit['start_date']}～{hit['end_date']} · {hit['bars']}根；{hit['confirmed_date']}确认（不要求突破）",
                                  shape=hit))
            return
        if metric == "body_low_retest":
            stamp = str(rows[0]["feature_date"])
            for level in rows[0].get("body_low_retest_levels", []):
                label = f"两年实体{'最低' if level['rank']==1 else '次低'}点 {level['price']:.3f}；{level['date']}，{level['confirmed_date']}确认；±5%回访区域"
                marks.append(dict(metric="close",timeframe=timeframe,path=active_path,date=stamp,
                                  startDate=level['date'],periods=1,priceLow=level['lower'],
                                  priceHigh=level['upper'],label=label))
            if rows[0].get("body_low_retest_hits"):
                ranks = "、".join('最低点' if x['rank']==1 else '次低点' for x in rows[0]['body_low_retest_hits'])
                marks.append(dict(metric="close",timeframe=timeframe,path=active_path,date=stamp,
                                  startDate=stamp,periods=1,label=f"实体低点回访：{ranks}±5%（含影线）"))
            return
        if metric in {"pa_bull_within_250", "pa_bear_within_250", "pw_bull_within_156"}:
            direction = "bear" if metric == "pa_bear_within_250" else "bull"
            prefix = "pw" if metric.startswith("pw_") else "pa"
            for hit in rows[0].get(f"{prefix}_{direction}_year_hits", []):
                details = "、".join(PA_LABELS[key].split("：",1)[-1] for key,value in hit["details"].items() if value)
                if prefix == "pw":
                    details = details.replace("此前已结束周线", "此前已结束月线")
                marks.append({"metric":"close", "timeframe":timeframe, "path":active_path,
                              "date":hit["date"], "startDate":hit.get("start_date", hit["date"]), "periods":hit.get("bars", 1),
                              "label":f"裸K：{'双K合成·' if hit.get('bars', 1) == 2 else ''}{'看涨' if direction == 'bull' else '看跌'}Pinbar · {hit['date']}；{details}"})
                zone = hit.get("zone")
                if zone:
                    marks.append({"metric":"close", "timeframe":timeframe, "path":active_path,
                                  "date":hit["date"], "startDate":zone.get("anchor_date",hit["date"]), "periods":1,
                                  "priceLow":zone["lower"], "priceHigh":zone["upper"],
                                  "label":f"{hit['date']}信号对应的{'260周历史月线' if prefix == 'pw' else '一年区间'}{'底部支撑' if direction == 'bull' else '顶部压力'}"})
            return
        if metric in PA_LABELS:
            add("close", timeframe, rows, 0, 1 if metric.startswith("pa2_") else 0, f"{PA_LABELS[metric]}：{result.get('actual')}")
            direction = "bull" if "_bull_" in metric else "bear"
            prefix = "pa2" if metric.startswith("pa2_") else "pa"
            zone = rows[0].get(f"{prefix}_{direction}_zone") if metric.endswith(("key_level", "false_break")) else None
            if zone:
                marks.append({"metric": "close", "timeframe": timeframe, "path": active_path,
                              "date": str(rows[0]["feature_date"]), "startDate": zone.get("anchor_date", str(rows[0]["feature_date"])), "periods": 1,
                              "priceLow": zone["lower"], "priceHigh": zone["upper"],
                              "label": f"一年大区间边界；{zone.get('anchor_date', '')}转折，{zone.get('confirmed_date', '')}确认；信号前已确认{'支撑' if direction == 'bull' else '压力'}带"})
            return
        change = re.fullmatch(r"return_(\d+)", metric)
        if change:
            add("close", timeframe, rows, 0, int(change[1]), label)
            return
        flatness = re.fullmatch(r"ma_(\d+)_(?:slope_abs|range)_5", metric)
        if flatness:
            add(f"ma_{flatness[1]}", timeframe, rows, 0, 4, label)
        if metric == "ma_10_20_distance":
            for average in ("ma_10", "ma_20"):
                add(average, timeframe, rows, 0, 0, label)
        pattern_periods = {"bullish_engulfing": 2, "bearish_engulfing": 2, "piercing": 2,
                           "dark_cloud_cover": 2, "morning_star": 3, "evening_star": 3,
                           "three_white_soldiers": 3, "three_black_crows": 3}
        pattern = node.get("right", {}).get("value")
        span = max((pattern_periods.get(value, 1) for value in (pattern if isinstance(pattern, list) else [pattern])), default=1) if metric == "pattern_type" else 1
        add(metric, timeframe, rows, 0, span - 1, label)
        right = node.get("right", {})
        if right.get("kind") == "metric":
            other = histories.get(Timeframe(right["timeframe"]), [])
            add(right["metric"], right["timeframe"], other, 0, 0, label)

    visit(tree, explanation)
    return marks
