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
async def test_get_sector_list_calls_tdx_sector_list_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_sector_list": {
                "ErrorId": "0",
                "Value": [{"Code": "880081.SH", "Name": "通达信88"}],
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    sectors = await provider.get_sector_list(1)

    assert sectors[0]["code"] == "880081.SH"
    assert sectors[0]["name"] == "通达信88"
    assert fake_client.calls == [("get_sector_list", {"list_type": 1})]


@pytest.mark.asyncio
async def test_get_trading_dates_calls_tdx_calendar_method():
    fake_client = FakeTdxHttpClient(
        {"get_trading_dates": {"ErrorId": "0", "Value": ["2026-06-25", "2026-06-26"]}}
    )
    provider = TdxDatasourceProvider(fake_client)

    dates = await provider.get_trading_dates("SH", count=2)

    assert dates == ["2026-06-25", "2026-06-26"]
    assert fake_client.calls == [
        (
            "get_trading_dates",
            {
                "market": "SH",
                "start_time": "",
                "end_time": "",
                "count": 2,
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_securities_calls_tdx_stock_list_method():
    fake_client = FakeTdxHttpClient({"get_stock_list": {"Value": ["SH600519"]}})
    provider = TdxDatasourceProvider(fake_client)

    securities = await provider.get_securities("5")

    assert securities[0]["symbol"] == "600519.SH"
    assert fake_client.calls == [("get_stock_list", {"market": "5"})]


@pytest.mark.asyncio
async def test_get_security_info_combines_stock_and_more_info():
    fake_client = FakeTdxHttpClient(
        {
            "get_stock_info": {"Name": "贵州茅台", "Market": "SH"},
            "get_more_info": {"Industry": "白酒"},
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    securities = await provider.get_security_info(["600519.SH"])

    assert securities[0]["symbol"] == "600519.SH"
    assert securities[0]["name"] == "贵州茅台"
    assert securities[0]["more"] == {"Industry": "白酒"}
    assert fake_client.calls == [
        ("get_stock_info", {"stock_code": "600519.SH"}),
        ("get_more_info", {"stock_code": "600519.SH", "field_list": []}),
    ]


@pytest.mark.asyncio
async def test_get_price_volume_calls_tdx_pricevol_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_pricevol": {
                "Value": {
                    "600519.SH": {
                        "Now": "1168.63",
                        "Volume": "1000",
                        "Amount": "1168630",
                    }
                }
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_price_volume(["600519.SH"], fields=["price", "volume"])

    assert items[0]["symbol"] == "600519.SH"
    assert items[0]["price"] == 1168.63
    assert items[0]["volume"] == 1000.0
    assert fake_client.calls == [
        (
            "get_pricevol",
            {
                "stock_list": ["600519.SH"],
                "field_list": ["price", "volume"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_security_relations_calls_tdx_relation_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_relation": {
                "Value": {
                    "RelatedSectors": [
                        {"Code": "880081.SH", "Name": "通达信88", "Type": "industry"}
                    ]
                }
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    relations = await provider.get_security_relations("600519.SH")

    assert relations == [
        {
            "symbol": "600519.SH",
            "category": "industry",
            "code": "880081.SH",
            "name": "通达信88",
            "provider": "tdx",
            "raw": {"Code": "880081.SH", "Name": "通达信88", "Type": "industry"},
        }
    ]
    assert fake_client.calls == [("get_relation", {"stock_code": "600519.SH"})]


@pytest.mark.asyncio
async def test_get_ipo_info_calls_tdx_ipo_method_and_normalizes_items():
    fake_client = FakeTdxHttpClient(
        {
            "get_ipo_info": {
                "Value": [
                    {
                        "code": "301036",
                        "name": "双乐转债",
                        "SGCode": "371036",
                        "SGDate": "20251226",
                        "SGPrice": "100.00",
                    }
                ]
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_ipo_info(ipo_type=2, ipo_date=1)

    assert items[0]["code"] == "301036"
    assert items[0]["subscribeCode"] == "371036"
    assert items[0]["subscribeDate"] == "20251226"
    assert items[0]["issuePrice"] == 100.0
    assert fake_client.calls == [("get_ipo_info", {"ipo_type": 2, "ipo_date": 1})]


@pytest.mark.asyncio
async def test_get_share_capital_calls_tdx_gb_info_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_gb_info": {
                "Value": [
                    {"Date": 20250101, "Zgb": "182942480", "Ltgb": "182942480"}
                ]
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_share_capital("600519.SH", ["20250101"], 1)

    assert items[0]["symbol"] == "600519.SH"
    assert items[0]["date"] == "20250101"
    assert items[0]["totalShareCapital"] == 182942480.0
    assert items[0]["floatShareCapital"] == 182942480.0
    assert fake_client.calls == [
        (
            "get_gb_info",
            {
                "stock_code": "600519.SH",
                "date_list": ["20250101"],
                "count": 1,
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_share_capital_by_date_calls_tdx_gb_info_by_date_method():
    fake_client = FakeTdxHttpClient(
        {"get_gb_info_by_date": {"Value": [{"Date": "20250101", "Zgb": 1, "Ltgb": 2}]}}
    )
    provider = TdxDatasourceProvider(fake_client)

    await provider.get_share_capital_by_date("600519.SH", "20250101", "20250601")

    assert fake_client.calls == [
        (
            "get_gb_info_by_date",
            {
                "stock_code": "600519.SH",
                "start_date": "20250101",
                "end_date": "20250601",
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_dividend_factors_calls_tdx_divid_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_divid_factors": {
                "Value": [
                    {
                        "Date": "20250101",
                        "Type": "1",
                        "Bonus": "1.23",
                        "ShareBonus": "0.5",
                    }
                ]
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_dividend_factors("600519.SH", "20250101", "20251231")

    assert items[0]["symbol"] == "600519.SH"
    assert items[0]["bonus"] == 1.23
    assert items[0]["shareBonus"] == 0.5
    assert fake_client.calls == [
        (
            "get_divid_factors",
            {
                "stock_code": "600519.SH",
                "start_time": "20250101",
                "end_time": "20251231",
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_convertible_bond_info_calls_selected_tdx_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_kzz_info": {
                "Value": {
                    "KZZCode": "123039",
                    "HSCode": "300577",
                    "ZGPrice": "29.15",
                    "KZZPrice": "120.50",
                }
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_convertible_bond_info(
        "123039.SZ",
        fields=["KZZCode", "HSCode"],
        native_method="get_kzz_info",
    )

    assert items[0]["symbol"] == "123039.SZ"
    assert items[0]["bondCode"] == "123039"
    assert items[0]["underlyingSymbol"] == "300577"
    assert items[0]["convertPrice"] == 29.15
    assert fake_client.calls == [
        (
            "get_kzz_info",
            {
                "stock_code": "123039.SZ",
                "field_list": ["KZZCode", "HSCode"],
            },
        )
    ]


@pytest.mark.asyncio
async def test_get_tracking_etfs_calls_tdx_trackzs_method():
    fake_client = FakeTdxHttpClient(
        {
            "get_trackzs_etf_info": {
                "Value": [
                    {"Code": "510300.SH", "Name": "沪深300ETF", "NowPrice": "4.21"}
                ]
            }
        }
    )
    provider = TdxDatasourceProvider(fake_client)

    items = await provider.get_tracking_etfs("950162.CSI")

    assert items[0]["indexSymbol"] == "950162.CSI"
    assert items[0]["symbol"] == "510300.SH"
    assert items[0]["price"] == 4.21
    assert fake_client.calls == [
        ("get_trackzs_etf_info", {"zs_code": "950162.CSI"})
    ]


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
