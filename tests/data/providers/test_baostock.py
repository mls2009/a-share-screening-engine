from datetime import date

from astock.data.providers.baostock import BaoStockProvider
from astock.domain.market import Adjustment, Timeframe


class FakeResponse:
    error_code = "0"
    error_msg = "success"


class FakeResult(FakeResponse):
    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.fields = fields
        self._rows = iter(rows)
        self._current: list[str] | None = None

    def next(self) -> bool:
        self._current = next(self._rows, None)
        return self._current is not None

    def get_row_data(self) -> list[str]:
        assert self._current is not None
        return self._current


class FakeBaoStock:
    def __init__(self) -> None:
        self.login_calls = 0
        self.logout_calls = 0
        self.history_kwargs: dict = {}
        self.history_rows = [
            ["2026-08-20", "sh.600519", "10", "11", "9", "10.5", "12300", "129150", "3"]
        ]
        self.results: dict[str, FakeResult] = {}
        self.basic_rows = [["sh.600519", "2001-08-27"]]

    def login(self) -> FakeResponse:
        self.login_calls += 1
        return FakeResponse()

    def logout(self) -> FakeResponse:
        self.logout_calls += 1
        return FakeResponse()

    def query_history_k_data_plus(self, **kwargs: str) -> FakeResult:
        self.history_kwargs = kwargs
        fields = kwargs["fields"].split(",")
        return FakeResult(fields, self.history_rows)

    def query_trade_dates(self, **kwargs: str) -> FakeResult:
        return self.results["trade_dates"]

    def query_all_stock(self, **kwargs: str) -> FakeResult:
        return self.results["all_stock"]

    def query_adjust_factor(self, **kwargs: str) -> FakeResult:
        return self.results["adjust_factor"]

    def query_dividend_data(self, **kwargs: str) -> FakeResult:
        return self.results["dividend"]

    def query_stock_basic(self, **kwargs: str) -> FakeResult:
        return FakeResult(["code", "ipoDate"], self.basic_rows)


def test_baostock_normalizes_daily_history() -> None:
    fake = FakeBaoStock()

    bars = BaoStockProvider(fake).history(
        "600519.SH",
        Timeframe.DAY,
        date(2026, 8, 20),
        date(2026, 8, 20),
        Adjustment.NONE,
    )

    assert bars[0].volume_shares == 12_300
    assert bars[0].symbol == "600519.SH"
    assert bars[0].timestamp.isoformat() == "2026-08-20T15:00:00+08:00"
    assert fake.history_kwargs["code"] == "sh.600519"
    assert fake.history_kwargs["frequency"] == "d"
    assert fake.history_kwargs["adjustflag"] == "3"
    assert fake.login_calls == fake.logout_calls == 1


def test_baostock_normalizes_five_minute_history() -> None:
    fake = FakeBaoStock()
    fake.history_rows = [
        [
            "2026-08-20",
            "20260820100500000",
            "sh.600519",
            "10",
            "11",
            "9",
            "10.5",
            "12300",
            "129150",
            "3",
        ]
    ]

    bars = BaoStockProvider(fake).history(
        "600519.SH",
        Timeframe.MIN_5,
        date(2026, 8, 20),
        date(2026, 8, 20),
        Adjustment.QFQ,
    )

    assert bars[0].timestamp.isoformat() == "2026-08-20T10:05:00+08:00"
    assert bars[0].timeframe == Timeframe.MIN_5
    assert bars[0].adjustment == Adjustment.QFQ
    assert fake.history_kwargs["frequency"] == "5"
    assert fake.history_kwargs["adjustflag"] == "2"


def test_baostock_normalizes_reference_data() -> None:
    fake = FakeBaoStock()
    fake.results = {
        "trade_dates": FakeResult(
            ["calendar_date", "is_trading_day"],
            [["2026-08-20", "1"], ["2026-08-22", "0"]],
        ),
        "all_stock": FakeResult(
            ["code", "tradeStatus", "code_name"],
            [["sh.600519", "1", "贵州茅台"]],
        ),
        "adjust_factor": FakeResult(
            ["code", "dividOperateDate", "foreAdjustFactor", "backAdjustFactor"],
            [["sh.600519", "2026-08-20", "0.5", "2.0"]],
        ),
        "dividend": FakeResult(
            [
                "code",
                "dividOperateDate",
                "dividCashPsBeforeTax",
                "dividStocksPs",
                "dividReserveToStockPs",
            ],
            [["sh.600519", "2026-08-20", "1.5", "0.1", "0.2"]],
        ),
    }
    provider = BaoStockProvider(fake)

    assert provider.trading_dates(date(2026, 8, 20), date(2026, 8, 22)) == {
        date(2026, 8, 20)
    }
    assert provider.symbols_on(date(2026, 8, 20)) == [
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "trade_status": "1",
            "source": "baostock",
        }
    ]
    assert provider.adjustment_factors(
        "600519.SH", date(2026, 8, 20), date(2026, 8, 20)
    ) == [
        {
            "symbol": "600519.SH",
            "trade_date": date(2026, 8, 20),
            "forward_factor": 0.5,
            "backward_factor": 2.0,
            "source": "baostock",
        }
    ]
    assert provider.corporate_actions(
        "600519.SH", date(2026, 8, 20), date(2026, 8, 20)
    ) == [
        {
            "symbol": "600519.SH",
            "ex_date": date(2026, 8, 20),
            "cash_per_share": 1.5,
            "share_ratio": 0.3,
            "source": "baostock",
        }
    ]


def test_baostock_builds_point_in_time_security_status() -> None:
    fake = FakeBaoStock()
    fake.history_rows = [["2026-08-20", "sh.600519", "10", "0", "1"]]

    rows = BaoStockProvider(fake).security_status(
        "600519.SH", date(2026, 8, 20), date(2026, 8, 20)
    )

    assert rows == [
        {
            "symbol": "600519.SH",
            "trade_date": date(2026, 8, 20),
            "board": "main",
            "is_st": True,
            "is_suspended": True,
            "previous_close": 10.0,
            "limit_up": 10.5,
            "limit_down": 9.5,
        }
    ]


def test_shenzhen_and_shanghai_ipos_have_no_limit_for_first_five_trading_days() -> None:
    fake = FakeBaoStock()
    fake.basic_rows = [["sh.600519", "2026-08-14"]]
    fake.history_rows = [
        ["2026-08-20", "sh.600519", "10", "1", "0"],
        ["2026-08-21", "sh.600519", "10", "1", "0"],
    ]
    fake.results["trade_dates"] = FakeResult(
        ["calendar_date", "is_trading_day"],
        [
            ["2026-08-14", "1"],
            ["2026-08-17", "1"],
            ["2026-08-18", "1"],
            ["2026-08-19", "1"],
            ["2026-08-20", "1"],
            ["2026-08-21", "1"],
        ],
    )

    rows = BaoStockProvider(fake).security_status(
        "600519.SH", date(2026, 8, 20), date(2026, 8, 21)
    )

    assert rows[0]["limit_up"] is None
    assert rows[0]["limit_down"] is None
    assert rows[1]["limit_up"] == 11.0
    assert rows[1]["limit_down"] == 9.0


def test_beijing_ipo_has_no_limit_only_on_first_trading_day() -> None:
    fake = FakeBaoStock()
    fake.basic_rows = [["bj.920001", "2026-08-20"]]
    fake.history_rows = [
        ["2026-08-20", "bj.920001", "10", "1", "0"],
        ["2026-08-21", "bj.920001", "10", "1", "0"],
    ]
    fake.results["trade_dates"] = FakeResult(
        ["calendar_date", "is_trading_day"],
        [["2026-08-20", "1"], ["2026-08-21", "1"]],
    )

    rows = BaoStockProvider(fake).security_status(
        "920001.BJ", date(2026, 8, 20), date(2026, 8, 21)
    )

    assert rows[0]["limit_up"] is None
    assert rows[1]["limit_up"] == 13.0
    assert rows[1]["limit_down"] == 7.0
