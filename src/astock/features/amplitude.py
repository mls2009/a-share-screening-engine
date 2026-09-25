"""Daily amplitude averages, independent of the chart's visible range."""
import math
import pandas as pd


def amplitude_summary(bars, as_of):
    history = sorted((bar for bar in bars if bar.is_final and bar.timestamp.date() <= as_of), key=lambda bar: bar.timestamp)
    samples = []
    previous = None
    for bar in history:
        if bar.volume_shares <= 0:
            continue
        value = None
        if previous is not None and previous > 0 and all(math.isfinite(v) for v in (previous, bar.high, bar.low)) and bar.high >= bar.low:
            value = (bar.high - bar.low) / previous * 100
        samples.append((bar.timestamp.date(), value))
        previous = bar.close
    boundary = (pd.Timestamp(as_of) - pd.DateOffset(years=2)).date()

    def average(rows):
        valid = [(day, value) for day, value in rows if value is not None]
        return {'value': sum(value for _, value in valid) / len(valid) if valid else None,
                'count': len(valid), 'start': str(valid[0][0]) if valid else None,
                'end': str(valid[-1][0]) if valid else None}

    return {'data_date': str(history[-1].timestamp.date()) if history else None,
            'days20': average(samples[-20:]), 'days120': average(samples[-120:]),
            'two_years': average([row for row in samples if row[0] >= boundary])}
