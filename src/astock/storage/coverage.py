from datetime import date, timedelta

from astock.domain.market import Adjustment, Timeframe
from astock.storage.database import Database

DateRange = tuple[date, date]


class CoverageRepository:
    def __init__(self, database: Database) -> None:
        self.connection = database.connection

    @staticmethod
    def _merge(intervals: list[DateRange]) -> list[DateRange]:
        merged: list[DateRange] = []
        for start, end in sorted(intervals):
            if not merged or start > merged[-1][1] + timedelta(days=1):
                merged.append((start, end))
                continue
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    def _intervals(
        self, symbol: str, timeframe: Timeframe, adjustment: Adjustment
    ) -> list[DateRange]:
        rows = self.connection.execute(
            """
            select cast(start_at as date), cast(end_at as date)
            from bar_coverage
            where symbol = ? and timeframe = ? and adjustment = ?
            order by start_at
            """,
            [symbol, timeframe.value, adjustment.value],
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def record(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment,
        start: date,
        end: date,
    ) -> None:
        intervals = self._merge([*self._intervals(symbol, timeframe, adjustment), (start, end)])
        self.connection.execute("begin transaction")
        try:
            self.connection.execute(
                "delete from bar_coverage where symbol = ? and timeframe = ? and adjustment = ?",
                [symbol, timeframe.value, adjustment.value],
            )
            self.connection.executemany(
                "insert into bar_coverage values (?, ?, ?, ?, ?)",
                [
                    [symbol, timeframe.value, adjustment.value, interval_start, interval_end]
                    for interval_start, interval_end in intervals
                ],
            )
            self.connection.execute("commit")
        except Exception:
            self.connection.execute("rollback")
            raise

    def missing_ranges(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment,
        start: date,
        end: date,
    ) -> list[DateRange]:
        missing: list[DateRange] = []
        cursor = start
        for covered_start, covered_end in self._merge(
            self._intervals(symbol, timeframe, adjustment)
        ):
            if covered_end < cursor:
                continue
            if covered_start > end:
                break
            if covered_start > cursor:
                missing.append((cursor, min(end, covered_start - timedelta(days=1))))
            cursor = max(cursor, covered_end + timedelta(days=1))
            if cursor > end:
                break
        if cursor <= end:
            missing.append((cursor, end))
        return missing
