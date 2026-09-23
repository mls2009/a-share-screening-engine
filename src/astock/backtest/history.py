from astock.features.chart_shapes import SHAPE_LABELS, chart_shape_features
from bisect import bisect_right
from datetime import date

import pandas as pd

from astock.backtest.engine import _close_at, _frame, _records
from astock.backtest.models import _tree_timeframes
from astock.data.service import MarketDataService
from astock.domain.market import Timeframe
from astock.features.patterns import detect_patterns
from astock.features.technical import compute_burst_features
from astock.features.zones import detect_zones
from astock.features.vacuum import VACUUM_METRICS, vacuum_features
from astock.features.price_action import PA_METRICS, price_action_features, weekly_price_action_features
from astock.screening.service import _requirements


def condition_history(request, database, bar_store, calendar):
    """Prepare each condition timeframe, then expose only bars closed by the signal time."""
    frames = _tree_timeframes(request.entry_tree) | _tree_timeframes(request.exit_tree)
    keys = _requirements(request.entry_tree)[2] | _requirements(request.exit_tree)[2]
    limit = max(_requirements(request.entry_tree)[1], _requirements(request.exit_tree)[1])
    histories = {}
    for symbol in request.symbols:
        identity = database.connection.execute("select board, listed_on from symbols where symbol = ?", [symbol]).fetchone()
        daily = [bar for bar in bar_store.read_range(symbol, Timeframe.DAY, request.adjustment, date.min, request.end)
                 if bar.is_final and bar.timestamp.date() <= request.end]
        dates = sorted({bar.timestamp.date() for bar in daily})
        states = {row[0]: row[1:] for row in database.connection.execute(
            "select trade_date, is_st, is_suspended, previous_close, limit_up from security_status where symbol = ? and trade_date <= ?",
            [symbol, request.end],
        ).fetchall()}
        for timeframe in frames:
            base = Timeframe.MIN_5 if timeframe.value.endswith("m") and timeframe != Timeframe.MONTH else Timeframe.DAY
            source = daily if base == Timeframe.DAY else [bar for bar in bar_store.read_range(symbol, base, request.adjustment, date.min, request.end) if bar.is_final and bar.timestamp.date() <= request.end]
            bars = [bar for bar in MarketDataService.derive(source, timeframe, calendar=calendar or None) if bar.is_final]
            if not bars:
                histories[symbol, timeframe] = ([], [])
                continue
            records = _records(bars)
            if timeframe == Timeframe.DAY and keys & VACUUM_METRICS:
                for row, derived in zip(records, vacuum_features(records), strict=True):
                    row.update(derived)
            if timeframe == Timeframe.DAY and keys & PA_METRICS:
                for row, derived in zip(records, price_action_features(records, include_year=True), strict=True):
                    row.update(derived)
            if timeframe == Timeframe.WEEK and 'pw_bull_within_156' in keys:
                for row, derived in zip(records, weekly_price_action_features(records, _records(daily)), strict=True):
                    row.update(derived)
            if timeframe == Timeframe.DAY and keys & SHAPE_LABELS.keys():
                for row, derived in zip(records, chart_shape_features(records), strict=True):
                    row.update(derived)
            frame = _frame(bars)
            if timeframe == Timeframe.DAY and keys & {"return_10_max_60", "limit_up_count_5_max_60", "limit_up_burst_5_count_60"}:
                thresholds = [((state[3] / state[2] - 1) * 100 if state and state[2] and state[3] is not None else None)
                              for bar in bars for state in [states.get(bar.timestamp.date())]]
                burst = compute_burst_features(pd.DataFrame(records), pd.Series(thresholds, dtype=float))
                for index, row in enumerate(records):
                    for key in ("return_10_max_60", "limit_up_count_5_max_60", "limit_up_burst_5_count_60"):
                        value = burst.iloc[index][key]
                        missing_limits = key != "return_10_max_60" and any(value is None for value in thresholds[max(0, index - 59):index + 1])
                        row[key] = None if pd.isna(value) or missing_limits else float(value)
            for index, (bar, row) in enumerate(zip(bars, records, strict=True)):
                day = bar.timestamp.date()
                state = states.get(day)
                row.update(board=identity[0] if identity else None, is_st=state[0] if state else None,
                           is_suspended=state[1] if state else None)
                listed = identity[1] if identity else None
                count = bisect_right(dates, day) - bisect_right(dates, listed) + 1 if listed and dates and dates[0] == listed else None
                row.update(listing_trade_days=count, listing_stage=None if count is None else "new" if count <= 30 else "secondary_new" if count <= 250 else "established",
                           is_new=None if count is None else count <= 30,
                           is_secondary_new=None if count is None else 30 < count <= 250)
                if keys & {"pattern_type", "pattern_strength"}:
                    events = detect_patterns(frame.iloc[max(0, index - 3):index + 1])
                    current = [event for event in events if event.event_date == day]
                    row["pattern_type"] = [event.pattern_type for event in current]
                    row["pattern_strength"] = max((event.strength for event in current), default=None)
                if keys & {"support_distance", "resistance_distance"}:
                    zones = detect_zones(frame.iloc[:index + 1], as_of=day, timeframe=timeframe)
                    for kind in ("support", "resistance"):
                        prices = [zone.center_price for zone in zones if zone.zone_kind == kind and zone.geometry == "horizontal"
                                  and (zone.center_price <= bar.close if kind == "support" else zone.center_price >= bar.close)]
                        nearest = min(prices, key=lambda price: abs(price - bar.close)) if prices else None
                        row[f"{kind}_distance"] = abs(nearest - bar.close) / bar.close * 100 if nearest is not None else None
            histories[symbol, timeframe] = ([_close_at(bar) for bar in bars], records)

    def at(symbol, timestamp):
        result = {}
        for timeframe in frames:
            times, rows = histories[symbol, timeframe]
            end = bisect_right(times, timestamp)
            result[timeframe] = list(reversed(rows[max(0, end - limit):end]))
        return result
    return at
