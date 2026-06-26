"""Minute-bar collector driven by TDX subscription callbacks."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from src.core.config import settings
from src.datasource.tdx_bridge import TdxBridge
from src.datasource.tdx_models import TdxBar
from src.datasource.tdx_normalization import normalize_symbol

BarKey = tuple[str, str, str, str]


class TdxMinuteCollector:
    """Collect recent minute bars for symbols marked dirty by quote callbacks."""

    def __init__(
        self,
        *,
        provider: Any,
        bridge: TdxBridge,
        period: str,
        collect_delay_seconds: float | None = None,
        retry_delay_seconds: float | None = None,
        bar_publisher: Callable[[TdxBar], Awaitable[None]] | None = None,
    ) -> None:
        self.provider = provider
        self.bridge = bridge
        self.period = period
        self.collect_delay_seconds = (
            float(settings.tdx.collect_delay_seconds)
            if collect_delay_seconds is None
            else collect_delay_seconds
        )
        self.retry_delay_seconds = (
            float(settings.tdx.retry_delay_seconds)
            if retry_delay_seconds is None
            else retry_delay_seconds
        )
        self.dirty_symbols: set[str] = set()
        self.emitted_bar_keys: set[BarKey] = set()
        self.stale_symbols: set[str] = set()
        self.last_error_code: str | None = None
        self.last_error: str | None = None
        self.state = "not_started"
        self.bar_publisher = bar_publisher
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def last_minute_bar_at(self) -> str | None:
        return self.bridge.last_minute_bar_at

    @property
    def event_queue_depth(self) -> int:
        return self.bridge.event_queue_depth

    @property
    def event_queue_capacity(self) -> int:
        return self.bridge.event_queue_capacity

    def mark_dirty(self, symbol: str) -> None:
        self.dirty_symbols.add(normalize_symbol(symbol))

    def mark_dirty_from_callback(self, payload: dict[str, Any]) -> None:
        code = payload.get("Code")
        if isinstance(code, str) and code:
            self.mark_dirty(code)

    async def collect_dirty_once(self) -> int:
        symbols = sorted(self.dirty_symbols)
        if not symbols:
            return 0
        symbols = self._filter_active_dirty_symbols(symbols)
        if not symbols:
            return 0

        self.dirty_symbols.difference_update(symbols)
        try:
            raw_bars = await self.provider.collect_recent_bars(symbols, self.period, 3)
        except Exception as exc:
            self.dirty_symbols.update(symbols)
            self.stale_symbols.update(symbols)
            self.state = "error"
            self.last_error_code = "TDX_COLLECTOR_PROVIDER_ERROR"
            self.last_error = str(exc)
            self.bridge.last_error_code = self.last_error_code
            return 0

        bars = [_coerce_bar(raw_bar) for raw_bar in raw_bars]
        emitted = 0
        fresh_symbols: set[str] = set()
        symbols_with_bars = {bar.symbol for bar in bars}
        publish_errors: list[str] = []
        for bar in bars:
            key = _bar_key(bar)
            if key in self.emitted_bar_keys:
                continue
            if not self.bridge.enqueue_bar(bar):
                continue
            self.emitted_bar_keys.add(key)
            fresh_symbols.add(bar.symbol)
            emitted += 1
            if self.bar_publisher is not None:
                try:
                    await self.bar_publisher(bar)
                except Exception as exc:
                    publish_errors.append(str(exc))

        stale_symbols = set(symbols) - symbols_with_bars
        self.stale_symbols.difference_update(fresh_symbols)
        if publish_errors:
            self.state = "error"
            self.last_error_code = "TDX_COLLECTOR_PUBLISH_ERROR"
            self.last_error = "; ".join(publish_errors)
            self.bridge.last_error_code = self.last_error_code
        elif stale_symbols:
            self.stale_symbols.update(stale_symbols)
            self.state = "stale"
            self.last_error_code = "TDX_COLLECTOR_STALE"
            self.last_error = "No fresh minute bars returned for dirty symbols"
            self.bridge.last_error_code = self.last_error_code
        else:
            if emitted > 0 or self.last_error_code != "TDX_COLLECTOR_PUBLISH_ERROR":
                self.state = "running" if self._task and not self._task.done() else "idle"
                self.last_error_code = None
                self.last_error = None

        return emitted

    def _filter_active_dirty_symbols(self, symbols: list[str]) -> list[str]:
        if not getattr(self.bridge, "subscription_state_known", False):
            return symbols

        active = set(self.bridge.active_subscriptions)
        active_symbols = [symbol for symbol in symbols if symbol in active]
        inactive_symbols = set(symbols) - set(active_symbols)
        self.dirty_symbols.difference_update(inactive_symbols)
        return active_symbols

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stopping.set()
        task = self._task
        if task is None:
            self.state = "stopped"
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None
        self.state = "stopped"

    async def _run_loop(self) -> None:
        try:
            while not self._stopping.is_set():
                await self.collect_dirty_once()
                delay = (
                    self.retry_delay_seconds
                    if self.state == "error"
                    else self.collect_delay_seconds
                )
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise


def _coerce_bar(raw_bar: TdxBar | dict[str, Any]) -> TdxBar:
    bar = raw_bar if isinstance(raw_bar, TdxBar) else TdxBar.model_validate(raw_bar)
    normalized_symbol = normalize_symbol(bar.symbol)
    if normalized_symbol == bar.symbol:
        return bar
    return bar.model_copy(update={"symbol": normalized_symbol})


def _bar_key(bar: TdxBar) -> BarKey:
    return (bar.symbol, bar.period, bar.barTime, bar.provider)


def dirty_symbols_from_payloads(payloads: Iterable[dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for payload in payloads:
        code = payload.get("Code")
        if isinstance(code, str) and code:
            symbols.add(normalize_symbol(code))
    return symbols
