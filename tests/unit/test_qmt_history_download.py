"""Unit tests for the QMT history download job registry (task 1.1)."""

import asyncio

import pytest

from src.datasource.qmt.history_download import QmtHistoryDownloadRegistry
from src.datasource.qmt.realtime.gateway import QmtCommandGateway


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_registry(stale_after: float = 15.0):
    clock = FakeClock()
    gateway = QmtCommandGateway(
        clock=clock, owner_stale_after_seconds=stale_after
    )
    gateway.register_owner("bridge-a")
    gateway.heartbeat("bridge-a")
    registry = QmtHistoryDownloadRegistry(
        command_gateway=gateway, clock=clock
    )
    return gateway, registry, clock


async def drain_one(gateway: QmtCommandGateway, ok: bool) -> None:
    for _ in range(100):
        commands = gateway.poll("bridge-a", limit=1)
        for command in commands:
            gateway.post_result(
                "bridge-a", command.command_id, ok=ok, result=None
            )
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no pending download command to drain")


@pytest.mark.asyncio
async def test_submit_creates_job_with_per_period_tasks():
    gateway, registry, _clock = make_registry()

    submitted = registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m", "5m", "1d"],
        start_time="20260901",
        end_time="20260908",
        timeout_seconds=60,
    )

    assert submitted["jobId"]
    assert len(submitted["tasks"]) == 3
    status = registry.job_status(submitted["jobId"])
    assert status is not None
    assert status["aggregate"] == "in_progress"


@pytest.mark.asyncio
async def test_job_executes_serially_and_reports_all_done():
    gateway, registry, _clock = make_registry()

    submitted = registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m", "5m"],
        start_time="20260901",
        end_time="20260908",
        timeout_seconds=60,
    )
    job_id = submitted["jobId"]

    # 模拟桥：逐命令取走并成功返回
    for _ in range(20):
        await asyncio.sleep(0.02)
        commands = gateway.poll("bridge-a", limit=1)
        for command in commands:
            assert command.method == "download_history_data"
            gateway.post_result("bridge-a", command.command_id, ok=True, result=None)
        status = registry.job_status(job_id)
        if status is not None and status["aggregate"] == "all_done":
            break

    status = registry.job_status(job_id)
    assert status is not None
    assert status["aggregate"] == "all_done"
    assert all(t["state"] == "done" for t in status["tasks"])


@pytest.mark.asyncio
async def test_download_command_failure_marks_task_failed():
    gateway, registry, _clock = make_registry()

    submitted = registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m"],
        start_time="20260901",
        end_time="20260908",
        timeout_seconds=60,
    )
    job_id = submitted["jobId"]

    for _ in range(20):
        await asyncio.sleep(0.02)
        commands = gateway.poll("bridge-a", limit=1)
        for command in commands:
            gateway.post_result(
                "bridge-a",
                command.command_id,
                ok=False,
                result=None,
                error={"code": "QMT_DOWNLOAD_API_UNAVAILABLE", "message": "missing"},
            )
        status = registry.job_status(job_id)
        if status is not None and status["aggregate"] != "in_progress":
            break

    status = registry.job_status(job_id)
    assert status is not None
    assert status["aggregate"] == "any_failed"
    assert status["tasks"][0]["state"] == "failed"


@pytest.mark.asyncio
async def test_download_extends_busy_until_per_command():
    gateway, registry, clock = make_registry()

    registry.submit_download_job(
        stock_list=["000688.SH"],
        base_periods=["1m"],
        start_time="20260901",
        end_time="20260908",
        timeout_seconds=600,
    )
    # 等待在途命令入队
    for _ in range(100):
        if gateway.health()["pendingCount"] > 0:
            break
        await asyncio.sleep(0.01)

    # 在途命令期间心跳停摆 30s > 15s 阈值，但 busy_until 放行 → 不判死
    gateway.heartbeat("bridge-a")
    clock.advance(30)
    assert gateway.health()["ownerStale"] is False

    # busy_until（submit 时 extend 的 timeout+60s）过期后恢复正常判定
    clock.advance(700)
    assert gateway.health()["ownerStale"] is True
