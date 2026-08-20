import pandas as pd

from astock.features.patterns import detect_patterns


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": timestamp,
                "open": values[0],
                "high": values[1],
                "low": values[2],
                "close": values[3],
                "volume_shares": 100,
                "amount_cny": 1_000,
            }
            for timestamp, values in zip(
                pd.date_range("2026-01-01", periods=len(rows), freq="B"), rows, strict=True
            )
        ]
    )


def test_detects_doji_and_hammer_with_explainable_ratios() -> None:
    frame = _bars([(10.0, 10.6, 9.4, 10.05), (10.0, 10.25, 8.0, 10.2)])

    events = detect_patterns(frame)

    doji = next(event for event in events if event.pattern_type == "doji")
    hammer = next(event for event in events if event.pattern_type == "hammer")
    assert doji.body_ratio <= 0.1
    assert hammer.lower_shadow_ratio > 0.75
    assert hammer.rule_version == "v1"


def test_detects_bullish_and_bearish_engulfing() -> None:
    bullish = _bars([(10.5, 10.7, 9.7, 10.0), (9.9, 10.8, 9.8, 10.6)])
    bearish = _bars([(10.0, 10.7, 9.9, 10.5), (10.6, 10.7, 9.7, 9.8)])

    assert "bullish_engulfing" in {
        event.pattern_type for event in detect_patterns(bullish)
    }
    assert "bearish_engulfing" in {
        event.pattern_type for event in detect_patterns(bearish)
    }


def test_pattern_detection_never_changes_past_events_with_future_rows() -> None:
    first = _bars([(10, 11, 9, 10.05), (10, 11, 9, 10.7)])
    extended = pd.concat(
        [first, _bars([(20, 21, 19, 20.5)]).assign(timestamp=pd.Timestamp("2026-02-01"))],
        ignore_index=True,
    )

    before = detect_patterns(first)
    after = [event for event in detect_patterns(extended) if event.event_date <= pd.Timestamp("2026-01-02").date()]

    assert before == after
