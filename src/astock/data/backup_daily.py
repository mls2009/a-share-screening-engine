"""Backup daily sync using a complete, consistently adjusted Eastmoney history window."""

import logging
import shutil
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, time, timedelta
from threading import Event
from zoneinfo import ZoneInfo

import duckdb
import requests

from astock.data.providers.baostock import BAOSTOCK_SESSION_LOCK
from astock.domain.market import Adjustment, Bar, Timeframe

LOGGER = logging.getLogger(__name__)


class EastmoneyDaily:
    @staticmethod
    def parse(symbol, payload, start, end, adjustment):
        data = payload.get("data")
        if payload.get("rc") != 0 or not data or data.get("code") != symbol.split(".")[0]:
            raise ValueError(f"{symbol} 东方财富行情响应无效")
        result = []
        for line in data.get("klines") or []:
            fields = line.split(",")
            day = date.fromisoformat(fields[0])
            if not start <= day <= end:
                continue
            result.append(
                Bar(
                    symbol=symbol,
                    timestamp=datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai")),
                    timeframe=Timeframe.DAY,
                    open=float(fields[1]),
                    close=float(fields[2]),
                    high=float(fields[3]),
                    low=float(fields[4]),
                    volume_shares=int(float(fields[5]) * 100),
                    amount_cny=float(fields[6]),
                    adjustment=adjustment,
                    source="eastmoney-daily",
                    is_final=True,
                )
            )
        if not result:
            raise ValueError(f"{symbol} 东方财富未返回所选区间日线")
        if len({b.timestamp for b in result}) != len(result):
            raise ValueError(f"{symbol} 东方财富返回重复日期")
        return sorted(result, key=lambda b: b.timestamp)

    def history(self, symbol, start, end, adjustment=Adjustment.QFQ):
        code, exchange = symbol.split(".")
        response = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": f"{1 if exchange == 'SH' else 0}.{code}",
                "klt": 101,
                "fqt": {Adjustment.NONE: 0, Adjustment.QFQ: 1, Adjustment.HFQ: 2}[adjustment],
                "beg": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "lmt": 100000,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
            timeout=20,
        )
        response.raise_for_status()
        return self.parse(symbol, response.json(), start, end, adjustment)


class BackupDailySync:
    def __init__(self, database, bars, jobs, feature_builder, updates, provider=None):
        self.con = database.connection
        self.bars = bars
        self.jobs = jobs
        self.feature_builder = feature_builder
        self.updates = updates
        self.provider = provider or DailyHTTPProvider()
        self.stopping = Event()
        self.con.execute("""create table if not exists backup_daily_jobs (
            job_id uuid primary key, source varchar not null)""")

    def pending(self, end):
        return self.con.execute(
            """select j.job_id from data_sync_jobs j join backup_daily_jobs b using(job_id)
            where end_date=? and status in ('running','completed_with_errors')
            order by started_at desc limit 1""",
            [end],
        ).fetchone()

    def start(self, end, years=3):
        # Confirm trading days with index history; do not fabricate holidays from weekdays.
        start = date(end.year - years, 1, 1)
        calendar = self.provider.history("000001.SH", start, end, Adjustment.NONE)
        target = calendar[-1].timestamp.date()
        if target < end and end.weekday() < 5:
            calendar_row = self.con.execute(
                "select is_open from trading_calendar where trade_date=?", [end]
            ).fetchone()
            if not calendar_row or calendar_row[0]:
                raise ValueError(f"备用源指数最新 {target}，无法确认 {end} 行情已发布或当日休市")
        # Preserve stored listing metadata. The backup updates the known stock universe.
        rows = self.con.execute(
            """select s.symbol, s.listed_on, w.symbol is not null from symbols s
            left join watchlist w using(symbol)
            where s.instrument_type='stock' and s.is_listed
            and (s.listed_on is null or s.listed_on<=?)
            order by (w.symbol is not null) desc,s.symbol""",
            [target],
        ).fetchall()
        if not rows:
            raise ValueError("本地股票名单为空，不能将空任务当作更新成功")
        pending = self.pending(end)
        identifier = pending[0] if pending else self.jobs.create(start, end, len(rows))
        if pending:
            self.jobs.reopen(identifier)
        else:
            self.con.execute(
                "insert into backup_daily_jobs values (?, 'http-backup')", [identifier]
            )
        done = self.jobs.succeeded_symbols(identifier)
        watch_symbols = {symbol for symbol, _, watched in rows if watched}
        work = iter((symbol, listed) for symbol, listed, _ in rows if symbol not in done)
        LOGGER.info(
            "HTTP backup started: job=%s target=%s total=%s (cached stock universe)",
            identifier,
            target,
            len(rows),
        )
        dates = {bar.timestamp.date() for bar in calendar}
        self.con.executemany(
            "insert or replace into trading_calendar values (?,true)", [[day] for day in dates]
        )

        def fetch(symbol, listed):
            existing = self.bars.read(symbol, Timeframe.DAY, Adjustment.QFQ)
            first = existing[0].timestamp.date() if existing else start
            recent_start = (
                max(first, existing[-1].timestamp.date() - timedelta(days=35))
                if existing
                else start
            )
            incoming = self.provider.history(symbol, recent_start, target)
            by_date = {bar.timestamp.date(): bar for bar in existing}
            overlap = [bar for bar in incoming if bar.timestamp.date() in by_date]
            same_prices = bool(overlap) and all(
                abs(getattr(bar, key) - getattr(by_date[bar.timestamp.date()], key)) <= 0.011
                for bar in overlap
                for key in ("open", "high", "low", "close")
            )
            if existing and not same_prices:
                incoming = self.provider.history(symbol, min(start, first), target)
                if incoming[0].timestamp.date() > first:
                    raise ValueError("备用源历史窗口不完整，未混接不同复权口径")
                return incoming, None, incoming[-1].timestamp.date()
            changed = [
                bar
                for bar in incoming
                if bar.timestamp.date() not in by_date
                or any(
                    getattr(bar, key) != getattr(by_date[bar.timestamp.date()], key)
                    for key in ("open", "high", "low", "close", "volume_shares", "amount_cny")
                )
            ]
            return (
                changed,
                min((bar.timestamp.date() for bar in changed), default=target),
                incoming[-1].timestamp.date(),
            )

        self.bars.root.mkdir(parents=True, exist_ok=True)
        # Bound both network concurrency and retained histories. All writes remain on this single thread.
        with (
            BAOSTOCK_SESSION_LOCK,
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="astock-backup") as pool,
        ):
            queue = {}

            def enqueue():
                item = next(work, None)
                if item is not None:
                    queue[pool.submit(fetch, *item)] = item[0]

            for _ in range(4):
                enqueue()
            processed = 0
            while queue and not self.stopping.is_set():
                if processed % 50 == 0:
                    if shutil.disk_usage(self.bars.root).free < 3 * 1024**3:
                        raise RuntimeError("剩余磁盘不足 3GB，已暂停更新以保护数据库")
                    try:
                        self.con.execute("checkpoint")
                    except duckdb.TransactionException as exc:
                        if "other write transactions" not in str(exc):
                            raise
                        LOGGER.warning(
                            "Checkpoint deferred while another write transaction completes"
                        )
                # Preserve watchlist priority; otherwise consume whichever request is ready.
                future = next((f for f, symbol in queue.items() if symbol in watch_symbols), None)
                if future is None:
                    ready, _ = wait(queue, return_when=FIRST_COMPLETED)
                    future = next(iter(ready))
                symbol = queue.pop(future)
                try:
                    incoming, changed_since, latest = future.result()
                    if incoming:
                        self.bars.upsert(incoming)
                    incremental = getattr(self.feature_builder, "build_incremental_symbol", None)
                    if incremental is not None:
                        incremental(symbol, target)
                    else:
                        self.feature_builder.build_symbol(symbol, target, changed_since=changed_since)
                    if latest != target:
                        raise ValueError(
                            f"最新成交日 {latest} 早于 {target}：可能停牌或未发布，未视作当日更新成功"
                        )
                except Exception as exc:  # noqa: BLE001 - one symbol must not abort a market batch
                    self.jobs.mark_failed(identifier, symbol, str(exc))
                else:
                    self.jobs.mark_succeeded(identifier, symbol)
                processed += 1
                if processed % 50 == 0 or symbol in watch_symbols:
                    self.updates.publish()
                enqueue()
            for future in queue:
                future.cancel()
        if not self.stopping.is_set():
            self.jobs.complete(identifier)
        self.updates.publish()
        result = self.jobs.get(identifier)
        LOGGER.info(
            "HTTP backup ended: job=%s status=%s succeeded=%s failed=%s",
            identifier,
            result.status,
            result.succeeded,
            result.failed,
        )
        return result


class ResilientDailySync:
    def __init__(self, primary, backup):
        self.primary = primary
        self.backup = backup
        self._active_source = "baostock"
        self.stopping = False

    @property
    def active_source(self):
        return (
            getattr(getattr(self.backup, "provider", None), "source", "http-backup")
            if self._active_source == "http-backup"
            else self._active_source
        )

    def __getattr__(self, name):
        return getattr(self.primary, name)

    def start(self, end, years=3):
        if self.stopping:
            raise RuntimeError("服务正在停止")
        if getattr(self.backup, "pending", lambda end: None)(end):
            self._active_source = "http-backup"
            return self.backup.start(end, years)
        self._active_source = "baostock"
        try:
            return self.primary.start(end, years)
        except Exception:
            if self.stopping:
                raise
            self._active_source = "http-backup"
            LOGGER.exception("Primary daily sync failed; switching to HTTP backup")
            return self.backup.start(end, years)

    def stop(self):
        self.stopping = True
        self.backup.stopping.set()
        stop = getattr(self.primary, "stop", None)
        if stop is not None:
            stop()


class TencentDaily:
    @staticmethod
    def parse(symbol, payload, start, end, adjustment):
        code, exchange = symbol.split(".")
        key = exchange.lower() + code
        data = payload.get("data", {}).get(key)
        if payload.get("code") != 0 or not isinstance(data, dict):
            raise ValueError(f"{symbol} 腾讯历史行情响应无效")
        field = {Adjustment.NONE: "day", Adjustment.QFQ: "qfqday", Adjustment.HFQ: "hfqday"}[
            adjustment
        ]
        # The API uses `day` for instruments with no adjustment events, including indices.
        rows = data.get(field, data.get("day", []))
        result = []
        for row in rows:
            day = date.fromisoformat(row[0])
            if not start <= day <= end:
                continue
            if len(row) < 9:
                raise ValueError(f"{symbol} 腾讯历史行情缺少成交额，不以零代替")
            volume = float(row[5])
            amount = float(row[8]) * 10000
            # Verified against raw daily amount/volume: Shenzhen 000 stocks use lots; STAR uses shares.
            multiplier = 1 if key.startswith(("sh688", "sz399", "sh000")) else 100
            result.append(
                Bar(
                    symbol=symbol,
                    timestamp=datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai")),
                    timeframe=Timeframe.DAY,
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume_shares=int(volume * multiplier),
                    amount_cny=amount,
                    adjustment=adjustment,
                    source="tencent-daily",
                    is_final=True,
                )
            )
        return result

    def history(self, symbol, start, end, adjustment=Adjustment.QFQ):
        code, exchange = symbol.split(".")
        key = exchange.lower() + code
        adjust = {Adjustment.NONE: "", Adjustment.QFQ: "qfq", Adjustment.HFQ: "hfq"}[adjustment]
        result = {}
        for year in range(start.year, end.year + 1):
            until = min(end, date(year, 12, 31))
            # One daily bar per calendar day at most; retain enough rows even across holidays.
            count = (until - max(start, date(year, 1, 1))).days + 1
            response = requests.get(
                "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
                params={"param": f"{key},day,{year}-01-01,{until},{count},{adjust}"},
                timeout=20,
            )
            response.raise_for_status()
            rows = self.parse(
                symbol, response.json(), max(start, date(year, 1, 1)), until, adjustment
            )
            result.update({bar.timestamp: bar for bar in rows})
        if not result:
            raise ValueError(f"{symbol} 腾讯未返回所选区间历史日线")
        return [result[key] for key in sorted(result)]


class DailyHTTPProvider:
    def __init__(self):
        self.source = "eastmoney-daily"
        self.eastmoney = EastmoneyDaily()
        self.tencent = TencentDaily()

    def history(self, *args):
        first, second = (
            (self.eastmoney, self.tencent)
            if self.source == "eastmoney-daily"
            else (self.tencent, self.eastmoney)
        )
        try:
            return first.history(*args)
        except (requests.RequestException, ValueError):
            result = second.history(*args)
            self.source = "tencent-daily" if first is self.eastmoney else "eastmoney-daily"
            return result
