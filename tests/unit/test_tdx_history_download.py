"""Unit tests for the TDX history download job registry (task 5.2/5.4)."""

import asyncio

import pytest

from src.datasource.tdx.history_download import TdxHistoryDownloadRegistry


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeTdxClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if self.fail:
            raise RuntimeError("terminal http down")
        return {"ErrorId": "0", "Msg": "refresh kline cache success."}


def make_registry(client: FakeTdxClient):
    clock = FakeClock()
    registry = TdxHistoryDownloadRegistry(client=client, clock=clock)
    return registry, clock


@pytest.mark.asyncio
async def test_submit_creates_one_task_per_base_period():
    client = FakeTdxClient()
    registry, _clock = make_registry(client)

    submitted = registry.submit_download_job(
        stock_list=["000688.SH", "880003.SH"],
        base_periods=["1m", "5m", "1d"],
    )

    # TDX 原生 API 按 (stock_list × period) 粒度：每周期一个任务，覆盖全部标的
    assert len(submitted["tasks"]) == 3
    assert submitted["jobId"]
    status = registry.job_status(submitted["jobId"])
    assert status is not None
    assert status["aggregate"] == "in_progress"


@pytest.mark.asyncio
async def test_job_calls_refresh_kline_per_period_and_completes():
    client = FakeTdxClient()
    registry, _clock = make_registry(client)

    submitted = registry.submit_download_job(
        stock_list=["000688.SH", "880003.SH"],
        base_periods=["1m", "5m", "1d"],
    )
    job_id = submitted["jobId"]

    for _ in range(20):
        await asyncio.sleep(0.02)
        status = registry.job_status(job_id)
        if status is not None and status["aggregate"] == "all_done":
            break

    status = registry.job_status(job_id)
    assert status is not None
    assert status["aggregate"] == "all_done"
    # refresh_kline 每周期一次，覆盖两个标的
    kline_calls = [c for c in client.calls if c[0] == "refresh_kline"]
    assert len(kline_calls) == 3
    periods = [c[1]["period"] for c in kline_calls]
    assert periods == ["1m", "5m", "1d"]
    assert all(set(c[1]["stock_list"]) == {"000688.SH", "880003.SH"} for c in kline_calls)


@pytest.mark.asyncio
async def test_client_failure_marks_task_failed():
    client = FakeTdxClient(fail=True)
    registry, _clock = make_registry(client)

    submitted = registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m"],
    )
    job_id = submitted["jobId"]

    for _ in range(20):
        await asyncio.sleep(0.02)
        status = registry.job_status(job_id)
        if status is not None and status["aggregate"] != "in_progress":
            break

    status = registry.job_status(job_id)
    assert status is not None
    assert status["aggregate"] == "any_failed"
    assert status["tasks"][0]["state"] == "failed"


@pytest.mark.asyncio
async def test_ttl_expires_completed_jobs():
    clock = FakeClock()
    client = FakeTdxClient()
    registry = TdxHistoryDownloadRegistry(client=client, clock=clock, ttl_seconds=100)

    submitted = registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m"],
    )
    job_id = submitted["jobId"]

    # 等 job 完成（后台任务），再让时钟越过 TTL
    for _ in range(50):
        status = registry.job_status(job_id)
        if status is not None and status["aggregate"] == "all_done":
            break
        await asyncio.sleep(0.02)
    clock.advance(200)

    assert registry.job_status(job_id) is None
