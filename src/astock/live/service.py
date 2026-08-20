from datetime import datetime
from threading import Lock
from typing import Protocol

from astock.domain.market import Quote
from astock.live.calendar import TradingCalendar
from astock.live.evaluator import evaluate_price
from astock.live.models import MonitorScope, ScanSummary
from astock.live.repository import MonitoringRepository
from astock.notifications.outbox import OutboxWorker
from astock.storage.database import Database


class QuoteSource(Protocol):
    def quotes(self, symbols: list[str]) -> list[Quote]: ...


class MonitoringService:
    def __init__(
        self,
        database: Database,
        repository: MonitoringRepository,
        quote_source: QuoteSource,
        outbox: OutboxWorker | None = None,
        max_quote_age_seconds: int = 120,
    ) -> None:
        self.database = database
        self.repository = repository
        self.quote_source = quote_source
        self.outbox = outbox
        self.max_quote_age_seconds = max_quote_age_seconds
        self._scan_lock = Lock()

    def _calendar(self, now: datetime) -> TradingCalendar:
        rows = self.database.connection.execute(
            "select trade_date from trading_calendar where is_open and trade_date = ?",
            [now.date()],
        ).fetchall()
        return TradingCalendar({row[0] for row in rows})

    def _run_locked(self, scope: MonitorScope, now: datetime, force: bool) -> ScanSummary:
        tasks = [
            task
            for task in self.repository.list_tasks(enabled=True)
            if task.scope == scope
        ]
        if scope == MonitorScope.MARKET and any(not task.symbols for task in tasks):
            rows = self.database.connection.execute(
                "select symbol from symbols where is_listed order by symbol"
            ).fetchall()
            symbols = [row[0] for row in rows]
        else:
            symbols = sorted({symbol for task in tasks for symbol in task.symbols})
        if not force and not self._calendar(now).is_live(now):
            return ScanSummary(
                scope=scope,
                tasks=len(tasks),
                requested_symbols=len(symbols),
                received_quotes=0,
                triggered=0,
                skipped_reason="outside_trading_session",
            )
        if not symbols:
            return ScanSummary(
                scope=scope,
                tasks=len(tasks),
                requested_symbols=0,
                received_quotes=0,
                triggered=0,
            )
        quotes = []
        failed = set()
        for offset in range(0, len(symbols), 60):
            batch = symbols[offset : offset + 60]
            try:
                quotes.extend(self.quote_source.quotes(batch))
            except (OSError, RuntimeError, ValueError):
                failed.update(batch)
        by_symbol = {quote.symbol: quote for quote in quotes}
        paused = {symbol: "quote_source_error" for symbol in failed}
        triggered = 0
        for symbol in symbols:
            quote = by_symbol.get(symbol)
            if quote is None:
                paused[symbol] = "missing_quote"
                continue
            age = abs((now - quote.timestamp).total_seconds())
            if age > self.max_quote_age_seconds:
                paused[symbol] = "stale_quote"
                continue
            for task in tasks:
                if task.symbols and symbol not in task.symbols:
                    continue
                state = self.repository.get_state(task.task_id, symbol)
                evaluation = evaluate_price(task, state, quote.price, now)
                created = self.repository.save_evaluation(
                    task, evaluation, quote.price, quote.timestamp
                )
                if created is not None:
                    triggered += 1
        if self.outbox is not None:
            self.outbox.deliver_due(now)
        return ScanSummary(
            scope=scope,
            tasks=len(tasks),
            requested_symbols=len(symbols),
            received_quotes=len(quotes),
            triggered=triggered,
            paused_symbols=paused,
        )

    def _run(self, scope: MonitorScope, now: datetime, force: bool) -> ScanSummary:
        with self._scan_lock:
            return self._run_locked(scope, now, force)

    def run_watchlist_once(self, now: datetime, force: bool = False) -> ScanSummary:
        return self._run(MonitorScope.WATCHLIST, now, force)

    def run_market_once(self, now: datetime, force: bool = False) -> ScanSummary:
        return self._run(MonitorScope.MARKET, now, force)
