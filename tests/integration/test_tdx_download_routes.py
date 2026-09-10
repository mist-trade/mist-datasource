"""Integration tests for the TDX download job routes (/v1/tdx/download)."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import tdx.main
from src.datasource.tdx.history_download import TdxHistoryDownloadRegistry


class FakeTdxHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        return {"ErrorId": "0", "Msg": "refresh kline cache success."}


@pytest.fixture
async def tdx_client() -> AsyncClient:
    previous_registry = tdx.main.app.state.tdx_download_registry
    fake_client = FakeTdxHttpClient()

    def clock() -> float:
        return 0.0

    registry = TdxHistoryDownloadRegistry(client=fake_client, clock=clock)
    tdx.main.app.state.tdx_download_registry = registry

    async with AsyncClient(
        transport=ASGITransport(app=tdx.main.app), base_url="http://test"
    ) as client:
        yield client

    tdx.main.app.state.tdx_download_registry = previous_registry


@pytest.mark.asyncio
async def test_download_submit_and_complete(tdx_client) -> None:
    response = await tdx_client.post(
        "/v1/tdx/download",
        json={
            "stock_list": ["000688.SH", "880003.SH"],
            "base_periods": ["1m", "5m", "1d"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["jobId"]
    assert len(body["data"]["tasks"]) == 3
    job_id = body["data"]["jobId"]

    # 等后台刷新任务完成，job 状态到 all_done
    for _ in range(50):
        status = await tdx_client.get(f"/v1/tdx/download/{job_id}")
        status_body = status.json()
        if status_body["data"]["aggregate"] == "all_done":
            break
        await asyncio.sleep(0.02)

    assert status_body["data"]["aggregate"] == "all_done"
    assert all(t["state"] == "done" for t in status_body["data"]["tasks"])


@pytest.mark.asyncio
async def test_download_rejects_invalid_base_period(tdx_client) -> None:
    response = await tdx_client.post(
        "/v1/tdx/download",
        json={
            "stock_list": ["000688.SH"],
            "base_periods": ["15m"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "TDX_DOWNLOAD_REQUEST_INVALID"
    assert body["error"]["details"]["reason"] == "invalid_base_period"


@pytest.mark.asyncio
async def test_download_status_unknown_job(tdx_client) -> None:
    response = await tdx_client.get("/v1/tdx/download/dl-does-not-exist")

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "TDX_DOWNLOAD_JOB_NOT_FOUND"
