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
