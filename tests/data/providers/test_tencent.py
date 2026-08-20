from urllib.parse import parse_qs, urlparse

import pytest

from astock.data.providers.tencent import (
    TencentQuoteError,
    TencentQuoteProvider,
    to_tencent_symbol,
)


def quote_row(
    key: str,
    code: str,
    *,
    price: str = "10.50",
    timestamp: str = "20260820100500",
    volume_lots: str = "123",
    amount_ten_thousand: str = "12.915",
) -> str:
    fields = [""] * 38
    fields[0] = "1"
    fields[1] = "测试股票"
    fields[2] = code
    fields[3] = price
    fields[30] = timestamp
    fields[36] = volume_lots
    fields[37] = amount_ten_thousand
    return f'v_{key}="{"~".join(fields)}";'


def test_converts_supported_a_share_symbols() -> None:
    assert to_tencent_symbol("600519.SH") == "sh600519"
    assert to_tencent_symbol("000001.SZ") == "sz000001"
    assert to_tencent_symbol("920001.BJ") == "bj920001"


def test_rejects_unsupported_symbol_suffix() -> None:
    with pytest.raises(ValueError, match="unsupported exchange"):
        to_tencent_symbol("00700.HK")


def test_parses_gbk_response_and_preserves_requested_order() -> None:
    calls: list[tuple[str, float]] = []
    body = "\n".join(
        [
            quote_row("sz000001", "000001", price="11.25"),
            quote_row("sh600519", "600519", price="10.50"),
        ]
    ).encode("gbk")

    def transport(url: str, timeout: float) -> bytes:
        calls.append((url, timeout))
        return body

    quotes = TencentQuoteProvider(transport=transport, timeout=2.5).quotes(
        ["600519.SH", "000001.SZ"]
    )

    assert [quote.symbol for quote in quotes] == ["600519.SH", "000001.SZ"]
    assert quotes[0].price == 10.5
    assert quotes[0].timestamp.isoformat() == "2026-08-20T10:05:00+08:00"
    assert quotes[0].volume_shares == 12_300
    assert quotes[0].amount_cny == 129_150
    assert quotes[0].source == "tencent"
    assert parse_qs(urlparse(calls[0][0]).query)["q"] == ["sh600519,sz000001"]
    assert calls[0][1] == 2.5


def test_skips_unmatched_and_truncated_rows() -> None:
    body = 'v_pv_none_match="1";\nv_sh600519="1~short";'.encode("gbk")
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: body)

    assert provider.quotes(["600519.SH"]) == []


def test_rejects_invalid_core_fields() -> None:
    body = quote_row("sh600519", "600519", timestamp="bad-time").encode("gbk")
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: body)

    with pytest.raises(TencentQuoteError, match="invalid quote"):
        provider.quotes(["600519.SH"])


def test_rejects_invalid_amount_field() -> None:
    body = quote_row("sh600519", "600519", amount_ten_thousand="bad").encode("gbk")
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: body)

    with pytest.raises(TencentQuoteError, match="invalid quote"):
        provider.quotes(["600519.SH"])


@pytest.mark.parametrize(
    "row",
    [
        quote_row("sh600519", "600519", price="0"),
        quote_row("sh600519", "600519", volume_lots="-1"),
        quote_row("sh600519", "600519", amount_ten_thousand="-1"),
    ],
)
def test_rejects_invalid_market_values(row: str) -> None:
    provider = TencentQuoteProvider(transport=lambda _url, _timeout: row.encode("gbk"))

    with pytest.raises(TencentQuoteError, match="invalid market values"):
        provider.quotes(["600519.SH"])


def test_wraps_transport_failure() -> None:
    def failing_transport(_url: str, _timeout: float) -> bytes:
        raise TimeoutError("timed out")

    provider = TencentQuoteProvider(transport=failing_transport)

    with pytest.raises(TencentQuoteError, match="request failed") as captured:
        provider.quotes(["600519.SH"])
    assert isinstance(captured.value.__cause__, TimeoutError)


def test_empty_request_does_not_call_transport() -> None:
    def forbidden_transport(_url: str, _timeout: float) -> bytes:
        raise AssertionError("transport must not be called")

    assert TencentQuoteProvider(transport=forbidden_transport).quotes([]) == []
