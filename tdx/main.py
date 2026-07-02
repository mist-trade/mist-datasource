"""TDX 适配器 FastAPI 应用入口 (Port 9001).

启动方式: uvicorn tdx.main:app --port 9001 --reload
对应 TDX SDK: tqcenter.tq (通过 MarketDataAdapter 适配器层调用)
"""

from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.adapter import create_tdx_adapter
from src.adapter.base import MarketDataAdapter
from src.core.config import settings
from src.core.logging import setup_logging
from src.datasource.tdx_bridge import TdxBridge
from src.datasource.tdx_collector import TdxMinuteCollector
from src.datasource.tdx_models import TdxSnapshot
from src.datasource.tdx_provider import TdxDatasourceProvider
from src.datasource.tdx_subscription import TdxSubscriptionClient
from src.ws.manager import ConnectionManager
from src.ws.protocol import ws_quote
from tdx.routes.client import router as client_router
from tdx.routes.etf import router as etf_router
from tdx.routes.financial import router as financial_router
from tdx.routes.market import router as market_router
from tdx.routes.sector import router as sector_router
from tdx.routes.stock import router as stock_router
from tdx.routes.v1 import router as v1_router
from tdx.routes.value import router as value_router
from tdx.routes.ws import router as ws_router

setup_logging()

tdx_adapter: MarketDataAdapter | None = None
tdx_provider: TdxDatasourceProvider | None = None
tdx_bridge: Any | None = None
tdx_collector: Any | None = None
tdx_subscription_client: Any | None = None
ws_manager = ConnectionManager()
_tdx_provider_owned_by_main: TdxDatasourceProvider | None = None
_tdx_adapter_owned_by_main: MarketDataAdapter | None = None
_tdx_bridge_owned_by_main: Any | None = None
_tdx_collector_owned_by_main: Any | None = None
_tdx_subscription_client_owned_by_main: Any | None = None


def _sync_app_state(target_app: FastAPI) -> None:
    target_app.state.tdx_adapter = tdx_adapter
    target_app.state.tdx_provider = tdx_provider
    target_app.state.tdx_bridge = tdx_bridge
    target_app.state.tdx_collector = tdx_collector
    target_app.state.tdx_subscription_client = tdx_subscription_client
    target_app.state.ws_manager = ws_manager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理器.

    启动时创建并初始化 TDX 适配器，关闭时执行清理.
    对应 TDX SDK: tq.initialize(__file__)

    Args:
        app: FastAPI 应用实例

    Yields:
        None
    """
    global _tdx_adapter_owned_by_main, _tdx_bridge_owned_by_main
    global _tdx_collector_owned_by_main, _tdx_provider_owned_by_main
    global _tdx_subscription_client_owned_by_main
    global tdx_adapter, tdx_bridge, tdx_collector, tdx_provider, tdx_subscription_client
    if tdx_adapter is None:
        tdx_adapter = create_tdx_adapter()
        _tdx_adapter_owned_by_main = tdx_adapter
        await tdx_adapter.initialize()
    else:
        _tdx_adapter_owned_by_main = None

    if tdx_provider is None:
        tdx_provider = TdxDatasourceProvider()
        _tdx_provider_owned_by_main = tdx_provider
    else:
        _tdx_provider_owned_by_main = None

    if tdx_bridge is None:
        tdx_bridge = TdxBridge(
            queue_max_size=settings.tdx.ws_queue_max_size,
            max_subscriptions=settings.tdx.max_subscriptions,
        )
        _tdx_bridge_owned_by_main = tdx_bridge
    else:
        _tdx_bridge_owned_by_main = None

    if tdx_collector is None:
        tdx_collector = TdxMinuteCollector(
            provider=tdx_provider,
            bridge=tdx_bridge,
            period=settings.tdx.minute_period,
            snapshot_publisher=_publish_collector_snapshot,
        )
        _tdx_collector_owned_by_main = tdx_collector
    else:
        _tdx_collector_owned_by_main = None

    if tdx_subscription_client is None:
        tdx_subscription_client = TdxSubscriptionClient(
            adapter=tdx_adapter,
            bridge=tdx_bridge,
            collector=tdx_collector,
            max_subscriptions=settings.tdx.max_subscriptions,
        )
        _tdx_subscription_client_owned_by_main = tdx_subscription_client
    else:
        _tdx_subscription_client_owned_by_main = None

    _sync_app_state(_app)

    if hasattr(tdx_collector, "start"):
        await tdx_collector.start()

    try:
        yield
    finally:
        owned_subscription_client = _tdx_subscription_client_owned_by_main
        owned_collector = _tdx_collector_owned_by_main
        owned_bridge = _tdx_bridge_owned_by_main
        owned_provider = _tdx_provider_owned_by_main
        owned_adapter = _tdx_adapter_owned_by_main
        try:
            try:
                try:
                    if tdx_collector and hasattr(tdx_collector, "stop"):
                        await tdx_collector.stop()
                finally:
                    if tdx_subscription_client is owned_subscription_client:
                        tdx_subscription_client = None
                    _tdx_subscription_client_owned_by_main = None
                    if tdx_collector is owned_collector:
                        tdx_collector = None
                    _tdx_collector_owned_by_main = None
                    if tdx_bridge is owned_bridge:
                        tdx_bridge = None
                    _tdx_bridge_owned_by_main = None

                if owned_provider and hasattr(owned_provider, "aclose"):
                    await owned_provider.aclose()
            finally:
                if tdx_provider is owned_provider:
                    tdx_provider = None
                _tdx_provider_owned_by_main = None
        finally:
            try:
                if owned_adapter:
                    await owned_adapter.shutdown()
            finally:
                if tdx_adapter is owned_adapter:
                    tdx_adapter = None
                _tdx_adapter_owned_by_main = None
        _sync_app_state(_app)


app = FastAPI(
    title="Mist DataSource - TDX Adapter",
    description="通达信数据源适配器 - 提供 HTTP/WebSocket 接口",
    version="0.1.0",
    lifespan=lifespan,
)
_sync_app_state(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """健康检查端点.

    Returns:
        包含以下字段的字典:
        - status (str): 服务状态，固定为 "ok"
        - instance (str): 实例标识，固定为 "tdx"
        - adapter (str): 当前适配器类名，未初始化时为 "none"
        - connections (int): 当前 WebSocket 连接数

    Examples:
        >>> GET /health
        {"status": "ok", "instance": "tdx", "adapter": "TDXMockAdapter", "connections": 0}
    """
    provider_health = await _tdx_provider_health()
    bridge_health = _tdx_bridge_health()
    collector_health = _tdx_collector_health()
    return {
        "status": "ok",
        "instance": "tdx",
        "adapter": type(tdx_adapter).__name__ if tdx_adapter else "none",
        "connections": ws_manager.connection_count,
        "tdxHttpReachable": provider_health["tdxHttpReachable"],
        "tdxProviderError": provider_health.get("lastError")
        or provider_health.get("providerHealthError"),
        "tdxProviderErrorType": provider_health.get("providerHealthErrorType"),
        "tqInitialized": tdx_adapter is not None,
        "wsConnected": ws_manager.connection_count > 0,
        "subscribedCount": bridge_health["subscribedCount"],
        "activeSubscriptions": bridge_health["activeSubscriptions"],
        "lastCallbackAt": bridge_health["lastCallbackAt"],
        "quoteCallbackCount": bridge_health["quoteCallbackCount"],
        "quoteCallbackRejectedCount": bridge_health["quoteCallbackRejectedCount"],
        "lastQuoteCallbackAt": bridge_health["lastQuoteCallbackAt"],
        "lastQuoteCallbackCode": bridge_health["lastQuoteCallbackCode"],
        "lastQuoteCallbackSymbol": bridge_health["lastQuoteCallbackSymbol"],
        "lastQuoteCallbackAccepted": bridge_health["lastQuoteCallbackAccepted"],
        "lastQuoteCallbackRejectReason": bridge_health["lastQuoteCallbackRejectReason"],
        "lastMinuteBarAt": _prefer_collector_value(
            collector_health["lastMinuteBarAt"],
            bridge_health["lastMinuteBarAt"],
        ),
        "eventQueueDepth": _prefer_collector_value(
            collector_health["eventQueueDepth"],
            bridge_health["eventQueueDepth"],
        ),
        "eventQueueCapacity": _prefer_collector_value(
            collector_health["eventQueueCapacity"],
            bridge_health["eventQueueCapacity"],
        ),
        "collectorState": collector_health["collectorState"],
    }


async def _tdx_provider_health() -> dict[str, Any]:
    if tdx_provider is None or not hasattr(tdx_provider, "health"):
        return {"tdxHttpReachable": False, "lastError": "TDX provider is not initialized"}

    try:
        health_status = await tdx_provider.health()
        if not isinstance(health_status, Mapping):
            return {
                "tdxHttpReachable": False,
                "lastError": "TDX provider health returned non-mapping status",
            }
        return {
            "tdxHttpReachable": bool(health_status.get("tdxHttpReachable", False)),
            "lastError": health_status.get("lastError"),
        }
    except Exception as exc:
        return {
            "tdxHttpReachable": False,
            "providerHealthError": str(exc),
            "providerHealthErrorType": type(exc).__name__,
        }


def _tdx_bridge_health() -> dict[str, Any]:
    if tdx_bridge is None:
        return {
            "subscribedCount": 0,
            "activeSubscriptions": [],
            "lastCallbackAt": None,
            "lastMinuteBarAt": None,
            "quoteCallbackCount": 0,
            "quoteCallbackRejectedCount": 0,
            "lastQuoteCallbackAt": None,
            "lastQuoteCallbackCode": None,
            "lastQuoteCallbackSymbol": None,
            "lastQuoteCallbackAccepted": None,
            "lastQuoteCallbackRejectReason": None,
            "eventQueueDepth": 0,
            "eventQueueCapacity": 0,
        }

    if hasattr(tdx_bridge, "health"):
        health_status = tdx_bridge.health()
        if isinstance(health_status, Mapping):
            return {
                "subscribedCount": _read_mapping_int(health_status, "subscribed_count", 0),
                "activeSubscriptions": _read_mapping_list(
                    health_status,
                    "active_subscriptions",
                ),
                "lastCallbackAt": health_status.get("last_callback_at"),
                "lastMinuteBarAt": health_status.get("last_minute_bar_at"),
                "quoteCallbackCount": _read_mapping_int(
                    health_status,
                    "quote_callback_count",
                    0,
                ),
                "quoteCallbackRejectedCount": _read_mapping_int(
                    health_status,
                    "quote_callback_rejected_count",
                    0,
                ),
                "lastQuoteCallbackAt": health_status.get("last_quote_callback_at"),
                "lastQuoteCallbackCode": health_status.get("last_quote_callback_code"),
                "lastQuoteCallbackSymbol": health_status.get("last_quote_callback_symbol"),
                "lastQuoteCallbackAccepted": health_status.get("last_quote_callback_accepted"),
                "lastQuoteCallbackRejectReason": health_status.get(
                    "last_quote_callback_reject_reason"
                ),
                "eventQueueDepth": _read_mapping_int(health_status, "event_queue_depth", 0),
                "eventQueueCapacity": _read_mapping_int(health_status, "event_queue_capacity", 0),
            }

    return {
        "subscribedCount": _read_int(tdx_bridge, "subscribed_count", 0),
        "activeSubscriptions": _read_list(tdx_bridge, "active_subscriptions"),
        "lastCallbackAt": _read_attr(tdx_bridge, "last_callback_at", None),
        "lastMinuteBarAt": _read_attr(tdx_bridge, "last_minute_bar_at", None),
        "quoteCallbackCount": _read_int(tdx_bridge, "quote_callback_count", 0),
        "quoteCallbackRejectedCount": _read_int(
            tdx_bridge,
            "quote_callback_rejected_count",
            0,
        ),
        "lastQuoteCallbackAt": _read_attr(tdx_bridge, "last_quote_callback_at", None),
        "lastQuoteCallbackCode": _read_attr(tdx_bridge, "last_quote_callback_code", None),
        "lastQuoteCallbackSymbol": _read_attr(
            tdx_bridge,
            "last_quote_callback_symbol",
            None,
        ),
        "lastQuoteCallbackAccepted": _read_attr(
            tdx_bridge,
            "last_quote_callback_accepted",
            None,
        ),
        "lastQuoteCallbackRejectReason": _read_attr(
            tdx_bridge,
            "last_quote_callback_reject_reason",
            None,
        ),
        "eventQueueDepth": _read_int(tdx_bridge, "event_queue_depth", 0),
        "eventQueueCapacity": _read_int(tdx_bridge, "event_queue_capacity", 0),
    }


def _tdx_collector_health() -> dict[str, Any]:
    if tdx_collector is None:
        return {
            "lastMinuteBarAt": None,
            "eventQueueDepth": 0,
            "eventQueueCapacity": 0,
            "collectorState": "not_started",
        }

    return {
        "lastMinuteBarAt": _read_attr(tdx_collector, "last_minute_bar_at", None),
        "eventQueueDepth": _read_int(tdx_collector, "event_queue_depth", 0),
        "eventQueueCapacity": _read_int(tdx_collector, "event_queue_capacity", 0),
        "collectorState": _read_attr(tdx_collector, "state", "not_started"),
    }


def _prefer_collector_value(collector_value: Any, bridge_value: Any) -> Any:
    return bridge_value if tdx_collector is None else collector_value


def _read_attr(source: Any | None, name: str, default: Any) -> Any:
    if source is None:
        return default
    return getattr(source, name, default)


def _read_int(source: Any | None, name: str, default: int) -> int:
    value = _read_attr(source, name, default)
    return value if isinstance(value, int) else default


def _read_list(source: Any | None, name: str) -> list[Any]:
    value = _read_attr(source, name, [])
    return list(value) if isinstance(value, list | tuple) else []


def _read_mapping_int(source: Mapping[str, Any], name: str, default: int) -> int:
    value = source.get(name, default)
    return value if isinstance(value, int) else default


def _read_mapping_list(source: Mapping[str, Any], name: str) -> list[Any]:
    value = source.get(name, [])
    return list(value) if isinstance(value, list | tuple) else []


async def _publish_collector_snapshot(snapshot: TdxSnapshot) -> None:
    await ws_manager.broadcast(ws_quote(provider="tdx", data=_serialize_snapshot_quote(snapshot)))


def _serialize_snapshot_quote(snapshot: TdxSnapshot) -> dict[str, Any]:
    return {
        "stock_code": snapshot.symbol,
        "snapshot": {
            "Code": snapshot.symbol,
            "Now": snapshot.last,
            "Open": snapshot.open,
            "High": snapshot.high,
            "Low": snapshot.low,
            "LastClose": snapshot.lastClose,
            "Volume": snapshot.volume,
            "Amount": snapshot.amount,
            "Provider": snapshot.provider,
            "AsOf": snapshot.asOf,
        },
    }


app.include_router(v1_router, tags=["V1"])
app.include_router(market_router, prefix="/api/tdx", tags=["Market"])
app.include_router(stock_router, prefix="/api/tdx", tags=["Stock"])
app.include_router(financial_router, prefix="/api/tdx", tags=["Financial"])
app.include_router(value_router, prefix="/api/tdx", tags=["Value"])
app.include_router(sector_router, prefix="/api/tdx", tags=["Sector"])
app.include_router(etf_router, prefix="/api/tdx", tags=["ETF"])
app.include_router(client_router, prefix="/api/tdx", tags=["Client"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])
