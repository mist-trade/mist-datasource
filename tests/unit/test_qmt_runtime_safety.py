import asyncio
import threading
import time
from typing import Any

import pytest

from src.adapter.qmt.client import QMTAdapter


class BlockingXtData:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls: list[dict[str, Any]] = []

    def get_market_data(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        self.release.wait(timeout=1)
        return {"Close": {"600519.SH": {"2026-07-02": "10.2"}}}


@pytest.mark.asyncio
async def test_qmt_market_data_does_not_block_event_loop():
    xtdata = BlockingXtData()
    adapter = QMTAdapter(path="/mock/qmt", account_id="mock")
    adapter._xtdata = xtdata
    threading.Timer(0.2, xtdata.release.set).start()

    async def loop_tick() -> float:
        start = time.monotonic()
        await asyncio.sleep(0.02)
        return time.monotonic() - start

    market_data_task = asyncio.create_task(
        adapter.get_market_data(
            stock_list=["600519.SH"],
            fields=["Close"],
            period="1d",
        )
    )
    tick_elapsed = await loop_tick()
    result = await market_data_task

    assert tick_elapsed < 0.1
    assert result["Close"]["600519.SH"]["2026-07-02"] == "10.2"


class CallbackXtData:
    def __init__(self) -> None:
        self.callback: Any | None = None
        self.unsubscribed: list[str] = []

    def subscribe_quote(self, stock_code: str, period: str, callback: Any) -> None:
        _ = period
        self.callback = callback
        self.stock_code = stock_code

    def unsubscribe_quote(self, stock_code: str) -> None:
        self.unsubscribed.append(stock_code)


@pytest.mark.asyncio
async def test_qmt_quote_callback_uses_captured_loop_from_thread():
    xtdata = CallbackXtData()
    adapter = QMTAdapter(path="/mock/qmt", account_id="mock")
    adapter._xtdata = xtdata

    quote_stream = adapter.subscribe_quote(["600519.SH"])
    next_quote = asyncio.create_task(anext(quote_stream))
    await asyncio.sleep(0)
    assert xtdata.callback is not None

    callback_error: list[BaseException] = []

    def run_callback() -> None:
        try:
            xtdata.callback({"symbol": "600519.SH", "price": 10.2})
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            callback_error.append(exc)

    thread = threading.Thread(target=run_callback)
    thread.start()
    quote = await asyncio.wait_for(next_quote, timeout=1)
    thread.join(timeout=1)
    await quote_stream.aclose()

    assert callback_error == []
    assert quote == {"symbol": "600519.SH", "price": 10.2}
    assert xtdata.unsubscribed == ["600519.SH"]
