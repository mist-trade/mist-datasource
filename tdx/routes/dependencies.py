from typing import Any

from fastapi import Request, WebSocket

from src.core.config import settings
from src.datasource.tdx_bridge import TdxBridge


def get_tdx_adapter(request: Request) -> Any:
    return getattr(request.app.state, "tdx_adapter", None)


def get_tdx_provider(request: Request) -> Any:
    return getattr(request.app.state, "tdx_provider", None)


def get_ws_manager(websocket: WebSocket) -> Any:
    return getattr(websocket.app.state, "ws_manager", None)


def get_tdx_subscription_client(websocket: WebSocket) -> Any:
    return getattr(websocket.app.state, "tdx_subscription_client", None)


def get_tdx_bridge(websocket: WebSocket) -> TdxBridge:
    bridge = getattr(websocket.app.state, "tdx_bridge", None)
    if bridge is None:
        bridge = TdxBridge(
            queue_max_size=settings.tdx.ws_queue_max_size,
            max_subscriptions=settings.tdx.max_subscriptions,
        )
        websocket.app.state.tdx_bridge = bridge
    return bridge
