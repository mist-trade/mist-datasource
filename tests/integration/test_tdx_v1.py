from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from src.datasource.tdx_http_client import TdxHttpError
from src.datasource.tdx_models import TdxBar, TdxSnapshot
from tdx.main import app


class FakeTdxProvider:
    def __init__(self) -> None:
        self.raw_calls: list[tuple[str, dict[str, Any]]] = []
        self.sector_queries: list[str] = []
        self.sector_list_queries: list[int] = []
        self.security_list_queries: list[str] = []
        self.security_info_queries: list[list[str]] = []
        self.trading_date_queries: list[tuple[str, str | None, str | None, int | None]] = []
        self.price_volume_queries: list[tuple[list[str], list[str] | None]] = []
        self.formula_calls: list[tuple[str, Any, Any]] = []
        self.fail_bars = False

    async def get_bars(
        self,
        symbols: list[str],
        *,
        period: str,
        start_time: str | None,
        end_time: str | None,
        count: int | None,
    ) -> list[TdxBar]:
        _ = (start_time, end_time)
        if self.fail_bars:
            raise TdxHttpError(
                code="TDX_HTTP_UNAVAILABLE",
                message="TDX HTTP is unavailable",
                retryable=True,
                details={"method": "get_market_data"},
            )

        return [
            TdxBar(
                symbol=symbols[0],
                period=period,
                barTime="2026-04-06T09:31:00+08:00",
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=1000,
                amount=1500,
                receivedAt=datetime(2026, 4, 6, 9, 31, tzinfo=UTC),
            )
        ][: count or 1]

    async def get_snapshots(
        self,
        symbols: list[str],
        fields: list[str] | None = None,
    ) -> list[TdxSnapshot]:
        _ = fields
        return [
            TdxSnapshot(
                symbol=symbols[0],
                last=10.0,
                open=9.8,
                high=10.2,
                low=9.7,
                lastClose=9.6,
                volume=10000,
                amount=100000,
                asOf="2026-04-06T10:00:00+08:00",
            )
        ]

    async def raw_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.raw_calls.append((method, params))
        return {"method": method, "params": params}

    async def get_sector_members(self, sector: str) -> list[str]:
        self.sector_queries.append(sector)
        return ["600519.SH", "000001.SZ"]

    async def get_sector_list(self, list_type: int = 0) -> list[dict[str, Any]]:
        self.sector_list_queries.append(list_type)
        return [
            {"code": "880081.SH", "name": "通达信88", "provider": "tdx"},
            {"code": "880300.SH", "name": "沪深300", "provider": "tdx"},
        ]

    async def get_trading_dates(
        self,
        market: str,
        start_time: str | None,
        end_time: str | None,
        count: int | None,
    ) -> list[str]:
        self.trading_date_queries.append((market, start_time, end_time, count))
        return ["2026-06-25", "2026-06-26"]

    async def get_securities(self, market: str) -> list[dict[str, Any]]:
        self.security_list_queries.append(market)
        return [
            {"symbol": "600519.SH", "name": "贵州茅台", "provider": "tdx"},
            {"symbol": "000001.SZ", "name": "平安银行", "provider": "tdx"},
        ]

    async def get_security_info(self, symbols: list[str]) -> list[dict[str, Any]]:
        self.security_info_queries.append(symbols)
        return [
            {
                "symbol": symbols[0],
                "name": "贵州茅台",
                "market": "SH",
                "provider": "tdx",
                "raw": {"Code": symbols[0]},
            }
        ]

    async def get_price_volume(
        self,
        symbols: list[str],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.price_volume_queries.append((symbols, fields))
        return [
            {
                "symbol": symbols[0],
                "price": 1168.63,
                "volume": 1000.0,
                "amount": 1168630.0,
                "provider": "tdx",
            }
        ]

    async def call_formula(
        self,
        name: str,
        args: dict[str, Any] | list[Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.formula_calls.append((name, args, context))
        return {"name": name, "value": 42}

    async def health(self) -> dict[str, Any]:
        return {"tdxHttpReachable": True, "lastError": None}


class NonDictHealthProvider(FakeTdxProvider):
    async def health(self) -> list[str]:
        return ["not", "a", "dict"]


class FakeAdapter:
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True


class CloseAwareProvider:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class RaisingCloseProvider:
    def __init__(self) -> None:
        self.close_attempted = False

    async def aclose(self) -> None:
        self.close_attempted = True
        raise RuntimeError("provider close failed")


@pytest.fixture
async def v1_client() -> AsyncClient:
    import tdx.main

    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_adapter = tdx.main.tdx_adapter
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    tdx.main.tdx_provider = FakeTdxProvider()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_adapter = previous_adapter
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider


@pytest.mark.asyncio
async def test_providers_returns_tdx_provider_envelope(v1_client: AsyncClient) -> None:
    response = await v1_client.get("/providers", headers={"x-request-id": "req-providers"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["requestId"] == "req-providers"
    assert body["provider"] == "tdx"
    assert body["data"]["providers"][0]["id"] == "tdx"


@pytest.mark.asyncio
async def test_providers_returns_tdx_and_qmt_capability_manifests(
    v1_client: AsyncClient,
) -> None:
    response = await v1_client.get("/providers")

    assert response.status_code == 200
    body = response.json()
    providers = {provider["id"]: provider for provider in body["data"]["providers"]}

    assert set(providers) == {"tdx", "qmt"}

    tdx_families = {
        capability["family"]: capability["status"]
        for capability in providers["tdx"]["capabilities"]
    }
    qmt_families = {
        capability["family"]: capability["status"]
        for capability in providers["qmt"]["capabilities"]
    }

    assert set(tdx_families) == set(qmt_families)
    assert tdx_families["bars"] == "supported"
    assert tdx_families["snapshots"] == "supported"
    assert tdx_families["sector-members"] == "supported"
    assert tdx_families["calendar"] == "supported"
    assert tdx_families["securities"] == "supported"
    assert tdx_families["security-info"] == "supported"
    assert tdx_families["sector-list"] == "supported"
    assert tdx_families["price-volume"] == "supported"
    assert tdx_families["formulas"] == "planned"
    assert qmt_families["bars"] in {"supported", "planned", "unsupported"}
    assert qmt_families["formulas"] == "unsupported"


@pytest.mark.parametrize(
    ("path", "payload", "family", "operation"),
    [
        (
            "/v1/calendar/trading-dates/query",
            {"provider": "qmt", "market": "SH", "count": 2},
            "calendar",
            "trading-dates/query",
        ),
        (
            "/v1/securities/query",
            {"provider": "qmt", "market": "5"},
            "securities",
            "securities/query",
        ),
        (
            "/v1/securities/info/query",
            {"provider": "qmt", "symbols": ["600519.SH"]},
            "security-info",
            "securities/info/query",
        ),
        (
            "/v1/sectors/list/query",
            {"provider": "qmt", "listType": 1},
            "sector-list",
            "sectors/list/query",
        ),
        (
            "/v1/price-volume/query",
            {"provider": "qmt", "symbols": ["600519.SH"]},
            "price-volume",
            "price-volume/query",
        ),
    ],
)
@pytest.mark.asyncio
async def test_qmt_provider_requests_return_capability_unsupported(
    v1_client: AsyncClient,
    path: str,
    payload: dict[str, Any],
    family: str,
    operation: str,
) -> None:
    response = await v1_client.post(path, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["provider"] == "qmt"
    assert body["data"] is None
    assert body["error"]["code"] == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert body["error"]["retryable"] is False
    assert body["error"]["details"]["provider"] == "qmt"
    assert body["error"]["details"]["family"] == family
    assert body["error"]["details"]["operation"] == operation


@pytest.mark.asyncio
async def test_bars_query_returns_normalized_envelope(v1_client: AsyncClient) -> None:
    response = await v1_client.post(
        "/v1/bars/query",
        json={"symbols": ["600519.SH"], "period": "1m", "count": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "tdx"
    assert body["meta"]["transport"] == "http"
    assert body["data"]["bars"][0]["symbol"] == "600519.SH"
    assert body["data"]["bars"][0]["barTime"] == "2026-04-06T09:31:00+08:00"


@pytest.mark.asyncio
async def test_snapshots_query_returns_normalized_envelope(v1_client: AsyncClient) -> None:
    response = await v1_client.post(
        "/v1/snapshots/query",
        json={"symbols": ["600519.SH"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "tdx"
    assert body["data"]["snapshots"][0]["symbol"] == "600519.SH"
    assert body["data"]["snapshots"][0]["lastClose"] == 9.6


@pytest.mark.asyncio
async def test_raw_call_proxies_method_and_params(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post(
        "/v1/raw/tdx/call",
        json={"method": "get_market_data", "params": {"stock_list": ["SH600519"]}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["result"] == {
        "method": "get_market_data",
        "params": {"stock_list": ["SH600519"]},
    }
    assert tdx.main.tdx_provider.raw_calls == [
        ("get_market_data", {"stock_list": ["SH600519"]})
    ]


@pytest.mark.asyncio
async def test_sectors_query_returns_symbols(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post("/v1/sectors/query", json={"sector": "通达信88"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["symbols"] == ["600519.SH", "000001.SZ"]
    assert tdx.main.tdx_provider.sector_queries == ["通达信88"]


@pytest.mark.asyncio
async def test_sector_list_query_returns_normalized_sectors(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post("/v1/sectors/list/query", json={"listType": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["sectors"][0]["code"] == "880081.SH"
    assert tdx.main.tdx_provider.sector_list_queries == [1]


@pytest.mark.asyncio
async def test_calendar_query_returns_trading_dates(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post(
        "/v1/calendar/trading-dates/query",
        json={"market": "SH", "count": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["tradingDates"] == ["2026-06-25", "2026-06-26"]
    assert tdx.main.tdx_provider.trading_date_queries == [("SH", None, None, 2)]


@pytest.mark.asyncio
async def test_securities_query_returns_normalized_symbols(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post("/v1/securities/query", json={"market": "5"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["securities"][0]["symbol"] == "600519.SH"
    assert tdx.main.tdx_provider.security_list_queries == ["5"]


@pytest.mark.asyncio
async def test_security_info_query_returns_normalized_metadata(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post(
        "/v1/securities/info/query",
        json={"symbols": ["600519.SH"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["securities"][0]["name"] == "贵州茅台"
    assert tdx.main.tdx_provider.security_info_queries == [["600519.SH"]]


@pytest.mark.asyncio
async def test_price_volume_query_returns_normalized_items(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post(
        "/v1/price-volume/query",
        json={"symbols": ["600519.SH"], "fields": ["price", "volume"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["items"][0]["price"] == 1168.63
    assert tdx.main.tdx_provider.price_volume_queries == [
        (["600519.SH"], ["price", "volume"])
    ]


@pytest.mark.asyncio
async def test_formulas_call_returns_result(v1_client: AsyncClient) -> None:
    import tdx.main

    response = await v1_client.post(
        "/v1/formulas/call",
        json={"name": "MY_FORMULA", "args": {"symbol": "600519.SH"}, "context": {"period": "1d"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["result"] == {"name": "MY_FORMULA", "value": 42}
    assert tdx.main.tdx_provider.formula_calls == [
        ("MY_FORMULA", {"symbol": "600519.SH"}, {"period": "1d"})
    ]


@pytest.mark.asyncio
async def test_provider_error_returns_failure_envelope(v1_client: AsyncClient) -> None:
    import tdx.main

    tdx.main.tdx_provider.fail_bars = True
    response = await v1_client.post(
        "/v1/bars/query",
        json={"symbols": ["600519.SH"], "period": "1m", "count": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["provider"] == "tdx"
    assert body["data"] is None
    assert body["error"] == {
        "code": "TDX_HTTP_UNAVAILABLE",
        "message": "TDX HTTP is unavailable",
        "retryable": True,
        "details": {"method": "get_market_data"},
    }


@pytest.mark.asyncio
async def test_health_includes_enriched_tdx_state(v1_client: AsyncClient) -> None:
    response = await v1_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["instance"] == "tdx"
    assert "adapter" in body
    assert "connections" in body
    assert body["tdxHttpReachable"] is True
    assert body["tqInitialized"] is False
    assert body["wsConnected"] is False
    assert body["subscribedCount"] == 0
    assert body["lastCallbackAt"] is None
    assert body["lastMinuteBarAt"] is None
    assert body["eventQueueDepth"] == 0
    assert body["eventQueueCapacity"] == 0
    assert body["collectorState"] == "not_started"


@pytest.mark.asyncio
async def test_health_handles_non_dict_provider_health() -> None:
    import tdx.main

    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_adapter = tdx.main.tdx_adapter
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    tdx.main.tdx_provider = NonDictHealthProvider()
    tdx.main.tdx_bridge = None
    tdx.main.tdx_collector = None

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert response.json()["tdxHttpReachable"] is False
    finally:
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_adapter = previous_adapter
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider


@pytest.mark.asyncio
async def test_lifespan_shutdown_clears_adapter_before_next_health(monkeypatch) -> None:
    import tdx.main

    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_adapter = tdx.main.tdx_adapter
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    fake_adapter = FakeAdapter()
    monkeypatch.setattr(tdx.main, "create_tdx_adapter", lambda: fake_adapter)
    monkeypatch.setattr(tdx.main, "TdxDatasourceProvider", CloseAwareProvider)
    tdx.main.tdx_provider = None
    tdx.main.tdx_bridge = None
    tdx.main.tdx_collector = None

    try:
        async with tdx.main.lifespan(app):
            assert tdx.main.tdx_adapter is fake_adapter

        assert fake_adapter.shutdown_called is True
        assert tdx.main.tdx_adapter is None

        tdx.main.tdx_provider = FakeTdxProvider()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        assert response.json()["tqInitialized"] is False
    finally:
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_adapter = previous_adapter
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider


@pytest.mark.asyncio
async def test_lifespan_closes_owned_provider_not_replacement(monkeypatch) -> None:
    import tdx.main

    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_adapter = tdx.main.tdx_adapter
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    fake_adapter = FakeAdapter()
    owned_provider = CloseAwareProvider()
    replacement_provider = CloseAwareProvider()
    monkeypatch.setattr(tdx.main, "create_tdx_adapter", lambda: fake_adapter)
    monkeypatch.setattr(tdx.main, "TdxDatasourceProvider", lambda: owned_provider)
    tdx.main.tdx_provider = None
    tdx.main.tdx_bridge = None
    tdx.main.tdx_collector = None

    try:
        async with tdx.main.lifespan(app):
            assert tdx.main.tdx_provider is owned_provider
            tdx.main.tdx_provider = replacement_provider

        assert owned_provider.closed is True
        assert replacement_provider.closed is False
        assert tdx.main.tdx_provider is replacement_provider
    finally:
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_adapter = previous_adapter
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider


@pytest.mark.asyncio
async def test_lifespan_shutdown_cleans_adapter_when_provider_close_raises(monkeypatch) -> None:
    import tdx.main

    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_adapter = tdx.main.tdx_adapter
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    fake_adapter = FakeAdapter()
    owned_provider = RaisingCloseProvider()
    monkeypatch.setattr(tdx.main, "create_tdx_adapter", lambda: fake_adapter)
    monkeypatch.setattr(tdx.main, "TdxDatasourceProvider", lambda: owned_provider)
    tdx.main.tdx_provider = None
    tdx.main.tdx_bridge = None
    tdx.main.tdx_collector = None

    try:
        with pytest.raises(RuntimeError, match="provider close failed"):
            async with tdx.main.lifespan(app):
                assert tdx.main.tdx_provider is owned_provider

        assert owned_provider.close_attempted is True
        assert fake_adapter.shutdown_called is True
        assert tdx.main.tdx_adapter is None
        assert tdx.main.tdx_provider is None
        assert tdx.main._tdx_provider_owned_by_main is None
    finally:
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_adapter = previous_adapter
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider
