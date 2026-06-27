from typing import Any

import pytest

from src.datasource.tdx_provider import TdxDatasourceProvider

REQUIRED_MARKET_DATA_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount"]


class FakeTdxHttpClient:
    def __init__(self, responses: dict[str, Any] | None = None, error: Exception | None = None):
        self.responses = responses or {}
        self.error = error
        self.calls: list[tuple[str, dict[str, Any] | list[Any] | None]] = []
        self.closed = False

    async def call(self, method: str, params: dict[str, Any] | list[Any] | None = None) -> Any:
        self.calls.append((method, params))
        if self.error is not None:
            raise self.error
        return self.responses[method]

    async def aclose(self) -> None:
        self.closed = True


def native_bar_rows() -> dict[str, Any]:
    return {
        "Open": {"600519.SH": {"2026-06-26T09:31:00": "10.1"}},
        "High": {"600519.SH": {"2026-06-26T09:31:00": "10.3"}},
        "Low": {"600519.SH": {"2026-06-26T09:31:00": "10.0"}},
        "Close": {"600519.SH": {"2026-06-26T09:31:00": "10.2"}},
        "Volume": {"600519.SH": {"2026-06-26T09:31:00": "1200"}},
        "Amount": {"600519.SH": {"2026-06-26T09:31:00": "12345.6"}},
    }


def native_snapshot() -> dict[str, Any]:
    return {
        "Now": "10.2",
        "Open": "10.1",
        "Max": "10.3",
        "Min": "10.0",
        "LastClose": "9.9",
        "Volume": "1200",
        "Amount": "12345.6",
        "asof": "2026-06-26T09:31:02",
    }


@pytest.mark.asyncio
async def test_get_bars_calls_tdx_market_data_and_returns_normalized_rows():
    fake_client = FakeTdxHttpClient({"get_market_data": native_bar_rows()})
    provider = TdxDatasourceProvider(fake_client)

    bars = await provider.get_bars(
        ["600519.SH"],
        period="1m",
        start_time=None,
        end_time=None,
        count=2,
    )

    assert fake_client.calls == [
        (
            "get_market_data",
            {
                "stock_list": ["600519.SH"],
                "field_list": REQUIRED_MARKET_DATA_FIELDS,
                "period": "1m",
                "start_time": None,
                "end_time": None,
                "count": 2,
            },
        )
    ]
    assert len(bars) == 1
    assert bars[0].symbol == "600519.SH"
    assert bars[0].close == 10.2


@pytest.mark.asyncio
async def test_get_snapshots_calls_tdx_snapshot_and_returns_normalized_snapshot():
    fake_client = FakeTdxHttpClient({"get_market_snapshot": native_snapshot()})
    provider = TdxDatasourceProvider(fake_client)

    snapshots = await provider.get_snapshots(["600519.SH"], fields=None)

    assert fake_client.calls == [
        (
            "get_market_snapshot",
            {
                "stock_code": "600519.SH",
                "field_list": [],
            },
        )
    ]
    assert len(snapshots) == 1
    assert snapshots[0].symbol == "600519.SH"
    assert snapshots[0].last == 10.2
    assert snapshots[0].lastClose == 9.9


@pytest.mark.asyncio
async def test_raw_call_proxies_exact_method_and_params():
    fake_client = FakeTdxHttpClient({"some_method": {"ok": True}})
    provider = TdxDatasourceProvider(fake_client)

    result = await provider.raw_call("some_method", {"x": 1})

    assert result == {"ok": True}
    assert fake_client.calls == [("some_method", {"x": 1})]


@pytest.mark.asyncio
async def test_get_sector_members_calls_tdx_sector_method_and_returns_normalized_symbols():
    fake_client = FakeTdxHttpClient({"get_stock_list_in_sector": ["SH600519", "000001.SZ"]})
    provider = TdxDatasourceProvider(fake_client)

    members = await provider.get_sector_members("通达信88")

    assert members == ["600519.SH", "000001.SZ"]
    assert fake_client.calls == [
        (
            "get_stock_list_in_sector",
            {
                "block_code": "通达信88",
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_sector_members_accepts_tdx_http_value_wrapper():
    fake_client = FakeTdxHttpClient(
        {
            "get_stock_list_in_sector": {
                "ErrorId": "0",
                "Value": ["600519.SH", "000001.SZ"],
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    members = await provider.get_sector_members("通达信88")

    assert members == ["600519.SH", "000001.SZ"]


@pytest.mark.asyncio
async def test_call_formula_passes_exact_formula_method_with_args_and_context():
    fake_response = {"value": 10.2}
    fake_client = FakeTdxHttpClient({"formula_exp": fake_response})
    provider = TdxDatasourceProvider(fake_client)

    result = await provider.call_formula(
        "formula_exp",
        {"exp": "CLOSE"},
        {"symbol": "600519.SH"},
    )

    assert result == fake_response
    assert fake_client.calls == [
        (
            "formula_exp",
            {
                "args": {"exp": "CLOSE"},
                "context": {"symbol": "600519.SH"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_collect_recent_bars_uses_count_without_date_range():
    fake_client = FakeTdxHttpClient({"get_market_data": native_bar_rows()})
    provider = TdxDatasourceProvider(fake_client)

    bars = await provider.collect_recent_bars(["600519.SH"], period="1m", count=2)

    assert fake_client.calls == [
        (
            "get_market_data",
            {
                "stock_list": ["600519.SH"],
                "field_list": REQUIRED_MARKET_DATA_FIELDS,
                "period": "1m",
                "start_time": None,
                "end_time": None,
                "count": 2,
            },
        )
    ]
    assert bars[0].symbol == "600519.SH"


@pytest.mark.asyncio
async def test_health_reports_reachability_without_live_network_when_fake_client_is_injected():
    fake_client = FakeTdxHttpClient({"get_market_snapshot": native_snapshot()})
    provider = TdxDatasourceProvider(fake_client)

    health = await provider.health()

    assert health["tdxHttpReachable"] is True
    assert health["lastError"] is None
    assert fake_client.calls == [
        (
            "get_market_snapshot",
            {
                "stock_code": "600519.SH",
                "field_list": [],
            },
        )
    ]


@pytest.mark.asyncio
async def test_health_reports_last_error_from_fake_client():
    fake_client = FakeTdxHttpClient(error=RuntimeError("boom"))
    provider = TdxDatasourceProvider(fake_client)

    health = await provider.health()

    assert health["tdxHttpReachable"] is False
    assert health["lastError"] == "boom"


@pytest.mark.asyncio
async def test_aclose_closes_underlying_client():
    fake_client = FakeTdxHttpClient()
    provider = TdxDatasourceProvider(fake_client)

    await provider.aclose()

    assert fake_client.closed is True
