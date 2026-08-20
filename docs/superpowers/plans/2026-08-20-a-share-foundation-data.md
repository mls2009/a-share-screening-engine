# A 股平台底座与行情数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可测试的 Python 项目、统一行情模型、DuckDB/Parquet 存储，以及 BaoStock 历史数据与 mootdx 实时行情接入。

**Architecture:** 通过 `MarketDataProvider` 隔离外部数据源，所有数据先归一化为领域模型，再经质量检查进入 Parquet。DuckDB 保存元数据、覆盖区间和质量结果；15/30/60 分钟及周/月数据按请求从 5 分钟和日线聚合。

**Tech Stack:** Python 3.12、Pydantic 2、DuckDB、PyArrow、Pandas、BaoStock、mootdx、pytest、Ruff

---

## File Map

```text
pyproject.toml                         项目依赖、测试和 lint 配置
src/astock/config.py                   本地路径和运行参数
src/astock/domain/market.py            K 线、报价、周期和复权领域模型
src/astock/storage/database.py         DuckDB 连接与迁移
src/astock/storage/schema.sql          元数据表结构
src/astock/storage/bars.py             Parquet K 线读写
src/astock/storage/coverage.py         缓存覆盖区间与缺口计算
src/astock/data/providers/base.py      数据源协议
src/astock/data/providers/baostock.py  历史数据适配器
src/astock/data/providers/mootdx.py    实时数据适配器
src/astock/data/aggregate.py           周期聚合
src/astock/data/quality.py             数据质量检查
src/astock/data/service.py             按需补齐与统一查询入口
src/astock/cli.py                      数据同步和在线冒烟入口
tests/                                 对应单元与集成测试
```

### Task 1: Scaffold the Python package

**Files:**
- Create: `pyproject.toml`
- Create: `src/astock/__init__.py`
- Create: `src/astock/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config test**

```python
from pathlib import Path

from astock.config import Settings


def test_settings_create_data_directories(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    assert settings.database_path == tmp_path / "data" / "astock.duckdb"
    assert settings.bars_dir.is_dir()
```

- [ ] **Step 2: Run the test and verify import failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'astock'`.

- [ ] **Step 3: Add package metadata and minimal settings**

```toml
[project]
name = "astock"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "baostock>=0.9.3",
  "duckdb>=1.3",
  "mootdx>=0.11.7",
  "pandas>=2.2",
  "pyarrow>=18",
  "pydantic>=2.10",
  "pydantic-settings>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-cov>=6", "ruff>=0.9"]

[project.scripts]
astock = "astock.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

```python
# src/astock/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTOCK_", env_file=".env")
    data_dir: Path = Path("data")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "astock.duckdb"

    @property
    def bars_dir(self) -> Path:
        return self.data_dir / "bars"

    def ensure_directories(self) -> None:
        self.bars_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Install and verify the test passes**

Run: `python -m pip install -e '.[dev]' && python -m pytest tests/test_config.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/astock tests/test_config.py
git commit -m "build: scaffold astock package"
```

### Task 2: Define normalized market-data models

**Files:**
- Create: `src/astock/domain/__init__.py`
- Create: `src/astock/domain/market.py`
- Test: `tests/domain/test_market.py`

- [ ] **Step 1: Write model validation tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from pydantic import ValidationError

from astock.domain.market import Bar, Quote, Timeframe


def test_bar_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValidationError):
        Bar(symbol="600519.SH", timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
            timeframe=Timeframe.DAY, open=10, high=9, low=8, close=9,
            volume_shares=100, amount_cny=900)


def test_quote_uses_share_volume() -> None:
    quote = Quote(symbol="600519.SH", timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
                  price=10, volume_shares=12_300, amount_cny=123_000, source="mootdx")
    assert quote.volume_shares == 12_300
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/domain/test_market.py -v`
Expected: FAIL because `astock.domain.market` does not exist.

- [ ] **Step 3: Implement enums and models**

```python
# src/astock/domain/market.py
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, model_validator


class Timeframe(StrEnum):
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1mo"


class Adjustment(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    timestamp: datetime
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume_shares: int
    amount_cny: float
    adjustment: Adjustment = Adjustment.NONE
    source: str = ""
    is_final: bool = True

    @model_validator(mode="after")
    def validate_market_values(self) -> "Bar":
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC values are inconsistent")
        if self.volume_shares < 0 or self.amount_cny < 0:
            raise ValueError("volume and amount must be non-negative")
        return self


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    timestamp: datetime
    price: float
    volume_shares: int
    amount_cny: float
    source: str
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/domain/test_market.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/astock/domain tests/domain
git commit -m "feat: add normalized market data models"
```

### Task 3: Create DuckDB schema and migration runner

**Files:**
- Create: `src/astock/storage/__init__.py`
- Create: `src/astock/storage/schema.sql`
- Create: `src/astock/storage/database.py`
- Test: `tests/storage/test_database.py`

- [ ] **Step 1: Write the schema test**

```python
from pathlib import Path
from astock.storage.database import Database


def test_database_migrates_required_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    names = {row[0] for row in db.connection.execute("show tables").fetchall()}
    assert {"symbols", "trading_calendar", "security_status", "bar_coverage",
            "quality_issues", "adjustment_factors", "corporate_actions"} <= names
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/storage/test_database.py -v`
Expected: FAIL because `Database` is missing.

- [ ] **Step 3: Add deterministic schema and migration code**

```sql
-- src/astock/storage/schema.sql
create table if not exists symbols (
  symbol varchar primary key,
  name varchar not null,
  exchange varchar not null,
  listed_on date,
  delisted_on date
);
create table if not exists trading_calendar (
  trade_date date primary key,
  is_open boolean not null
);
create table if not exists security_status (
  symbol varchar not null,
  trade_date date not null,
  board varchar not null,
  is_st boolean not null,
  is_suspended boolean not null,
  previous_close double,
  limit_up double,
  limit_down double,
  primary key(symbol, trade_date)
);
create table if not exists bar_coverage (
  symbol varchar not null,
  timeframe varchar not null,
  adjustment varchar not null,
  start_at timestamp not null,
  end_at timestamp not null,
  primary key(symbol, timeframe, adjustment, start_at, end_at)
);
create table if not exists adjustment_factors (
  symbol varchar not null,
  trade_date date not null,
  forward_factor double not null,
  backward_factor double not null,
  source varchar not null,
  primary key(symbol, trade_date)
);
create table if not exists corporate_actions (
  symbol varchar not null,
  ex_date date not null,
  cash_per_share double not null default 0,
  share_ratio double not null default 0,
  source varchar not null,
  primary key(symbol, ex_date)
);
create table if not exists quality_issues (
  issue_id uuid default uuid(),
  symbol varchar not null,
  timestamp timestamp,
  code varchar not null,
  detail varchar not null,
  created_at timestamp default current_timestamp
);
```

```python
# src/astock/storage/database.py
from importlib.resources import files
from pathlib import Path
import duckdb


class Database:
    def __init__(self, path: Path) -> None:
        self.connection = duckdb.connect(str(path))

    def migrate(self) -> None:
        sql = files("astock.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        self.connection.execute(sql)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/storage/test_database.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/astock/storage tests/storage/test_database.py
git commit -m "feat: add DuckDB metadata schema"
```

### Task 4: Implement idempotent Parquet bar storage

**Files:**
- Create: `src/astock/storage/bars.py`
- Test: `tests/storage/test_bars.py`

- [ ] **Step 1: Write duplicate-safe round-trip test**

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.storage.bars import BarStore


def test_upsert_bars_deduplicates_symbol_timestamp(tmp_path: Path) -> None:
    bar = Bar(symbol="600519.SH", timestamp=datetime(2026, 8, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
              timeframe=Timeframe.DAY, open=10, high=11, low=9, close=10.5,
              volume_shares=1000, amount_cny=10_500, source="test")
    store = BarStore(tmp_path)
    store.upsert([bar, bar])
    assert store.read("600519.SH", Timeframe.DAY, Adjustment.NONE)[0] == bar
    assert len(store.read("600519.SH", Timeframe.DAY, Adjustment.NONE)) == 1
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/storage/test_bars.py -v`
Expected: FAIL because `BarStore` is missing.

- [ ] **Step 3: Implement partitioned read/upsert**

```python
# src/astock/storage/bars.py
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
            groups.setdefault((bar.symbol, bar.timeframe, bar.timestamp.year), []).append(bar)
        for (symbol, timeframe, year), rows in groups.items():
            path = self._path(symbol, timeframe, year)
            path.parent.mkdir(parents=True, exist_ok=True)
            incoming = pd.DataFrame([row.model_dump(mode="json") for row in rows])
            current = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            merged = pd.concat([current, incoming], ignore_index=True)
            merged = merged.drop_duplicates(["symbol", "timestamp", "adjustment"], keep="last")
            merged.sort_values("timestamp").to_parquet(path, index=False)

    def read(self, symbol: str, timeframe: Timeframe,
             adjustment: Adjustment = Adjustment.NONE) -> list[Bar]:
        paths = sorted((self.root / f"timeframe={timeframe.value}").glob(f"year=*/{symbol}.parquet"))
        if not paths:
            return []
        frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
        frame = frame[frame["adjustment"] == adjustment.value]
        return [Bar.model_validate(row) for row in frame.to_dict("records")]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/storage/test_bars.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/astock/storage/bars.py tests/storage/test_bars.py
git commit -m "feat: persist normalized bars in Parquet"
```

### Task 5: Aggregate supported timeframes without crossing lunch break

**Files:**
- Create: `src/astock/data/__init__.py`
- Create: `src/astock/data/aggregate.py`
- Test: `tests/data/test_aggregate.py`

- [ ] **Step 1: Write aggregation tests with session boundary**

```python
import pandas as pd
from astock.data.aggregate import aggregate_intraday


def test_fifteen_minute_bars_do_not_cross_lunch() -> None:
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-08-20 11:25", "2026-08-20 11:30", "2026-08-20 13:05"]),
        "open": [10, 11, 20], "high": [11, 12, 21], "low": [9, 10, 19],
        "close": [11, 12, 21], "volume_shares": [100, 200, 300],
        "amount_cny": [1000, 2200, 6000],
    })
    result = aggregate_intraday(frame, minutes=15)
    assert len(result) == 2
    assert result.iloc[0].volume_shares == 300
    assert result.iloc[1].open == 20
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/data/test_aggregate.py -v`
Expected: FAIL because aggregation is missing.

- [ ] **Step 3: Implement session-aware grouping**

```python
# src/astock/data/aggregate.py
import pandas as pd


def aggregate_intraday(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    data = frame.copy().sort_values("timestamp")
    local = pd.to_datetime(data["timestamp"])
    session_start = local.dt.normalize() + pd.to_timedelta(
        local.dt.hour.map(lambda hour: "09:30:00" if hour < 12 else "13:00:00")
    )
    elapsed_seconds = (local - session_start).dt.total_seconds().astype(int)
    bucket_number = ((elapsed_seconds - 1).clip(lower=0) // (minutes * 60)) + 1
    data["session"] = session_start
    data["bucket"] = session_start + pd.to_timedelta(bucket_number * minutes, unit="m")
    return data.groupby(["session", "bucket"], as_index=False).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume_shares=("volume_shares", "sum"), amount_cny=("amount_cny", "sum"),
    ).rename(columns={"bucket": "timestamp"}).drop(columns=["session"])


def aggregate_daily(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    data = frame.copy().sort_values("timestamp").set_index("timestamp")
    rule = {"week": "W-FRI", "month": "ME"}[period]
    return data.resample(rule).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume_shares=("volume_shares", "sum"),
        amount_cny=("amount_cny", "sum"),
    ).dropna(subset=["open"]).reset_index()
```

- [ ] **Step 4: Add daily-to-week/month cases and run tests**

Add tests asserting Monday–Friday aggregate into one week and two calendar months remain separate. Also assert the output timestamp is the resampled period end, OHLC uses first/max/min/last, and volume/amount are summed.

Run: `python -m pytest tests/data/test_aggregate.py -v`
Expected: all aggregation tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/data tests/data/test_aggregate.py
git commit -m "feat: aggregate A-share bar timeframes"
```

### Task 6: Enforce data quality before persistence

**Files:**
- Create: `src/astock/data/quality.py`
- Test: `tests/data/test_quality.py`

- [ ] **Step 1: Write explicit issue-code tests**

```python
from datetime import datetime
from astock.data.quality import QualityContext, inspect_rows


def test_quality_reports_duplicate_and_negative_volume() -> None:
    rows = [
        {"timestamp": datetime(2026, 8, 20), "open": 10, "high": 11, "low": 9,
         "close": 10, "volume_shares": -1, "amount_cny": 1},
        {"timestamp": datetime(2026, 8, 20), "open": 10, "high": 11, "low": 9,
         "close": 10, "volume_shares": 1, "amount_cny": 1},
    ]
    context = QualityContext(valid_trading_dates={datetime(2026, 8, 20).date()}, intraday=False)
    assert {issue.code for issue in inspect_rows(rows, context)} == {
        "duplicate_timestamp", "negative_volume"
    }
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/data/test_quality.py -v`
Expected: FAIL because `inspect_rows` is missing.

- [ ] **Step 3: Implement deterministic validation**

```python
# src/astock/data/quality.py
from dataclasses import dataclass
from collections import Counter
from datetime import date, time


@dataclass(frozen=True)
class QualityIssue:
    code: str
    timestamp: object
    detail: str


@dataclass(frozen=True)
class QualityContext:
    valid_trading_dates: set[date]
    intraday: bool


def inspect_rows(rows: list[dict], context: QualityContext) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    counts = Counter(row["timestamp"] for row in rows)
    for timestamp, count in counts.items():
        if count > 1:
            issues.append(QualityIssue("duplicate_timestamp", timestamp, f"count={count}"))
    for row in rows:
        timestamp = row["timestamp"]
        if row["volume_shares"] < 0:
            issues.append(QualityIssue("negative_volume", timestamp, "volume < 0"))
        if row["amount_cny"] < 0:
            issues.append(QualityIssue("negative_amount", timestamp, "amount < 0"))
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
            issues.append(QualityIssue("invalid_ohlc", timestamp, "OHLC bounds"))
        if timestamp.date() not in context.valid_trading_dates:
            issues.append(QualityIssue("invalid_trading_date", timestamp, "market closed"))
        if context.intraday and not (
            time(9, 30) < timestamp.time() <= time(11, 30)
            or time(13, 0) < timestamp.time() <= time(15, 0)
        ):
            issues.append(QualityIssue("invalid_session_time", timestamp, "outside A-share session"))
    return issues
```

Before the row loop, append `QualityIssue("non_monotonic_input", rows[0]["timestamp"], "timestamps not ascending")` when adjacent timestamps descend. Add tests for descending input, non-trading dates, timestamps outside both sessions, invalid OHLC, negative amount and valid zero-volume suspension bars. The service records `non_monotonic_input`, sorts those otherwise valid rows before persistence, and blocks persistence for every other issue. Quote freshness is checked against an injected clock before live use, because it is not a historical-bar property.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/data/test_quality.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/data/quality.py tests/data/test_quality.py
git commit -m "feat: validate market data before storage"
```

### Task 7: Add the BaoStock history adapter

**Files:**
- Create: `src/astock/data/providers/__init__.py`
- Create: `src/astock/data/providers/base.py`
- Create: `src/astock/data/providers/baostock.py`
- Test: `tests/data/providers/test_baostock.py`

- [ ] **Step 1: Write adapter test using a fake BaoStock module**

```python
from datetime import date
from astock.data.providers.baostock import BaoStockProvider
from astock.domain.market import Timeframe


def test_baostock_converts_volume_from_shares(fake_baostock) -> None:
    fake_baostock.rows = [["2026-08-20", "sh.600519", "10", "11", "9", "10.5", "12300", "129150"]]
    bars = BaoStockProvider(fake_baostock).history("600519.SH", Timeframe.DAY,
                                                   date(2026, 8, 20), date(2026, 8, 20))
    assert bars[0].volume_shares == 12_300
    assert bars[0].symbol == "600519.SH"
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/data/providers/test_baostock.py -v`
Expected: FAIL because adapter is missing.

- [ ] **Step 3: Define provider protocol and adapter**

```python
# src/astock/data/providers/base.py
from datetime import date
from typing import Protocol
from astock.domain.market import Adjustment, Bar, Quote, Timeframe


class HistoryProvider(Protocol):
    def history(self, symbol: str, timeframe: Timeframe, start: date, end: date,
                adjustment: Adjustment = Adjustment.NONE) -> list[Bar]: ...


class QuoteProvider(Protocol):
    def quotes(self, symbols: list[str]) -> list[Quote]: ...


class ReferenceDataProvider(Protocol):
    def trading_dates(self, start: date, end: date) -> set[date]: ...
    def symbols_on(self, on_date: date) -> list[dict]: ...
    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]: ...
    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]: ...
    def security_status(self, symbol: str, start: date, end: date) -> list[dict]: ...
```

Implement `BaoStockProvider.history()` with explicit field lists for `1d` and `5m`, anonymous login/logout in a context manager, Shanghai timezone parsing, `sh.600519`/`sz.000001` conversion, and `adjustflag` mapping `{none: "3", qfq: "2", hfq: "1"}`. Implement the reference methods with recorded responses from `query_trade_dates`, `query_all_stock`, `query_adjust_factor`, `query_dividend_data` and daily `tradestatus/isST` fields; normalize dividend/bonus values to per-share cash and share ratios. `security_status()` derives board from the point-in-time code segment and stores the date-specific ST/suspension state plus calculated price limits; it must include focused fixtures for main board, ChiNext/STAR, Beijing, ST and newly listed securities with no daily price limit.

- [ ] **Step 4: Run recorded adapter tests**

Run: `python -m pytest tests/data/providers/test_baostock.py -v`
Expected: all BaoStock adapter tests PASS without network access.

- [ ] **Step 5: Commit**

```bash
git add src/astock/data/providers tests/data/providers/test_baostock.py
git commit -m "feat: adapt BaoStock historical bars"
```

### Task 8: Add the mootdx real-time adapter

**Files:**
- Create: `src/astock/data/providers/mootdx.py`
- Test: `tests/data/providers/test_mootdx.py`

- [ ] **Step 1: Write lot-to-share and stale-time tests**

```python
from astock.data.providers.mootdx import MootdxProvider


def test_mootdx_converts_a_share_lots(fake_mootdx_client) -> None:
    fake_mootdx_client.quote_frame("600519", price=10.5, volume=123, amount=129150)
    quote = MootdxProvider(fake_mootdx_client).quotes(["600519.SH"])[0]
    assert quote.volume_shares == 12_300
    assert quote.price == 10.5
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/data/providers/test_mootdx.py -v`
Expected: FAIL because `MootdxProvider` is missing.

- [ ] **Step 3: Implement quote and current-bar normalization**

```python
# key normalization inside MootdxProvider
Quote(
    symbol=symbol,
    timestamp=self._parse_server_time(row["servertime"]),
    price=float(row["price"]),
    volume_shares=int(row["volume"]) * 100,
    amount_cny=float(row["amount"]),
    source="mootdx",
)
```

Create the real client with `Quotes.factory(market="std", multithread=True, heartbeat=True, bestip=True)`. Keep client creation outside methods so tests inject a fake and production reuses the connection.

- [ ] **Step 4: Run adapter tests**

Run: `python -m pytest tests/data/providers/test_mootdx.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/astock/data/providers/mootdx.py tests/data/providers/test_mootdx.py
git commit -m "feat: adapt mootdx realtime quotes"
```

### Task 9: Track cached coverage and calculate missing ranges

**Files:**
- Create: `src/astock/storage/coverage.py`
- Test: `tests/storage/test_coverage.py`

- [ ] **Step 1: Write overlap and gap tests**

```python
from datetime import date
from astock.domain.market import Adjustment, Timeframe
from astock.storage.coverage import CoverageRepository


def test_missing_ranges_merge_overlapping_coverage(database) -> None:
    repo = CoverageRepository(database)
    repo.record("600519.SH", Timeframe.DAY, Adjustment.NONE,
                date(2026, 1, 1), date(2026, 1, 10))
    repo.record("600519.SH", Timeframe.DAY, Adjustment.NONE,
                date(2026, 1, 8), date(2026, 1, 20))
    assert repo.missing_ranges("600519.SH", Timeframe.DAY, Adjustment.NONE,
                               date(2026, 1, 1), date(2026, 1, 31)) == [
        (date(2026, 1, 21), date(2026, 1, 31))
    ]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/storage/test_coverage.py -v`
Expected: FAIL because `CoverageRepository` is missing.

- [ ] **Step 3: Implement interval merging and range reads**

`record()` inserts a covered interval, reads all intervals for the same symbol/timeframe/adjustment, merges overlapping or adjacent dates, and replaces them inside one transaction. `missing_ranges()` subtracts merged coverage from the requested inclusive range. Add `BarStore.read_range(symbol, timeframe, adjustment, start, end)` that filters parsed timestamps inclusively and sorts by timestamp.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/storage/test_coverage.py tests/storage/test_bars.py -v`
Expected: PASS.

```bash
git add src/astock/storage/coverage.py src/astock/storage/bars.py tests/storage
git commit -m "feat: track cached market data coverage"
```

### Task 10: Build the on-demand market-data service and CLI

**Files:**
- Create: `src/astock/data/service.py`
- Create: `src/astock/cli.py`
- Test: `tests/data/test_service.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Test cached coverage and derived periods**

```python
def test_history_downloads_once_and_derives_15m(fake_history, bar_store, database) -> None:
    service = MarketDataService(fake_history, bar_store, database)
    first = service.history("600519.SH", Timeframe.MIN_15, START, END)
    second = service.history("600519.SH", Timeframe.MIN_15, START, END)
    assert first == second
    assert fake_history.calls == [
        ("600519.SH", Timeframe.MIN_5, START, END, Adjustment.NONE)
    ]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/data/test_service.py -v`
Expected: FAIL because `MarketDataService` is missing.

- [ ] **Step 3: Implement coverage, quality gate, persistence and derivation**

```python
class MarketDataService:
    def history(self, symbol, timeframe, start, end, adjustment=Adjustment.NONE):
        base = Timeframe.MIN_5 if timeframe in {Timeframe.MIN_15, Timeframe.MIN_30, Timeframe.MIN_60} else (
            Timeframe.DAY if timeframe in {Timeframe.WEEK, Timeframe.MONTH} else timeframe
        )
        for gap_start, gap_end in self.coverage.missing_ranges(
                symbol, base, adjustment, start, end):
            incoming = self.history_provider.history(
                symbol, base, gap_start, gap_end, adjustment)
            context = QualityContext(self.calendar.open_dates(gap_start, gap_end),
                                     intraday=base == Timeframe.MIN_5)
            issues = inspect_rows([bar.model_dump() for bar in incoming], context)
            self.quality_repository.record(symbol, issues)
            blocking = [issue for issue in issues if issue.code != "non_monotonic_input"]
            if blocking:
                raise DataQualityError(blocking)
            self.bar_store.upsert(sorted(incoming, key=lambda bar: bar.timestamp))
            self.coverage.record(symbol, base, adjustment, gap_start, gap_end)
        bars = self.bar_store.read_range(symbol, base, adjustment, start, end)
        return self.derive(bars, timeframe)
```

`derive()` returns base bars unchanged, converts bars to a frame, calls `aggregate_intraday()` for 15/30/60 minutes or `aggregate_daily()` for week/month, and maps rows back to `Bar` with the requested timeframe, identical adjustment/source metadata and `is_final=True`. Add `sync_reference(start, end)` to upsert the trading calendar, daily symbol snapshots, adjustment factors, corporate actions and security status before realistic backtests.

Add CLI commands:

```text
astock data sync --symbol 600519.SH --timeframe 1d --start 2020-01-01 --end 2026-08-20
astock data smoke --provider baostock
astock data smoke --provider mootdx
```

- [ ] **Step 4: Run service, CLI and full foundation tests**

Run: `python -m pytest -v && ruff check .`
Expected: all tests PASS and Ruff reports no errors.

- [ ] **Step 5: Run opt-in online smoke tests**

Run during a network-connected session:

```bash
astock data smoke --provider baostock
astock data smoke --provider mootdx
```

Expected: BaoStock returns at least one completed daily bar; mootdx returns a quote with positive price and a current timestamp on a trading day.

- [ ] **Step 6: Commit**

```bash
git add src/astock/data/service.py src/astock/cli.py tests
git commit -m "feat: add on-demand market data service"
```

## Milestone Verification

Run:

```bash
python -m pytest --cov=astock --cov-report=term-missing
ruff check .
astock data sync --symbol 600519.SH --timeframe 1d --start 2026-01-01 --end 2026-08-20
```

Expected:

- automated tests all PASS;
- no lint errors;
- a Parquet partition exists for `600519.SH`;
- DuckDB records matching bar coverage;
- repeated sync does not duplicate rows or call BaoStock for covered dates.
