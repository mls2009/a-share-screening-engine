from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd

from astock.domain.market import Adjustment, Bar, Timeframe


class BarStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, symbol: str, timeframe: Timeframe, year: int) -> Path:
        return self.root / f"timeframe={timeframe.value}" / f"year={year}" / f"{symbol}.parquet"

    def upsert(self, bars: list[Bar]) -> None:
        groups: dict[tuple[str, Timeframe, int], list[Bar]] = {}
        for bar in bars:
            key = (bar.symbol, bar.timeframe, bar.timestamp.year)
            groups.setdefault(key, []).append(bar)

        for (symbol, timeframe, year), rows in groups.items():
            path = self._path(symbol, timeframe, year)
            path.parent.mkdir(parents=True, exist_ok=True)
            incoming = pd.DataFrame([row.model_dump(mode="json") for row in rows])
            if path.exists():
                incoming = pd.concat([pd.read_parquet(path), incoming], ignore_index=True)
            merged = incoming.drop_duplicates(
                ["symbol", "timestamp", "adjustment"], keep="last"
            ).sort_values("timestamp")
            temporary_path = path.with_suffix(".parquet.tmp")
            merged.to_parquet(temporary_path, index=False)
            temporary_path.replace(path)

    def read(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment = Adjustment.NONE,
    ) -> list[Bar]:
        timeframe_root = self.root / f"timeframe={timeframe.value}"
        paths = sorted(timeframe_root.glob(f"year=*/{symbol}.parquet"))
        if not paths:
            return []

        frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
        frame = frame[frame["adjustment"] == adjustment.value].sort_values("timestamp")
        return [Bar.model_validate(row) for row in frame.to_dict("records")]

    def read_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment,
        start: date,
        end: date,
    ) -> list[Bar]:
        return [
            bar
            for bar in self.read(symbol, timeframe, adjustment)
            if start <= bar.timestamp.date() <= end
        ]

    def read_latest(
        self,
        symbol: str,
        timeframe: Timeframe,
        adjustment: Adjustment,
        as_of: date,
        *,
        final_only: bool = False,
    ) -> Bar | None:
        timeframe_root = self.root / f"timeframe={timeframe.value}"
        paths = []
        for year_root in timeframe_root.glob("year=*"):
            try:
                year = int(year_root.name.removeprefix("year="))
            except ValueError:
                continue
            path = year_root / f"{symbol}.parquet"
            if year <= as_of.year and path.exists():
                paths.append((year, path))

        for _, path in sorted(paths, reverse=True):
            frame = pd.read_parquet(path)
            timestamps = pd.to_datetime(frame["timestamp"])
            selected = frame[
                (frame["adjustment"] == adjustment.value)
                & (timestamps.dt.date <= as_of)
            ]
            if final_only and "is_final" in selected:
                selected = selected[selected["is_final"]]
            if selected.empty:
                continue
            latest = selected.sort_values("timestamp").iloc[-1]
            return Bar.model_validate(latest.to_dict())
        return None

    def revision(
        self, symbol: str, timeframe: Timeframe, as_of: date
    ) -> str | None:
        timeframe_root = self.root / f"timeframe={timeframe.value}"
        paths: list[tuple[int, Path]] = []
        for year_root in timeframe_root.glob("year=*"):
            try:
                year = int(year_root.name.removeprefix("year="))
            except ValueError:
                continue
            path = year_root / f"{symbol}.parquet"
            if year <= as_of.year and path.exists():
                paths.append((year, path))
        if not paths:
            return None

        digest = sha256()
        for year, path in sorted(paths, key=lambda item: (item[0], str(item[1]))):
            stat = path.stat()
            fingerprint = (
                f"{year}\0{path.name}\0{stat.st_mtime_ns}\0"
                f"{stat.st_size}\0{stat.st_ino}\n"
            )
            digest.update(fingerprint.encode())
        return digest.hexdigest()
