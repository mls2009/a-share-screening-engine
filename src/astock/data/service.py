from datetime import date, timedelta
from typing import Protocol

import pandas as pd

from astock.data.aggregate import aggregate_daily, aggregate_intraday
from astock.data.providers.base import HistoryProvider, ReferenceDataProvider
from astock.data.quality import QualityContext, QualityIssue, inspect_rows
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security
from astock.storage.bars import BarStore
from astock.storage.coverage import CoverageRepository
from astock.storage.database import Database


class Calendar(Protocol):
    def open_dates(self, start: date, end: date) -> set[date]: ...


class DatabaseCalendar:
    def __init__(self, database: Database) -> None:
        self.connection = database.connection

    def open_dates(self, start: date, end: date) -> set[date]:
        rows = self.connection.execute(
            """
            select trade_date from trading_calendar
            where is_open and trade_date between ? and ?
            """,
            [start, end],
        ).fetchall()
        return {row[0] for row in rows}


class DataQualityError(RuntimeError):
    def __init__(self, issues: list[QualityIssue]) -> None:
        self.issues = issues
        super().__init__(", ".join(issue.code for issue in issues))


class MarketDataService:
    def __init__(
        self,
        history_provider: HistoryProvider,
        bar_store: BarStore,
        database: Database,
        calendar: Calendar | None = None,
        reference_provider: ReferenceDataProvider | None = None,
    ) -> None:
        self.history_provider = history_provider
        self.reference_provider = reference_provider
        self.bar_store = bar_store
        self.database = database
        self.coverage = CoverageRepository(database)
        self.calendar = calendar if calendar is not None else DatabaseCalendar(database)

    @staticmethod
    def _base_timeframe(timeframe: Timeframe) -> Timeframe:
        if timeframe in {Timeframe.MIN_15, Timeframe.MIN_30, Timeframe.MIN_60}:
            return Timeframe.MIN_5
        if timeframe in {Timeframe.WEEK, Timeframe.MONTH}:
            return Timeframe.DAY
        return timeframe

    def _record_issues(self, symbol: str, issues: list[QualityIssue]) -> None:
        if not issues:
            return
        self.database.connection.executemany(
            """
            insert into quality_issues(symbol, timestamp, code, detail)
            values (?, ?, ?, ?)
            """,
            [[symbol, issue.timestamp, issue.code, issue.detail] for issue in issues],
        )

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]:
        if start > end:
            raise ValueError("start must not be after end")

        base = self._base_timeframe(timeframe)
        for gap_start, gap_end in self.coverage.missing_ranges(
            symbol, base, adjustment, start, end
        ):
            incoming = self.history_provider.history(
                symbol, base, gap_start, gap_end, adjustment
            )
            context = QualityContext(
                valid_trading_dates=self.calendar.open_dates(gap_start, gap_end),
                intraday=base == Timeframe.MIN_5,
            )
            issues = inspect_rows([bar.model_dump() for bar in incoming], context)
            self._record_issues(symbol, issues)
            blocking = [issue for issue in issues if issue.code != "non_monotonic_input"]
            if blocking:
                raise DataQualityError(blocking)
            self.bar_store.upsert(sorted(incoming, key=lambda bar: bar.timestamp))
            self.coverage.record(symbol, base, adjustment, gap_start, gap_end)

        bars = self.bar_store.read_range(symbol, base, adjustment, start, end)
        return self.derive(bars, timeframe)

    def sync_universe(self, start: date, end: date) -> list[Security]:
        if self.reference_provider is None:
            raise RuntimeError("reference provider is not configured")
        securities = self.reference_provider.securities_on(end)
        open_dates = self.reference_provider.trading_dates(start, end)
        calendar_rows = []
        current = start
        while current <= end:
            calendar_rows.append([current, current in open_dates])
            current += timedelta(days=1)
        connection = self.database.connection
        connection.execute("begin transaction")
        try:
            connection.executemany(
                "insert or replace into trading_calendar values (?, ?)", calendar_rows
            )
            if securities:
                connection.executemany(
                    """
                    insert into symbols
                      (symbol, name, exchange, listed_on, delisted_on, board, is_listed)
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict (symbol) do update set
                      name = excluded.name,
                      exchange = excluded.exchange,
                      listed_on = excluded.listed_on,
                      delisted_on = excluded.delisted_on,
                      board = excluded.board,
                      is_listed = excluded.is_listed
                    """,
                    [
                        [
                            security.symbol,
                            security.name,
                            security.exchange,
                            security.listed_on,
                            security.delisted_on,
                            security.board,
                            security.is_listed,
                        ]
                        for security in securities
                    ],
                )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise
        return securities

    def sync_reference(self, symbols: list[str], start: date, end: date) -> None:
        if self.reference_provider is None:
            raise RuntimeError("reference provider is not configured")

        open_dates = self.reference_provider.trading_dates(start, end)
        securities = [
            security
            for security in self.reference_provider.securities_on(end)
            if security.symbol in symbols
        ]
        factors = []
        actions = []
        statuses = []
        for symbol in symbols:
            factors.extend(self.reference_provider.adjustment_factors(symbol, start, end))
            actions.extend(self.reference_provider.corporate_actions(symbol, start, end))
            statuses.extend(self.reference_provider.security_status(symbol, start, end))

        calendar_rows = []
        current = start
        while current <= end:
            calendar_rows.append([current, current in open_dates])
            current += timedelta(days=1)

        connection = self.database.connection
        connection.execute("begin transaction")
        try:
            connection.executemany(
                "insert or replace into trading_calendar values (?, ?)", calendar_rows
            )
            if securities:
                connection.executemany(
                    """
                    insert into symbols
                      (symbol, name, exchange, listed_on, delisted_on, board, is_listed)
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict (symbol) do update set
                      name = excluded.name,
                      exchange = excluded.exchange,
                      listed_on = excluded.listed_on,
                      delisted_on = excluded.delisted_on,
                      board = excluded.board,
                      is_listed = excluded.is_listed
                    """,
                    [
                        [
                            security.symbol,
                            security.name,
                            security.exchange,
                            security.listed_on,
                            security.delisted_on,
                            security.board,
                            security.is_listed,
                        ]
                        for security in securities
                    ],
                )
            if factors:
                connection.executemany(
                    "insert or replace into adjustment_factors values (?, ?, ?, ?, ?)",
                    [
                        [
                            row["symbol"],
                            row["trade_date"],
                            row["forward_factor"],
                            row["backward_factor"],
                            row["source"],
                        ]
                        for row in factors
                    ],
                )
            if actions:
                connection.executemany(
                    "insert or replace into corporate_actions values (?, ?, ?, ?, ?)",
                    [
                        [
                            row["symbol"],
                            row["ex_date"],
                            row["cash_per_share"],
                            row["share_ratio"],
                            row["source"],
                        ]
                        for row in actions
                    ],
                )
            if statuses:
                connection.executemany(
                    "insert or replace into security_status values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        [
                            row["symbol"],
                            row["trade_date"],
                            row["board"],
                            row["is_st"],
                            row["is_suspended"],
                            row["previous_close"],
                            row["limit_up"],
                            row["limit_down"],
                        ]
                        for row in statuses
                    ],
                )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise

    @staticmethod
    def derive(bars: list[Bar], timeframe: Timeframe) -> list[Bar]:
        if not bars or bars[0].timeframe == timeframe:
            return bars

        frame = pd.DataFrame([bar.model_dump() for bar in bars])
        if timeframe in {Timeframe.MIN_15, Timeframe.MIN_30, Timeframe.MIN_60}:
            minutes = {
                Timeframe.MIN_15: 15,
                Timeframe.MIN_30: 30,
                Timeframe.MIN_60: 60,
            }[timeframe]
            derived = aggregate_intraday(frame, minutes)
        elif timeframe in {Timeframe.WEEK, Timeframe.MONTH}:
            period = "week" if timeframe == Timeframe.WEEK else "month"
            derived = aggregate_daily(frame, period)
        else:
            raise ValueError(f"cannot derive timeframe {timeframe} from {bars[0].timeframe}")

        first = bars[0]
        return [
            Bar(
                symbol=first.symbol,
                timestamp=row["timestamp"],
                timeframe=timeframe,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume_shares=row["volume_shares"],
                amount_cny=row["amount_cny"],
                adjustment=first.adjustment,
                source=first.source,
                is_final=True,
            )
            for row in derived.to_dict("records")
        ]
