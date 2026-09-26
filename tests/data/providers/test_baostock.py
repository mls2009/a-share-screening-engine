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
        fields = (
            ["code", "code_name", "ipoDate", "outDate", "type", "status"]
            if self.basic_rows and len(self.basic_rows[0]) == 6
            else ["code", "ipoDate"]
        )
        return FakeResult(fields, self.basic_rows)


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


def test_bulk_session_reuses_one_login_for_multiple_history_queries() -> None:
    fake = FakeBaoStock()
    provider = BaoStockProvider(fake)

    with provider.bulk_session():
        for symbol in ("600519.SH", "600519.SH"):
            provider.history(
                symbol,
                Timeframe.DAY,
                date(2026, 8, 20),
                date(2026, 8, 20),
                Adjustment.QFQ,
            )

    assert fake.login_calls == 1
    assert fake.logout_calls == 1


def test_history_skips_suspended_rows_with_empty_ohlc() -> None:
    fake = FakeBaoStock()
    fake.history_rows = [
        ["2026-08-19", "sh.600519", "", "", "", "", "", "", "2"],
        ["2026-08-20", "sh.600519", "10", "11", "9", "10.5", "12300", "129150", "2"],
    ]

    bars = BaoStockProvider(fake).history(
        "600519.SH",
        Timeframe.DAY,
        date(2026, 8, 19),
        date(2026, 8, 20),
        Adjustment.QFQ,
    )

    assert len(bars) == 1
    assert bars[0].timestamp.date() == date(2026, 8, 20)


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


def test_baostock_builds_complete_listed_security_universe() -> None:
    fake = FakeBaoStock()
    fake.results["all_stock"] = FakeResult(
        ["code", "tradeStatus", "code_name"],
        [
            ["sh.600519", "1", "贵州茅台"],
            ["sz.300750", "0", "宁德时代"],
            ["bj.920001", "1", "北交样例"],
        ],
    )
    fake.basic_rows = [
        ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"],
        ["sz.300750", "宁德时代", "2018-06-11", "", "1", "1"],
        ["bj.920001", "北交样例", "2025-01-02", "", "1", "1"],
    ]

    securities = BaoStockProvider(fake).securities_on(date(2026, 8, 20))

    assert [security.symbol for security in securities] == [
        "600519.SH",
        "300750.SZ",
        "920001.BJ",
    ]
    assert securities[0].board == "main"
    assert securities[1].board == "chinext"
    assert securities[2].board == "beijing"
    assert securities[0].listed_on == date(2001, 8, 27)
    assert securities[1].is_suspended is True


def test_baostock_keeps_etfs_and_filters_other_non_stock_instruments() -> None:
    fake = FakeBaoStock()
    fake.results["all_stock"] = FakeResult(
        ["code", "tradeStatus", "code_name"],
        [
            ["sh.600519", "1", "贵州茅台"],
            ["sz.159558", "1", "创业板中盘ETF"],
            ["sz.160106", "1", "南方高增LOF"],
            ["sh.113001", "1", "转债样例"],
        ],
    )
    fake.basic_rows = [
        ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"],
        ["sz.159558", "创业板中盘ETF", "2024-01-01", "", "3", "1"],
        ["sz.160106", "南方高增LOF", "2005-01-01", "", "3", "1"],
        ["sh.113001", "转债样例", "2010-01-01", "", "3", "1"],
    ]

    securities = BaoStockProvider(fake).securities_on(date(2026, 8, 20))

    assert [(item.symbol, item.instrument_type) for item in securities] == [
        ("600519.SH", "stock"),
        ("159558.SZ", "etf"),
    ]


def test_security_universe_falls_back_to_latest_completed_trading_day() -> None:
    class IntradayBaoStock(FakeBaoStock):
        def __init__(self) -> None:
            super().__init__()
            self.requested_days: list[str] = []
            self.basic_rows = [
                ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"]
            ]

        def query_all_stock(self, **kwargs: str) -> FakeResult:
            self.requested_days.append(kwargs["day"])
            rows = (
                []
                if kwargs["day"] == "2026-08-20"
                else [["sh.600519", "1", "贵州茅台"]]
            )
            return FakeResult(["code", "tradeStatus", "code_name"], rows)

    fake = IntradayBaoStock()

    securities = BaoStockProvider(fake).securities_on(date(2026, 8, 20))

    assert [security.symbol for security in securities] == ["600519.SH"]
    assert fake.requested_days == ["2026-08-20", "2026-08-19"]


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
            "limit_up": 11.0,
            "limit_down": 9.0,
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


def test_chinext_risk_warning_keeps_board_limit():
    fake = FakeBaoStock()
    fake.history_rows = [["2026-08-20", "sz.300001", "10", "1", "1"]]
    rows = BaoStockProvider(fake).security_status("300001.SZ", date(2026,8,20), date(2026,8,20))
    assert rows[0]['limit_up'] == 12
    assert rows[0]['limit_down'] == 8


def test_history_checks_error_after_result_iteration():
    import pytest

    from astock.data.providers.baostock import BaoStockError
    class Interrupted(FakeResult):
        def next(self):
            self.error_code = '10002007'
            self.error_msg = 'response interrupted'
            return False
    fake = FakeBaoStock()
    fake.query_history_k_data_plus = lambda **kw: Interrupted(kw['fields'].split(','), [])
    with pytest.raises(BaoStockError, match='interrupted'):
        BaoStockProvider(fake).history('600519.SH', Timeframe.DAY, date(2026,8,20), date(2026,8,20))


def test_limit_rate_main_st_widened_to_ten_percent_from_2026_07_06() -> None:
    from decimal import Decimal

    from astock.data.providers.baostock import limit_rate

    # 沪深交易所 2026-07-06 起，主板 ST/*ST 涨跌幅由 5% 调整为 10%
    assert limit_rate(True, "main", date(2026, 7, 3)) == Decimal("0.05")
    assert limit_rate(True, "main", date(2026, 7, 6)) == Decimal("0.10")
    assert limit_rate(True, "main", date(2026, 9, 18)) == Decimal("0.10")
    # 非风险警示主板一直是 10%
    assert limit_rate(False, "main", date(2026, 7, 3)) == Decimal("0.10")
    # 创业板 2020-08-24 注册制改革前后
    assert limit_rate(True, "chinext", date(2020, 8, 21)) == Decimal("0.05")
    assert limit_rate(True, "chinext", date(2020, 8, 24)) == Decimal("0.20")
    # 科创板/北交所维持不变
    assert limit_rate(True, "star", date(2026, 9, 18)) == Decimal("0.20")
    assert limit_rate(True, "beijing", date(2026, 9, 18)) == Decimal("0.30")


def test_price_limit_rounds_half_up() -> None:
    from decimal import Decimal

    from astock.data.providers.baostock import BaoStockProvider

    # *ST中迪 2026-09-18：前收 9.38。旧 5% 规则误算出 9.85 假涨停价，
    # 真实 10% 规则涨停价应为 10.32。
    assert BaoStockProvider._price_limit(9.38, Decimal("0.05")) == (9.85, 8.91)
    assert BaoStockProvider._price_limit(9.38, Decimal("0.10")) == (10.32, 8.44)


def test_security_status_uses_widened_st_limit() -> None:
    fake = FakeBaoStock()
    fake.history_rows = [
        ["2026-07-03", "sh.600001", "9.62", "1", "1"],
        ["2026-07-06", "sh.600001", "9.62", "1", "1"],
    ]
    statuses = BaoStockProvider(fake).security_status(
        "600001.SH", date(2026, 7, 3), date(2026, 7, 6)
    )
    by_date = {str(row["trade_date"]): row for row in statuses}
    assert by_date["2026-07-03"]["limit_up"] == 10.10  # 旧规则 5%
    assert by_date["2026-07-06"]["limit_up"] == 10.58  # 新规则 10%
    assert by_date["2026-07-06"]["limit_down"] == 8.66
