import argparse
import json
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from astock.config import Settings
from astock.data.market_sync import MarketSyncService
from astock.data.providers.base import QuoteProvider
from astock.data.providers.fallback import FallbackQuoteProvider
from astock.data.providers.mootdx import MootdxProvider, create_mootdx_client
from astock.data.providers.routing import build_default_market_providers
from astock.data.providers.tencent import TencentQuoteProvider
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Timeframe
from astock.features.builder import FeatureBuilder
from astock.features.store import MarketFeatureStore
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.models import Node
from astock.screening.service import ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository

SHANGHAI = ZoneInfo("Asia/Shanghai")


def build_market_data_service() -> MarketDataService:
    settings = Settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.migrate()
    history_provider, reference_provider = build_default_market_providers()
    return MarketDataService(
        history_provider=history_provider,
        reference_provider=reference_provider,
        bar_store=BarStore(settings.bars_dir),
        database=database,
    )


def build_quote_provider(name: str) -> QuoteProvider:
    providers: dict[str, Callable[[], QuoteProvider]] = {
        "mootdx": MootdxProvider,
        "tencent": TencentQuoteProvider,
    }
    if name == "auto":
        return FallbackQuoteProvider(
            [
                (
                    "mootdx",
                    lambda: MootdxProvider(client=create_mootdx_client(servers=[])),
                ),
                ("tencent", providers["tencent"]),
            ]
        )
    return providers[name]()


def build_market_sync_service() -> MarketSyncService:
    settings = Settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.migrate()
    history_provider, reference_provider = build_default_market_providers()
    bars = BarStore(settings.bars_dir)
    market_data = MarketDataService(
        history_provider, bars, database, reference_provider=reference_provider
    )
    feature_store = MarketFeatureStore(database)
    return MarketSyncService(
        market_data,
        reference_provider,
        SyncJobRepository(database.connection),
        FeatureBuilder(bars, feature_store, database),
    )


def build_screening_service() -> ScreeningService:
    settings = Settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.migrate()
    return ScreeningService(
        database,
        MarketFeatureStore(database),
        snapshot_provider=TencentQuoteProvider(),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astock")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data", help="行情数据操作")
    data_commands = data.add_subparsers(dest="data_command", required=True)

    sync = data_commands.add_parser("sync", help="同步历史行情")
    sync.add_argument("--symbol", required=True)
    sync.add_argument("--timeframe", choices=[item.value for item in Timeframe], required=True)
    sync.add_argument("--start", type=date.fromisoformat, required=True)
    sync.add_argument("--end", type=date.fromisoformat, required=True)
    sync.add_argument(
        "--adjustment",
        choices=[item.value for item in Adjustment],
        default=Adjustment.NONE.value,
    )

    smoke = data_commands.add_parser("smoke", help="在线数据源冒烟测试")
    smoke.add_argument(
        "--provider",
        choices=["auto", "baostock", "mootdx", "tencent"],
        default="auto",
    )

    sync_market = data_commands.add_parser("sync-market", help="同步全市场日线与特征")
    sync_market.add_argument("--years", type=int, default=3)
    sync_market.add_argument(
        "--end", type=date.fromisoformat, default=datetime.now(SHANGHAI).date()
    )

    sync_status = data_commands.add_parser("sync-status", help="查看全市场同步状态")
    sync_status.add_argument("job_id", type=UUID)

    retry_failed = data_commands.add_parser("retry-failed", help="重试失败股票")
    retry_failed.add_argument("job_id", type=UUID)

    screen = commands.add_parser("screen", help="选股操作")
    screen_commands = screen.add_subparsers(dest="screen_command", required=True)
    screen_commands.add_parser("catalog", help="输出可用筛选指标")
    validate = screen_commands.add_parser("validate", help="校验条件 JSON")
    validate.add_argument("file", type=Path)
    run = screen_commands.add_parser("run", help="执行条件筛选")
    run.add_argument("file", type=Path)
    run.add_argument("--mode", choices=["close", "live"], default="close")
    run.add_argument(
        "--as-of", type=date.fromisoformat, default=datetime.now(SHANGHAI).date()
    )
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--offset", type=int, default=0)
    results = screen_commands.add_parser("results", help="读取筛选结果")
    results.add_argument("run_id", type=UUID)
    results.add_argument("--limit", type=int, default=100)
    results.add_argument("--offset", type=int, default=0)
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, default=str))


def _summary(summary: object) -> dict:
    return {
        "job_id": str(summary.job_id),
        "status": summary.status,
        "total": summary.total,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
    }


def main(
    argv: Sequence[str] | None = None,
    service_factory: Callable[[], MarketDataService] = build_market_data_service,
    quote_provider_factory: Callable[[str], QuoteProvider] = build_quote_provider,
    market_sync_factory: Callable[[], MarketSyncService] = build_market_sync_service,
    screening_service_factory: Callable[[], ScreeningService] = build_screening_service,
) -> int:
    args = _parser().parse_args(argv)

    if args.command == "screen":
        if args.screen_command == "catalog":
            _print_json(
                [
                    {
                        "key": metric.key,
                        "label": metric.label,
                        "unit": metric.unit.value,
                        "timeframes": sorted(item.value for item in metric.timeframes),
                        "operators": sorted(item.value for item in metric.operators),
                    }
                    for metric in DEFAULT_CATALOG.all()
                ]
            )
            return 0
        service = screening_service_factory()
        if args.screen_command in {"validate", "run"}:
            tree = TypeAdapter(Node).validate_json(args.file.read_text(encoding="utf-8"))
            if args.screen_command == "validate":
                issues = service.validate(tree)
                _print_json([issue.__dict__ for issue in issues])
                return 1 if issues else 0
            result = service.run(
                tree,
                as_of=args.as_of,
                mode=args.mode,
                limit=args.limit,
                offset=args.offset,
            )
            _print_json(
                {
                    "run_id": str(result.run_id),
                    "status": result.status,
                    "universe_size": result.universe_size,
                    "realtime_covered": result.realtime_covered,
                    "failed_batches": result.failed_batches,
                    "matches": [
                        {
                            "symbol": match.symbol,
                            "rank": match.rank,
                            "result": match.explanation.result.value,
                            "actual": match.explanation.actual,
                        }
                        for match in result.matches
                    ],
                }
            )
            return 0
        _print_json(service.results(args.run_id, args.limit, args.offset))
        return 0

    if args.data_command == "sync":
        service = service_factory()
        service.sync_reference([args.symbol], args.start, args.end)
        bars = service.history(
            args.symbol,
            Timeframe(args.timeframe),
            args.start,
            args.end,
            Adjustment(args.adjustment),
        )
        print(f"同步完成：{args.symbol} {args.timeframe}，共 {len(bars)} 根 K 线")
        return 0

    if args.data_command == "sync-market":
        _print_json(_summary(market_sync_factory().start(args.end, args.years)))
        return 0

    if args.data_command == "sync-status":
        _print_json(_summary(market_sync_factory().status(args.job_id)))
        return 0

    if args.data_command == "retry-failed":
        _print_json(_summary(market_sync_factory().retry_failed(args.job_id)))
        return 0

    if args.provider == "baostock":
        service = service_factory()
        end = datetime.now(SHANGHAI).date()
        start = end - timedelta(days=14)
        service.sync_reference(["600519.SH"], start, end)
        bars = service.history("600519.SH", Timeframe.DAY, start, end)
        if not bars:
            raise RuntimeError("BaoStock 未返回日线数据")
        print(f"BaoStock 正常：最新日线 {bars[-1].timestamp.isoformat()}")
        return 0

    quotes = quote_provider_factory(args.provider).quotes(["600519.SH"])
    if not quotes:
        raise RuntimeError(f"{args.provider} 未返回实时报价")
    quote = quotes[0]
    print(f"{quote.source} 正常：价格 {quote.price}，时间 {quote.timestamp.isoformat()}")
    return 0
