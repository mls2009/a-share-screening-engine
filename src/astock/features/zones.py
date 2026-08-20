import json
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from astock.domain.market import Timeframe


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


def detect_zones(
    bars: pd.DataFrame,
    as_of: date,
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

    for kind, column, positions in (
        ("support", "low", low_positions),
        ("resistance", "high", high_positions),
    ):
        selected = positions[-5:]
        if len(selected) < 2:
            continue
        prices = np.array([float(data.iloc[position][column]) for position in selected])
        slope, intercept = np.polyfit(np.array(selected, dtype=float), prices, 1)
        center = float(slope * (len(data) - 1) + intercept)
        residual = float(np.mean(np.abs(prices - (slope * np.array(selected) + intercept))))
        if residual > tolerance:
            continue
        if kind == "support" and center >= latest_close:
            continue
        if kind == "resistance" and center <= latest_close:
            continue
        anchors = tuple(
            (pd.Timestamp(data.iloc[position]["timestamp"]).date(), float(price))
            for position, price in zip(selected, prices, strict=True)
        )
        zones.append(
            PriceZone(
                as_of_date=as_of,
                zone_kind=kind,
                geometry="trend",
                lower_price=center - tolerance,
                center_price=center,
                upper_price=center + tolerance,
                slope=float(slope),
                intercept=float(intercept),
                anchors=anchors,
                strength=min(1.0, len(selected) / 5 * (1 - residual / tolerance)),
                touches=len(selected),
                rule_version=rule_version,
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
    zone = connection.execute(
        """
        select symbol, timeframe, geometry, lower_price, center_price, upper_price
        from support_resistance_zones
        where zone_id = ? and symbol = ?
        """,
        [zone_id, symbol],
    ).fetchone()
    if zone is None:
        return False
    connection.execute("begin transaction")
    try:
        connection.execute(
            """
            insert into zone_deletion_markers
              (marker_id, symbol, timeframe, geometry, lower_price, center_price,
               upper_price)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [uuid4(), *zone],
        )
        connection.execute(
            "delete from support_resistance_zones where zone_id = ? and symbol = ?",
            [zone_id, symbol],
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
    close_row = connection.execute(
        """
        select close from market_features
        where symbol = ? and timeframe = ? and feature_date <= ?
        order by feature_date desc limit 1
        """,
        [symbol, timeframe.value, as_of],
    ).fetchone()
    auto_zone_date = connection.execute(
        """
        select max(as_of_date) from support_resistance_zones
        where symbol = ? and timeframe = ? and as_of_date <= ? and source = 'auto'
        """,
        [symbol, timeframe.value, as_of],
    ).fetchone()
    if close_row is None:
        return []
    cursor = connection.execute(
        """
        select * from support_resistance_zones
        where symbol = ? and timeframe = ? and state = 'active' and as_of_date <= ?
          and (source = 'manual' or (source = 'auto' and as_of_date = ?))
        """,
        [
            symbol,
            timeframe.value,
            as_of,
            auto_zone_date[0] if auto_zone_date is not None else None,
        ],
    )
    columns = [column[0] for column in cursor.description]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    for row in rows:
        if row["source"] != "auto" or row["center_price"] == close_row[0]:
            continue
        row["zone_kind"] = (
            "support" if row["center_price"] < close_row[0] else "resistance"
        )
    selected = []
    for kind in ("support", "resistance"):
        matching = [row for row in rows if row["zone_kind"] == kind]
        matching.sort(key=lambda row: abs(row["center_price"] - close_row[0]))
        selected.extend(matching[:limit_each])
    return selected
