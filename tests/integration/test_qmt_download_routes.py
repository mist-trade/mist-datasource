"""Integration tests for the QMT download job routes (/v1/qmt/download).

ActivityWindow is monkeypatched so tests are deterministic regardless of wall
clock: functional tests force the window OFF; the in-session gate test forces
it ON.
"""

import asyncio

import pytest

import qmt.main
import qmt.routes.v1.product as product_routes
from src.datasource.qmt.realtime.gateway import QmtCommandGateway


async def _wait_for_pending(gateway: QmtCommandGateway) -> None:
    for _ in range(100):
        if gateway.health()["pendingCount"] == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("QMT download command was not enqueued")


@pytest.fixture
def window_off(monkeypatch):
    class _ClosedWindow:
        def in_window(self, _now=None):
            return False

    monkeypatch.setattr(product_routes, "_ACTIVITY_WINDOW", _ClosedWindow())


@pytest.fixture
def window_open(monkeypatch):
    class _OpenWindow:
        def in_window(self, _now=None):
            return True

    monkeypatch.setattr(product_routes, "_ACTIVITY_WINDOW", _OpenWindow())


@pytest.mark.asyncio
@pytest.mark.usefixtures("window_off")
async def test_download_submit_returns_job_and_executes_serially(qmt_client) -> None:
    gateway = qmt.main.app.state.qmt_command_gateway
    gateway.register_owner("bridge-a")

    response = await qmt_client.post(
        "/v1/qmt/download",
        json={
            "stock_list": ["000688.SH"],
            "base_periods": ["1m", "5m", "1d"],
            "start_time": "20260901",
            "end_time": "20260908",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["jobId"]
    assert len(body["data"]["tasks"]) == 3
    job_id = body["data"]["jobId"]

    # 桥侧逐命令取走并完成（模拟终端串行下载）
    for period in ("1m", "5m", "1d"):
        await _wait_for_pending(gateway)
        commands = gateway.poll("bridge-a", limit=1)
        assert len(commands) == 1
        assert commands[0].method == "download_history_data"
        assert commands[0].params["periods"] == [period]
        gateway.post_result(
            "bridge-a", commands[0].command_id, ok=True, result=None
        )

    status_body = None
    for _ in range(50):
        status = await qmt_client.get(f"/v1/qmt/download/{job_id}")
        status_body = status.json()
        if status_body["data"]["aggregate"] == "all_done":
            break
        await asyncio.sleep(0.02)

    assert status_body is not None
    assert status_body["data"]["aggregate"] == "all_done"
    assert all(t["state"] == "done" for t in status_body["data"]["tasks"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("window_off")
async def test_download_submit_rejects_invalid_base_period(qmt_client) -> None:
    response = await qmt_client.post(
        "/v1/qmt/download",
        json={
            "stock_list": ["000688.SH"],
            "base_periods": ["15m"],
            "start_time": "20260901",
            "end_time": "20260908",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_DOWNLOAD_REQUEST_INVALID"
    assert body["error"]["details"]["reason"] == "invalid_base_period"


@pytest.mark.asyncio
@pytest.mark.usefixtures("window_off")
async def test_download_submit_rejects_invalid_symbol(qmt_client) -> None:
    response = await qmt_client.post(
        "/v1/qmt/download",
        json={
            "stock_list": ["000688"],
            "base_periods": ["1m"],
            "start_time": "20260901",
            "end_time": "20260908",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_DOWNLOAD_REQUEST_INVALID"
    assert body["error"]["details"]["reason"] == "invalid_symbol_format"


@pytest.mark.asyncio
@pytest.mark.usefixtures("window_off")
async def test_download_status_unknown_job_returns_not_found(qmt_client) -> None:
    response = await qmt_client.get("/v1/qmt/download/dl-does-not-exist")

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_DOWNLOAD_JOB_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.usefixtures("window_open")
async def test_download_submit_refused_in_session(qmt_client) -> None:
    response = await qmt_client.post(
        "/v1/qmt/download",
        json={
            "stock_list": ["000688.SH"],
            "base_periods": ["1m"],
            "start_time": "20260901",
            "end_time": "20260908",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_DOWNLOAD_IN_SESSION"
