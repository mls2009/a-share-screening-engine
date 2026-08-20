import json
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from astock.domain.market import Timeframe

_DELETE_ZONE_LOCK = Lock()


@dataclass(frozen=True)
class PriceZone:
    as_of_date: date
    zone_kind: str
    geometry: str
    lower_price: float
    center_price: float
    upper_price: float
    slope: float | None
    intercept: float | None
    anchors: tuple[tuple[date, float], ...]
    strength: float
    touches: int
    source: str = "auto"
    rule_version: str = "v1"


class ManualZoneInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: Timeframe
    as_of_date: date
    zone_kind: Literal["support", "resistance"]
    geometry: Literal["horizontal", "trend"]
    lower_price: float
    center_price: float
    upper_price: float
    slope: float | None = None
    intercept: float | None = None
    anchors: tuple[tuple[date, float], ...]

    @model_validator(mode="after")
    def validate_geometry(self) -> "ManualZoneInput":
        if not 0 < self.lower_price <= self.center_price <= self.upper_price:
            raise ValueError("prices must be positive and ordered")
        if self.geometry == "trend" and len(self.anchors) < 2:
            raise ValueError("trend zone requires at least two anchors")
        if self.geometry == "trend" and (self.slope is None or self.intercept is None):
            raise ValueError("trend zone requires slope and intercept")
        if not self.anchors:
            raise ValueError("zone requires at least one anchor")
        return self


def _pivots(values: pd.Series, order: int, low: bool) -> list[int]:
    positions = []
    for index in range(order, len(values) - order):
        window = values.iloc[index - order : index + order + 1]
        target = window.min() if low else window.max()
        if values.iloc[index] == target:
            positions.append(index)
    return positions


def _clusters(
    data: pd.DataFrame,
    positions: list[int],
    column: str,
    tolerance: float,
) -> list[list[int]]:
    clusters: list[list[int]] = []
    for position in positions:
        price = float(data.iloc[position][column])
        for cluster in clusters:
            center = float(np.mean([data.iloc[item][column] for item in cluster]))
            if abs(price - center) <= tolerance:
                cluster.append(position)
                break
        else:
            clusters.append([position])
    return [cluster for cluster in clusters if len(cluster) >= 2]


def _fit_trend(
    data: pd.DataFrame, positions: list[int], column: str
) -> tuple[float, float, float, float]:
    x = np.array(positions, dtype=float)
    prices = np.array([float(data.iloc[position][column]) for position in positions])
    slope, intercept = np.polyfit(x, prices, 1)
    center = float(slope * (len(data) - 1) + intercept)
    residual = float(np.mean(np.abs(prices - (slope * x + intercept))))
    return float(slope), float(intercept), center, residual


def _directional_trend_zones(
    data: pd.DataFrame,
    as_of: date,
    pivot_groups: tuple[tuple[str, list[int]], ...],
    tolerance: float,
    rule_version: str,
) -> list[PriceZone]:
    candidates: dict[str, list[tuple[list[int], str, float, float, float, float]]] = {
        "uptrend": [],
        "downtrend": [],
    }
    for column, positions in pivot_groups:
        recent = positions[-12:]
        for size in range(2, min(5, len(recent)) + 1):
            for start in range(len(recent) - size + 1):
                selected = recent[start : start + size]
                slope, intercept, center, residual = _fit_trend(
                    data, selected, column
                )
                total_move = abs(slope) * (selected[-1] - selected[0])
                if residual > tolerance or slope == 0 or total_move < tolerance:
                    continue
                direction = "uptrend" if slope > 0 else "downtrend"
                candidates[direction].append(
                    (selected, column, slope, intercept, center, residual)
                )

    zones = []
    for direction, direction_candidates in candidates.items():
        if not direction_candidates:
            continue
        selected, column, slope, intercept, center, residual = min(
            direction_candidates,
            key=lambda item: (
                -item[0][-1],
                -len(item[0]),
                item[5] / tolerance,
            ),
        )
        anchors = tuple(
            (
                pd.Timestamp(data.iloc[position]["timestamp"]).date(),
                float(data.iloc[position][column]),
            )
            for position in selected
        )
        zones.append(
            PriceZone(
                as_of_date=as_of,
                zone_kind=direction,
                geometry="trend",
                lower_price=center - tolerance,
                center_price=center,
                upper_price=center + tolerance,
                slope=slope,
                intercept=intercept,
                anchors=anchors,
                strength=max(
                    0.1,
                    min(
                        1.0,
                        len(selected) / 5 * (1 - min(residual / tolerance, 0.9)),
                    ),
                ),
                touches=len(selected),
                rule_version=rule_version,
            )
        )
    return zones


def detect_zones(
    bars: pd.DataFrame,
    as_of: date,
    timeframe: Timeframe | None = None,
    pivot_order: int = 2,
    rule_version: str = "v1",
) -> list[PriceZone]:
    data = bars.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    data = data[data["timestamp"].dt.date <= as_of].sort_values("timestamp").reset_index(drop=True)
    if len(data) < pivot_order * 2 + 1:
        return []

    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    latest_close = float(data.iloc[-1]["close"])
    atr = float(true_range.tail(14).mean())
    tolerance = max(latest_close * 0.005, atr * 0.5)
    zones: list[PriceZone] = []

    low_positions = _pivots(data["low"], pivot_order, low=True)
    high_positions = _pivots(data["high"], pivot_order, low=False)
    for kind, column, positions in (
        ("support", "low", low_positions),
        ("resistance", "high", high_positions),
    ):
        for cluster in _clusters(data, positions, column, tolerance):
            prices = [float(data.iloc[position][column]) for position in cluster]
            center = float(np.mean(prices))
            if kind == "support" and center >= latest_close:
                continue
            if kind == "resistance" and center <= latest_close:
                continue
            anchors = tuple(
                (pd.Timestamp(data.iloc[position]["timestamp"]).date(), prices[index])
                for index, position in enumerate(cluster)
            )
            zones.append(
                PriceZone(
                    as_of_date=as_of,
                    zone_kind=kind,
                    geometry="horizontal",
                    lower_price=center - tolerance,
                    center_price=center,
                    upper_price=center + tolerance,
                    slope=None,
                    intercept=None,
                    anchors=anchors,
                    strength=min(1.0, len(cluster) / 5),
                    touches=len(cluster),
                    rule_version=rule_version,
                )
            )

    zones.extend(
        _directional_trend_zones(
            data,
            as_of,
            (("low", low_positions), ("high", high_positions)),
            tolerance,
            rule_version,
        )
    )
    return sorted(zones, key=lambda zone: (zone.geometry, zone.zone_kind, zone.center_price))


def replace_auto_zones(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    as_of: date,
    zones: list[PriceZone],
) -> None:
    connection.execute(
        """
        delete from support_resistance_zones
        where symbol = ? and timeframe = ? and as_of_date = ? and source = 'auto'
        """,
        [symbol, timeframe.value, as_of],
    )
    rows = [
        [
            symbol,
            timeframe.value,
            zone.as_of_date,
            zone.zone_kind,
            zone.geometry,
            zone.lower_price,
            zone.center_price,
            zone.upper_price,
            zone.slope,
            zone.intercept,
            json.dumps([[day.isoformat(), price] for day, price in zone.anchors]),
            zone.strength,
            zone.touches,
            zone.anchors[0][0],
            zone.anchors[-1][0],
            zone.rule_version,
        ]
        for zone in zones
    ]
    if rows:
        connection.executemany(
            """
            insert into support_resistance_zones
              (symbol, timeframe, as_of_date, zone_kind, geometry, lower_price,
               center_price, upper_price, slope, intercept, anchors, strength, touches,
               first_touched_on, last_touched_on, source, rule_version)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto', ?)
            """,
            rows,
        )


def create_manual_zone(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    zone: ManualZoneInput,
) -> UUID:
    zone_id = uuid4()
    connection.execute(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry, lower_price,
           center_price, upper_price, slope, intercept, anchors, strength, touches,
           first_touched_on, last_touched_on, state, source, rule_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'active', 'manual', 'manual-v1')
        """,
        [
            zone_id,
            symbol,
            zone.timeframe.value,
            zone.as_of_date,
            zone.zone_kind,
            zone.geometry,
            zone.lower_price,
            zone.center_price,
            zone.upper_price,
            zone.slope,
            zone.intercept,
            json.dumps([[day.isoformat(), price] for day, price in zone.anchors]),
            len(zone.anchors),
            min(day for day, _ in zone.anchors),
            max(day for day, _ in zone.anchors),
        ],
    )
    return zone_id


def delete_zone(
    connection: duckdb.DuckDBPyConnection, symbol: str, zone_id: UUID
) -> bool:
    with _DELETE_ZONE_LOCK:
        connection.execute("begin transaction")
        try:
            zone = connection.execute(
                """
                update support_resistance_zones set state = 'deleted'
                where zone_id = ? and symbol = ? and state = 'active'
                returning symbol, timeframe, geometry, lower_price, center_price,
                          upper_price
                """,
                [zone_id, symbol],
            ).fetchone()
            if zone is None:
                connection.execute("rollback")
                return False
            connection.execute(
                """
                insert into zone_deletion_markers
                  (marker_id, symbol, timeframe, geometry, lower_price, center_price,
                   upper_price)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                [uuid4(), *zone],
            )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise
        return True


def nearest_zones(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    as_of: date,
    limit_each: int = 3,
) -> list[dict]:
    rows, close = _active_zones(connection, symbol, timeframe, as_of)
    if close is None:
        return []
    return _nearest_horizontal_zones(rows, close, limit_each)


def chart_zones(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    as_of: date,
    limit_each: int = 3,
    close_override: float | None = None,
) -> list[dict]:
    rows, close = _active_zones(
        connection, symbol, timeframe, as_of, close_override=close_override
    )

    selected = [row for row in rows if row["source"] == "manual"]
    if close is not None:
        selected.extend(
            _nearest_horizontal_zones(rows, close, limit_each, source="auto")
        )
    auto_trends = [
        row
        for row in rows
        if row["source"] == "auto" and row["geometry"] == "trend"
    ]
    for kind in ("uptrend", "downtrend"):
        matching = [row for row in auto_trends if row["zone_kind"] == kind]
        if matching:
            selected.append(
                max(
                    matching,
                    key=lambda row: (
                        row["last_touched_on"] or date.min,
                        row["touches"],
                        row["strength"],
                        str(row["zone_id"]),
                    ),
                )
            )
    return selected


def _active_zones(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    as_of: date,
    close_override: float | None = None,
) -> tuple[list[dict], float | None]:
    cursor = connection.execute(
        """
        with latest_close as (
          select close from market_features
          where symbol = ? and timeframe = ? and feature_date <= ?
            and close is not null
          order by feature_date desc limit 1
        ),
        latest_auto as (
          select max(as_of_date) as as_of_date
          from support_resistance_zones
          where symbol = ? and timeframe = ? and as_of_date <= ? and source = 'auto'
        ),
        active as (
          select zones.*
          from support_resistance_zones zones, latest_auto
          where zones.symbol = ? and zones.timeframe = ?
            and zones.state = 'active' and zones.as_of_date <= ?
            and (
              zones.source = 'manual'
              or (zones.source = 'auto' and zones.as_of_date = latest_auto.as_of_date)
            )
        )
        select active.*, (select close from latest_close) as latest_close,
          exists(
            select 1 from zone_deletion_markers marker
            where marker.symbol = ? and marker.timeframe = ?
              and marker.geometry = active.geometry
              and marker.lower_price <= active.center_price
              and marker.upper_price >= active.center_price
          ) as reappeared
        from active
        """,
        [
            symbol,
            timeframe.value,
            as_of,
            symbol,
            timeframe.value,
            as_of,
            symbol,
            timeframe.value,
            as_of,
            symbol,
            timeframe.value,
        ],
    )
    columns = [column[0] for column in cursor.description]
    loaded = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    if not loaded:
        return [], None
    close_value = loaded[0].pop("latest_close")
    close = float(close_value) if close_value is not None else None
    if close_override is not None and np.isfinite(close_override) and close_override > 0:
        close = float(close_override)
    rows = []
    for row in loaded:
        row.pop("latest_close", None)
        if row["zone_id"] is None:
            continue
        rows.append(row)
    for row in rows:
        if (
            row["source"] == "auto"
            and row["geometry"] == "horizontal"
            and row["zone_kind"] in {"support", "resistance"}
            and close is not None
            and row["center_price"] != close
        ):
            row["zone_kind"] = "support" if row["center_price"] < close else "resistance"
    return rows, close


def _nearest_horizontal_zones(
    rows: list[dict],
    close: float,
    limit_each: int,
    source: str | None = None,
) -> list[dict]:
    selected = []
    for kind in ("support", "resistance"):
        matching = [
            row
            for row in rows
            if row["geometry"] == "horizontal"
            and row["zone_kind"] == kind
            and (source is None or row["source"] == source)
        ]
        matching.sort(key=lambda row: abs(row["center_price"] - close))
        selected.extend(matching[:limit_each])
    return selected
