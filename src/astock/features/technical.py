import numpy as np
import pandas as pd


def _streak(values: pd.Series, positive: bool) -> pd.Series:
    condition = values.diff().gt(0) if positive else values.diff().lt(0)
    groups = (~condition).cumsum()
    return condition.astype(int).groupby(groups).cumsum()


def _rolling_drawdown(values: pd.Series, window: int) -> pd.Series:
    return values.rolling(window).apply(
        lambda rows: float((rows / np.maximum.accumulate(rows) - 1).min() * 100),
        raw=True,
    )


def compute_technical_features(bars: pd.DataFrame) -> pd.DataFrame:
    data = bars.copy().sort_values("timestamp").reset_index(drop=True)
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume_shares"].astype(float)

    data["volume"] = volume
    data["amount"] = data["amount_cny"].astype(float)
    for window in (1, 3, 5, 10, 20, 60, 120, 250):
        data[f"return_{window}"] = close.pct_change(window, fill_method=None) * 100
    for window in (5, 10, 20, 30, 60, 120, 250):
        data[f"ma_{window}"] = close.rolling(window).mean()
    for window in (5, 20, 60):
        data[f"volume_ma_{window}"] = volume.rolling(window).mean()
    data["volume_ratio_20"] = volume / data["volume_ma_20"]

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    data["macd"] = ema_12 - ema_26
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
    data["macd_hist"] = (data["macd"] - data["macd_signal"]) * 2

    low_9 = low.rolling(9, min_periods=1).min()
    high_9 = high.rolling(9, min_periods=1).max()
    rsv = (close - low_9) / (high_9 - low_9).replace(0, np.nan) * 100
    data["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    data["kdj_d"] = data["kdj_k"].ewm(alpha=1 / 3, adjust=False).mean()
    data["kdj_j"] = 3 * data["kdj_k"] - 2 * data["kdj_d"]

    delta = close.diff()
    average_gain = delta.clip(lower=0).rolling(14).mean()
    average_loss = -delta.clip(upper=0).rolling(14).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    data["rsi_14"] = 100 - 100 / (1 + relative_strength)
    data.loc[(average_gain > 0) & (average_loss == 0), "rsi_14"] = 100.0

    data["boll_middle"] = close.rolling(20).mean()
    boll_std = close.rolling(20).std(ddof=0)
    data["boll_upper"] = data["boll_middle"] + 2 * boll_std
    data["boll_lower"] = data["boll_middle"] - 2 * boll_std

    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    data["atr_14"] = true_range.rolling(14).mean()
    direction = np.sign(close.diff()).fillna(0)
    data["obv"] = (direction * volume).cumsum()
    data["amplitude"] = (high - low) / previous_close * 100
    log_return = np.log(close / previous_close)
    data["volatility_20"] = log_return.rolling(20).std(ddof=0) * np.sqrt(252) * 100

    for window in (20, 60, 250):
        data[f"high_{window}"] = high.rolling(window).max()
        data[f"low_{window}"] = low.rolling(window).min()
        data[f"max_drawdown_{window}"] = _rolling_drawdown(close, window)
    data["up_streak"] = _streak(close, positive=True)
    data["down_streak"] = _streak(close, positive=False)
    return data
