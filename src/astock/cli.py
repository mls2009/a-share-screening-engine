import argparse
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astock.config import Settings
from astock.data.providers.baostock import BaoStockProvider
from astock.data.providers.base import QuoteProvider
from astock.data.providers.fallback import FallbackQuoteProvider
from astock.data.providers.mootdx import MootdxProvider, create_mootdx_client
from astock.data.providers.tencent import TencentQuoteProvider
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Timeframe
from astock.storage.bars import BarStore
from astock.storage.database import Database

SHANGHAI = ZoneInfo("Asia/Shanghai")


def build_market_data_service() -> MarketDataService:
    settings = Settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.migrate()
    provider = BaoStockProvider()
    return MarketDataService(
        history_provider=provider,
        reference_provider=provider,
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
    return parser


def main(
    argv: Sequence[str] | None = None,
    service_factory: Callable[[], MarketDataService] = build_market_data_service,
    quote_provider_factory: Callable[[str], QuoteProvider] = build_quote_provider,
) -> int:
    args = _parser().parse_args(argv)
    if args.command != "data":
        return 2

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
