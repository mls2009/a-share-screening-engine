import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from astock.domain.market import Timeframe

_DELETE_ZONE_LOCK = Lock()
ZONE_RULE_VERSION = "v3"


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
    anchors: tuple[tuple[date | datetime, float], ...]
    strength: float
    touches: int
    source: str = "auto"
    rule_version: str = ZONE_RULE_VERSION


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
    window = values.rolling(order * 2 + 1, center=True, min_periods=1)
    target = window.min() if low else window.max()
    return [int(index) for index in np.flatnonzero(values.eq(target).to_numpy())
            if order <= index < len(values) - order]


def _clusters(
    data: pd.DataFrame,
    positions: list[int],
    column: str,
    tolerance: float,
) -> list[list[int]]:
    clusters: list[list[int]] = []
    prices = data[column].to_numpy()
    for position in positions:
        price = float(prices[position])
        for cluster in clusters:
            center = float(np.mean(prices[cluster]))
            if abs(price - center) <= tolerance:
                cluster.append(position)
                break
        else:
            clusters.append([position])
    return [cluster for cluster in clusters if len(cluster) >= 2]


def detect_zones(
    bars: pd.DataFrame,
    as_of: date,
    timeframe: Timeframe | None = None,
    pivot_order: int = 2,
    rule_version: str = ZONE_RULE_VERSION,
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

    return sorted(zones, key=lambda zone: (zone.geometry, zone.zone_kind, zone.center_price))


def replace_auto_zones(
    connection: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: Timeframe,
    as_of: date,
    zones: list[PriceZone],
    rule_version: str = ZONE_RULE_VERSION,
    latest_bar_at: datetime | None = None,
    source_revision: str = "legacy",
) -> None:
    """Replace one auto-zone batch, owning the transaction for this operation."""
    if any(zone.as_of_date != as_of for zone in zones):
        raise ValueError("all automatic zones must match the batch date")
    if any(zone.rule_version != rule_version for zone in zones):
        raise ValueError("all automatic zones must match the batch rule version")

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
            zone.anchors[0][0].date()
            if isinstance(zone.anchors[0][0], datetime)
            else zone.anchors[0][0],
            zone.anchors[-1][0].date()
            if isinstance(zone.anchors[-1][0], datetime)
            else zone.anchors[-1][0],
            zone.rule_version,
        ]
        for zone in zones
    ]
    watermark = latest_bar_at or datetime.combine(
        as_of, time.min, tzinfo=UTC
    )
    connection.execute("begin transaction")
    try:
        connection.execute(
            """
            delete from support_resistance_zones
            where symbol = ? and timeframe = ? and as_of_date = ? and source = 'auto'
            """,
            [symbol, timeframe.value, as_of],
        )
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
        connection.execute(
            """
            delete from zone_detection_batches
            where symbol = ? and timeframe = ? and as_of_date = ?
            """,
            [symbol, timeframe.value, as_of],
        )
        connection.execute(
            """
            insert into zone_detection_batches
              (symbol, timeframe, as_of_date, rule_version, latest_bar_at,
               source_revision)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                symbol,
                timeframe.value,
                as_of,
                rule_version,
                watermark,
                source_revision,
            ],
        )
        connection.execute("commit")
    except Exception:
        connection.execute("rollback")
        raise


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
        batch_state as (
          select count(*) as batch_count
          from zone_detection_batches
          where symbol = ? and timeframe = ?
        ),
        latest_batch as (
          select as_of_date, rule_version
          from zone_detection_batches
          where symbol = ? and timeframe = ? and as_of_date <= ?
          order by as_of_date desc limit 1
        ),
        legacy_auto as (
          select max(as_of_date) as as_of_date
          from support_resistance_zones
          where symbol = ? and timeframe = ? and as_of_date <= ? and source = 'auto'
        ),
        latest_auto as (
          select case
            when batch_state.batch_count > 0 then latest_batch.as_of_date
            else legacy_auto.as_of_date
          end as as_of_date,
          case
            when batch_state.batch_count > 0 then latest_batch.rule_version
            else null
          end as rule_version
          from batch_state
          left join latest_batch on true
          cross join legacy_auto
        ),
        active as (
          select zones.*
          from support_resistance_zones zones, latest_auto
          where zones.symbol = ? and zones.timeframe = ?
            and zones.state = 'active' and zones.as_of_date <= ?
            and (
              zones.source = 'manual'
              or (
                zones.source = 'auto' and zones.as_of_date = latest_auto.as_of_date
                and (
                  latest_auto.rule_version is null
                  or zones.rule_version = latest_auto.rule_version
                )
              )
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
