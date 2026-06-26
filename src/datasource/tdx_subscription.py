"""Thin subscription wrapper around an initialized TDX adapter."""

import asyncio
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

from src.core.config import settings
from src.datasource.tdx_bridge import TdxBridge
from src.datasource.tdx_normalization import normalize_symbol

TDX_SUBSCRIBE_LIMIT_EXCEEDED = "TDX_SUBSCRIBE_LIMIT_EXCEEDED"


class TdxSubscriptionClient:
    """Coordinate TDX SDK subscriptions without owning SDK initialization."""

    def __init__(
        self,
        *,
        adapter: Any,
        bridge: TdxBridge,
        collector: Any,
        max_subscriptions: int | None = None,
    ) -> None:
        self.adapter = adapter
        self.bridge = bridge
        self.collector = collector
        self.max_subscriptions = (
            settings.tdx.max_subscriptions if max_subscriptions is None else max_subscriptions
        )
        self._lock = asyncio.Lock()

    async def subscribe(self, symbols: Iterable[str]) -> dict[str, Any]:
        requested = _dedupe_normalized(symbols)
        async with self._lock:
            desired = _dedupe_normalized([*self.bridge.active_subscriptions, *requested])
            if len(desired) > self.max_subscriptions:
                self.bridge.last_error_code = TDX_SUBSCRIBE_LIMIT_EXCEEDED
                return {
                    "accepted": [],
                    "rejected": requested,
                    "active": list(self.bridge.active_subscriptions),
                    "error": _limit_error(self.max_subscriptions),
                }

            to_subscribe = [
                symbol
                for symbol in requested
                if symbol not in set(self.bridge.active_subscriptions)
            ]
            previous_active = list(self.bridge.active_subscriptions)
            try:
                if to_subscribe:
                    await self.adapter.subscribe_hq(to_subscribe, self._on_quote_update)
                self.bridge.mark_active(desired)
            except Exception:
                self.bridge.mark_active(previous_active)
                if to_subscribe:
                    with suppress(Exception):
                        await self.adapter.unsubscribe_hq(to_subscribe)
                if previous_active:
                    with suppress(Exception):
                        await self.adapter.subscribe_hq(previous_active, self._on_quote_update)
                raise

            return {
                "accepted": requested,
                "rejected": [],
                "active": list(self.bridge.active_subscriptions),
                "error": None,
            }

    async def sync(self, symbols: Iterable[str]) -> dict[str, Any]:
        desired = _dedupe_normalized(symbols)
        async with self._lock:
            if len(desired) > self.max_subscriptions:
                self.bridge.last_error_code = TDX_SUBSCRIBE_LIMIT_EXCEEDED
                return {
                    "accepted": [],
                    "rejected": desired,
                    "active": list(self.bridge.active_subscriptions),
                    "error": _limit_error(self.max_subscriptions),
                }

            active = set(self.bridge.active_subscriptions)
            desired_set = set(desired)
            to_subscribe = [symbol for symbol in desired if symbol not in active]
            to_unsubscribe = [
                symbol for symbol in self.bridge.active_subscriptions if symbol not in desired_set
            ]
            previous_active = list(self.bridge.active_subscriptions)
            try:
                if to_unsubscribe:
                    await self.adapter.unsubscribe_hq(to_unsubscribe)
                if to_subscribe:
                    await self.adapter.subscribe_hq(to_subscribe, self._on_quote_update)
                self.bridge.mark_active(desired)
            except Exception:
                self.bridge.mark_active(previous_active)
                if to_subscribe:
                    with suppress(Exception):
                        await self.adapter.unsubscribe_hq(to_subscribe)
                if previous_active:
                    with suppress(Exception):
                        await self.adapter.subscribe_hq(
                            previous_active,
                            self._on_quote_update,
                        )
                raise

            return {
                "accepted": desired,
                "rejected": [],
                "active": list(self.bridge.active_subscriptions),
                "error": None,
            }

    async def unsubscribe(self, symbols: Iterable[str] | None = None) -> dict[str, Any]:
        async with self._lock:
            if symbols is None:
                to_unsubscribe = list(self.bridge.active_subscriptions)
                desired: list[str] = []
            else:
                requested = set(_dedupe_normalized(symbols))
                to_unsubscribe = [
                    symbol for symbol in self.bridge.active_subscriptions if symbol in requested
                ]
                desired = [
                    symbol for symbol in self.bridge.active_subscriptions if symbol not in requested
                ]
            previous_active = list(self.bridge.active_subscriptions)

            try:
                if to_unsubscribe:
                    await self.adapter.unsubscribe_hq(to_unsubscribe)
                self.bridge.mark_active(desired)
            except Exception:
                self.bridge.mark_active(previous_active)
                if previous_active:
                    with suppress(Exception):
                        await self.adapter.subscribe_hq(previous_active, self._on_quote_update)
                raise

            return {
                "accepted": to_unsubscribe,
                "rejected": [],
                "active": list(self.bridge.active_subscriptions),
                "error": None,
            }

    def _on_quote_update(self, payload: dict[str, Any]) -> None:
        code = payload.get("Code")
        if not isinstance(code, str) or not code:
            return
        if normalize_symbol(code) not in set(self.bridge.active_subscriptions):
            return
        if self.collector is not None:
            self.collector.mark_dirty_from_callback(payload)


def _dedupe_normalized(symbols: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _limit_error(max_subscriptions: int) -> dict[str, Any]:
    return {
        "code": TDX_SUBSCRIBE_LIMIT_EXCEEDED,
        "message": f"Cannot subscribe to more than {max_subscriptions} symbols",
        "retryable": False,
        "details": {"maxSubscriptions": max_subscriptions},
    }
