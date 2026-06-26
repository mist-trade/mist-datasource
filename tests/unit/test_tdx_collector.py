import asyncio
import inspect
from typing import Any

import pytest

from src.adapter.mock.tdx_mock import TDXMockAdapter
from src.datasource.tdx_bridge import TdxBridge
from src.datasource.tdx_collector import TdxMinuteCollector
from src.datasource.tdx_models import TdxBar
from src.datasource.tdx_subscription import TdxSubscriptionClient
from tdx.main import app


class FakeProvider:
    async def collect_recent_bars(self, symbols, period, count):
        _ = count
        return [
            {
                "symbol": symbol,
                "period": period,
                "barTime": "2026-06-26T09:31:00+08:00",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12345.6,
                "provider": "tdx",
                "receivedAt": "2026-06-26T09:31:02+08:00",
            }
            for symbol in symbols
        ]


class MixedProvider:
    async def collect_recent_bars(self, symbols, period, count):
        _ = count
        return [
            TdxBar(
                symbol=symbols[0],
                period=period,
                barTime="2026-06-26T09:31:00+08:00",
                open=10.1,
                high=10.3,
                low=10.0,
                close=10.2,
                volume=1200,
                amount=12345.6,
                provider="tdx",
                receivedAt="2026-06-26T09:31:02+08:00",
            ),
            {
                "symbol": symbols[0],
                "period": period,
                "barTime": "2026-06-26T09:32:00+08:00",
                "open": 10.2,
                "high": 10.5,
                "low": 10.1,
                "close": 10.4,
                "volume": 1300,
                "amount": 13345.6,
                "provider": "tdx",
                "receivedAt": "2026-06-26T09:32:02+08:00",
            },
        ]


class MultiSymbolProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, int]] = []

    async def collect_recent_bars(self, symbols, period, count):
        self.calls.append((list(symbols), period, count))
        return [
            {
                "symbol": symbol,
                "period": period,
                "barTime": f"2026-06-26T09:3{index}:00+08:00",
                "open": 10.1 + index,
                "high": 10.3 + index,
                "low": 10.0 + index,
                "close": 10.2 + index,
                "volume": 1200 + index,
                "amount": 12345.6 + index,
                "provider": "tdx",
                "receivedAt": f"2026-06-26T09:3{index}:02+08:00",
            }
            for index, symbol in enumerate(symbols, start=1)
        ]


class CountingProvider(FakeProvider):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, int]] = []

    async def collect_recent_bars(self, symbols, period, count):
        self.calls.append((list(symbols), period, count))
        return await super().collect_recent_bars(symbols, period, count)


class DuplicateProvider:
    async def collect_recent_bars(self, symbols, period, count):
        _ = (symbols, period, count)
        return [
            {
                "symbol": "600519.SH",
                "period": "1m",
                "barTime": "2026-06-26T09:31:00+08:00",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12345.6,
                "provider": "tdx",
                "receivedAt": "2026-06-26T09:31:02+08:00",
            },
            {
                "symbol": "600519.SH",
                "period": "1m",
                "barTime": "2026-06-26T09:31:00+08:00",
                "open": 10.9,
                "high": 11.3,
                "low": 10.0,
                "close": 11.2,
                "volume": 9999,
                "amount": 99999.9,
                "provider": "tdx",
                "receivedAt": "2026-06-26T09:31:05+08:00",
            },
            {
                "symbol": "600519.SH",
                "period": "1m",
                "barTime": "2026-06-26T09:31:00+08:00",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 1200,
                "amount": 12345.6,
                "provider": "alternate",
                "receivedAt": "2026-06-26T09:31:02+08:00",
            },
        ]


class EmptyProvider:
    async def collect_recent_bars(self, symbols, period, count):
        _ = (symbols, period, count)
        return []


class RaisingProvider:
    async def collect_recent_bars(self, symbols, period, count):
        _ = (symbols, period, count)
        raise RuntimeError("tdx http failed")


class CallbackCollector:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def mark_dirty_from_callback(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class CallbackAdapter:
    def __init__(self) -> None:
        self.callback: Any | None = None
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.snapshot_calls: list[str] = []

    async def subscribe_hq(self, stock_list: list[str], callback: Any = None) -> None:
        self.subscribed.extend(stock_list)
        self.callback = callback

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> None:
        if stock_list is None:
            self.unsubscribed.extend(self.subscribed)
            self.subscribed.clear()
            return
        self.unsubscribed.extend(stock_list)
        requested = set(stock_list)
        self.subscribed = [symbol for symbol in self.subscribed if symbol not in requested]

    async def get_market_snapshot(
        self,
        stock_code: str,
        field_list: list[str] | None = None,
    ) -> dict[str, Any]:
        _ = field_list
        self.snapshot_calls.append(stock_code)
        return {"Code": stock_code}


class CapacityEnforcingAdapter:
    def __init__(self, *, max_active: int, active: list[str]) -> None:
        self.max_active = max_active
        self.active = list(active)
        self.operations: list[tuple[str, list[str]]] = []
        self.fail_on_subscribe_symbols: set[str] = set()
        self.callback: Any | None = None

    async def subscribe_hq(self, stock_list: list[str], callback: Any = None) -> None:
        if self.fail_on_subscribe_symbols.intersection(stock_list):
            raise RuntimeError("subscribe failed")
        if len(self.active) + len(stock_list) > self.max_active:
            raise RuntimeError("subscription cap exceeded")
        self.operations.append(("subscribe", stock_list))
        self.active.extend(stock_list)
        self.callback = callback

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> None:
        if stock_list is None:
            stock_list = list(self.active)
        self.operations.append(("unsubscribe", stock_list))
        self.active = [symbol for symbol in self.active if symbol not in set(stock_list)]


class BlockingSubscribeAdapter:
    def __init__(self) -> None:
        self.subscribe_started = asyncio.Event()
        self.release_first_subscribe = asyncio.Event()
        self.subscribe_calls: list[list[str]] = []

    async def subscribe_hq(self, stock_list: list[str], callback: Any = None) -> None:
        _ = callback
        self.subscribe_calls.append(stock_list)
        if len(self.subscribe_calls) == 1:
            self.subscribe_started.set()
            await self.release_first_subscribe.wait()

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> None:
        _ = stock_list


class PartialUnsubscribeAdapter:
    def __init__(self) -> None:
        self.active = ["600519.SH", "000001.SZ"]
        self.subscribe_calls: list[list[str]] = []

    async def subscribe_hq(self, stock_list: list[str], callback: Any = None) -> None:
        _ = callback
        self.subscribe_calls.append(stock_list)
        self.active.extend(stock for stock in stock_list if stock not in self.active)

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> None:
        requested = set(stock_list or self.active)
        self.active = [stock for stock in self.active if stock not in requested]
        raise RuntimeError("unsubscribe failed")


class RollbackFailingAdapter:
    def __init__(self) -> None:
        self.active = ["600519.SH"]

    async def subscribe_hq(self, stock_list: list[str], callback: Any = None) -> None:
        _ = callback
        if stock_list == ["000001.SZ"]:
            raise RuntimeError("subscribe failed")
        raise RuntimeError("rollback failed")

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> None:
        requested = set(stock_list or self.active)
        self.active = [stock for stock in self.active if stock not in requested]


class FakeAdapter:
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_callback_only_marks_dirty_symbol():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=FakeProvider(), bridge=bridge, period="1m")

    collector.mark_dirty_from_callback({"Code": "SH600519", "ErrorId": "0"})

    assert collector.dirty_symbols == {"600519.SH"}


@pytest.mark.asyncio
async def test_collector_emits_bar_once_per_key():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=FakeProvider(), bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()
    emitted_again = await collector.collect_dirty_once()

    assert emitted == 1
    assert emitted_again == 0
    assert bridge.event_queue_depth == 1


@pytest.mark.asyncio
async def test_collector_publishes_new_normalized_bars():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    published: list[TdxBar] = []

    async def publish_bar(bar: TdxBar) -> None:
        published.append(bar)

    collector = TdxMinuteCollector(
        provider=FakeProvider(),
        bridge=bridge,
        period="1m",
        bar_publisher=publish_bar,
    )
    collector.mark_dirty("SH600519")

    emitted = await collector.collect_dirty_once()

    assert emitted == 1
    assert published[0].model_dump(by_alias=True) == {
        "symbol": "600519.SH",
        "period": "1m",
        "barTime": "2026-06-26T09:31:00+08:00",
        "open": 10.1,
        "high": 10.3,
        "low": 10.0,
        "close": 10.2,
        "volume": 1200.0,
        "amount": 12345.6,
        "provider": "tdx",
        "receivedAt": "2026-06-26T09:31:02+08:00",
    }


@pytest.mark.asyncio
async def test_collector_publishes_all_unique_bars_when_bridge_buffer_rolls_over():
    bridge = TdxBridge(queue_max_size=1, max_subscriptions=100)
    provider = MultiSymbolProvider()
    published: list[TdxBar] = []

    async def publish_bar(bar: TdxBar) -> None:
        published.append(bar)

    collector = TdxMinuteCollector(
        provider=provider,
        bridge=bridge,
        period="1m",
        bar_publisher=publish_bar,
    )
    collector.mark_dirty("600519.SH")
    collector.mark_dirty("000001.SZ")

    emitted = await collector.collect_dirty_once()

    assert emitted == 2
    assert [bar.symbol for bar in published] == ["000001.SZ", "600519.SH"]
    assert bridge.event_queue_depth == 1
    assert bridge.last_error_code == "DATASOURCE_WS_BACKPRESSURE"


@pytest.mark.asyncio
async def test_collector_discards_dirty_symbols_when_active_subscriptions_are_known_empty():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    bridge.mark_active([])
    provider = CountingProvider()
    published: list[TdxBar] = []

    async def publish_bar(bar: TdxBar) -> None:
        published.append(bar)

    collector = TdxMinuteCollector(
        provider=provider,
        bridge=bridge,
        period="1m",
        bar_publisher=publish_bar,
    )
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 0
    assert provider.calls == []
    assert published == []
    assert collector.dirty_symbols == set()


@pytest.mark.asyncio
async def test_collector_keeps_unknown_subscription_state_conservative():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    provider = CountingProvider()
    collector = TdxMinuteCollector(provider=provider, bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 1
    assert provider.calls == [(["600519.SH"], "1m", 3)]


@pytest.mark.asyncio
async def test_collector_records_publish_error_without_reemitting_duplicate():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    publish_calls: list[str] = []

    async def failing_publish_bar(bar: TdxBar) -> None:
        publish_calls.append(bar.symbol)
        raise RuntimeError("publish failed")

    collector = TdxMinuteCollector(
        provider=FakeProvider(),
        bridge=bridge,
        period="1m",
        bar_publisher=failing_publish_bar,
    )
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()
    collector.mark_dirty("600519.SH")
    emitted_again = await collector.collect_dirty_once()

    assert emitted == 1
    assert emitted_again == 0
    assert publish_calls == ["600519.SH"]
    assert collector.emitted_bar_keys == {
        ("600519.SH", "1m", "2026-06-26T09:31:00+08:00", "tdx")
    }
    assert collector.state == "error"
    assert collector.last_error_code == "TDX_COLLECTOR_PUBLISH_ERROR"


@pytest.mark.asyncio
async def test_subscription_client_enforces_max_subscriptions_with_stable_error():
    adapter = CallbackAdapter()
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=2)
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=2,
    )

    result = await client.subscribe(["SH600519", "SZ000001", "SH601318"])

    assert result == {
        "accepted": [],
        "rejected": ["600519.SH", "000001.SZ", "601318.SH"],
        "active": [],
        "error": {
            "code": "TDX_SUBSCRIBE_LIMIT_EXCEEDED",
            "message": "Cannot subscribe to more than 2 symbols",
            "retryable": False,
            "details": {"maxSubscriptions": 2},
        },
    }
    assert adapter.subscribed == []


def test_subscription_client_preserves_zero_max_subscription_override():
    client = TdxSubscriptionClient(
        adapter=CallbackAdapter(),
        bridge=TdxBridge(queue_max_size=10, max_subscriptions=100),
        collector=CallbackCollector(),
        max_subscriptions=0,
    )

    assert client.max_subscriptions == 0


@pytest.mark.asyncio
async def test_subscription_callback_marks_dirty_without_collecting_bars():
    adapter = CallbackAdapter()
    collector = CallbackCollector()
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=collector,
        max_subscriptions=100,
    )

    await client.subscribe(["600519.SH"])
    assert adapter.callback is not None
    adapter.callback({"Code": "SH600519", "ErrorId": "0"})

    assert collector.payloads == [{"Code": "SH600519", "ErrorId": "0"}]
    assert adapter.snapshot_calls == []


def test_subscription_client_has_no_synchronous_compatibility_callback_hook():
    signature = inspect.signature(TdxSubscriptionClient)

    assert "compatibility_callback" not in signature.parameters


@pytest.mark.asyncio
async def test_subscription_client_replaces_symbols_without_exceeding_adapter_capacity():
    adapter = CapacityEnforcingAdapter(
        max_active=2,
        active=["600519.SH", "000001.SZ"],
    )
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=2)
    bridge.mark_active(["600519.SH", "000001.SZ"])
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=2,
    )

    result = await client.sync(["601318.SH", "000858.SZ"])

    assert result["error"] is None
    assert adapter.operations[0][0] == "unsubscribe"
    assert adapter.operations[1] == ("subscribe", ["601318.SH", "000858.SZ"])
    assert adapter.active == ["601318.SH", "000858.SZ"]
    assert bridge.active_subscriptions == ["601318.SH", "000858.SZ"]


@pytest.mark.asyncio
async def test_subscription_client_limit_check_uses_active_state_after_waiting_for_lock():
    adapter = BlockingSubscribeAdapter()
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=1)
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=1,
    )

    first = asyncio.create_task(client.subscribe(["600519.SH"]))
    await adapter.subscribe_started.wait()
    second = asyncio.create_task(client.subscribe(["000001.SZ"]))

    adapter.release_first_subscribe.set()
    first_result = await first
    second_result = await second

    assert first_result["accepted"] == ["600519.SH"]
    assert second_result["error"]["code"] == "TDX_SUBSCRIBE_LIMIT_EXCEEDED"
    assert adapter.subscribe_calls == [["600519.SH"]]
    assert bridge.active_subscriptions == ["600519.SH"]


@pytest.mark.asyncio
async def test_subscription_client_rolls_back_active_state_when_sync_subscribe_fails():
    adapter = CapacityEnforcingAdapter(
        max_active=2,
        active=["600519.SH"],
    )
    adapter.fail_on_subscribe_symbols = {"000001.SZ"}
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=2)
    bridge.mark_active(["600519.SH"])
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=2,
    )

    with pytest.raises(RuntimeError, match="subscribe failed"):
        await client.sync(["000001.SZ"])

    assert adapter.active == ["600519.SH"]
    assert bridge.active_subscriptions == ["600519.SH"]


@pytest.mark.asyncio
async def test_subscription_client_restores_bridge_and_adapter_after_partial_unsubscribe_failure():
    adapter = PartialUnsubscribeAdapter()
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=2)
    bridge.mark_active(["600519.SH", "000001.SZ"])
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=2,
    )

    with pytest.raises(RuntimeError, match="unsubscribe failed"):
        await client.sync(["601318.SH"])

    assert bridge.active_subscriptions == ["600519.SH", "000001.SZ"]
    assert adapter.active == ["600519.SH", "000001.SZ"]


@pytest.mark.asyncio
async def test_subscription_client_rollback_failure_does_not_mask_original_exception():
    adapter = RollbackFailingAdapter()
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=2)
    bridge.mark_active(["600519.SH"])
    client = TdxSubscriptionClient(
        adapter=adapter,
        bridge=bridge,
        collector=CallbackCollector(),
        max_subscriptions=2,
    )

    with pytest.raises(RuntimeError, match="subscribe failed"):
        await client.sync(["000001.SZ"])

    assert bridge.active_subscriptions == ["600519.SH"]


@pytest.mark.asyncio
async def test_collector_suppresses_duplicates_by_symbol_period_bartime_provider():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=DuplicateProvider(), bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 2
    assert collector.emitted_bar_keys == {
        ("600519.SH", "1m", "2026-06-26T09:31:00+08:00", "tdx"),
        ("600519.SH", "1m", "2026-06-26T09:31:00+08:00", "alternate"),
    }


@pytest.mark.asyncio
async def test_collector_accepts_dicts_and_tdx_bar_models():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=MixedProvider(), bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 2
    assert bridge.event_queue_depth == 2


@pytest.mark.asyncio
async def test_collector_records_stale_state_when_no_bars_are_returned():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=EmptyProvider(), bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 0
    assert collector.state == "stale"
    assert collector.last_error_code == "TDX_COLLECTOR_STALE"
    assert collector.stale_symbols == {"600519.SH"}


@pytest.mark.asyncio
async def test_collector_records_error_state_when_provider_raises():
    bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)
    collector = TdxMinuteCollector(provider=RaisingProvider(), bridge=bridge, period="1m")
    collector.mark_dirty("600519.SH")

    emitted = await collector.collect_dirty_once()

    assert emitted == 0
    assert collector.state == "error"
    assert collector.last_error_code == "TDX_COLLECTOR_PROVIDER_ERROR"
    assert collector.stale_symbols == {"600519.SH"}


@pytest.mark.asyncio
async def test_mock_adapter_emit_hq_update_triggers_stored_callback():
    adapter = TDXMockAdapter()
    payloads: list[dict[str, str]] = []

    await adapter.subscribe_hq(["600519.SH"], payloads.append)
    await adapter.emit_hq_update("SH600519")

    assert payloads == [{"Code": "SH600519", "ErrorId": "0"}]


@pytest.mark.asyncio
async def test_lifespan_creates_runtime_without_overwriting_injected_fakes(monkeypatch):
    import tdx.main

    previous_adapter = tdx.main.tdx_adapter
    previous_provider = tdx.main.tdx_provider
    previous_bridge = tdx.main.tdx_bridge
    previous_collector = tdx.main.tdx_collector
    previous_subscription_client = getattr(tdx.main, "tdx_subscription_client", None)
    previous_owned_provider = tdx.main._tdx_provider_owned_by_main
    previous_owned_bridge = getattr(tdx.main, "_tdx_bridge_owned_by_main", None)
    previous_owned_collector = getattr(tdx.main, "_tdx_collector_owned_by_main", None)
    previous_owned_subscription_client = getattr(
        tdx.main,
        "_tdx_subscription_client_owned_by_main",
        None,
    )

    fake_adapter = FakeAdapter()
    fake_provider = FakeProvider()
    fake_bridge = TdxBridge(queue_max_size=10, max_subscriptions=100)

    async def injected_bar_publisher(bar: TdxBar) -> None:
        _ = bar

    fake_collector = TdxMinuteCollector(
        provider=fake_provider,
        bridge=fake_bridge,
        period="1m",
        collect_delay_seconds=999,
        bar_publisher=injected_bar_publisher,
    )
    monkeypatch.setattr(tdx.main, "create_tdx_adapter", lambda: fake_adapter)
    tdx.main.tdx_adapter = None
    tdx.main.tdx_provider = fake_provider
    tdx.main.tdx_bridge = fake_bridge
    tdx.main.tdx_collector = fake_collector
    tdx.main.tdx_subscription_client = None

    try:
        async with tdx.main.lifespan(app):
            assert tdx.main.tdx_adapter is fake_adapter
            assert tdx.main.tdx_provider is fake_provider
            assert tdx.main.tdx_bridge is fake_bridge
            assert tdx.main.tdx_collector is fake_collector
            assert fake_collector.bar_publisher is injected_bar_publisher
            assert tdx.main.tdx_subscription_client is not None
            assert fake_collector._task is not None
            assert not fake_collector._task.done()

        assert fake_adapter.shutdown_called is True
        assert fake_collector.state == "stopped"
        assert tdx.main.tdx_adapter is None
        assert tdx.main.tdx_provider is fake_provider
        assert tdx.main.tdx_bridge is fake_bridge
        assert tdx.main.tdx_collector is fake_collector
        assert fake_collector.bar_publisher is injected_bar_publisher
        assert tdx.main.tdx_subscription_client is None
    finally:
        tdx.main.tdx_adapter = previous_adapter
        tdx.main.tdx_provider = previous_provider
        tdx.main.tdx_bridge = previous_bridge
        tdx.main.tdx_collector = previous_collector
        tdx.main.tdx_subscription_client = previous_subscription_client
        tdx.main._tdx_provider_owned_by_main = previous_owned_provider
        tdx.main._tdx_bridge_owned_by_main = previous_owned_bridge
        tdx.main._tdx_collector_owned_by_main = previous_owned_collector
        tdx.main._tdx_subscription_client_owned_by_main = previous_owned_subscription_client
