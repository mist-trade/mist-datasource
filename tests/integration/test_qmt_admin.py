"""Integration tests for the QMT admin escape hatch (/v1/raw/qmt/call)."""

import asyncio

import pytest

import qmt.main
from src.datasource.qmt.realtime.gateway import QmtCommandGateway


async def _wait_for_pending(gateway: QmtCommandGateway) -> None:
    for _ in range(100):
        if gateway.health()["pendingCount"] == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("QMT admin call was not enqueued")


@pytest.mark.asyncio
async def test_admin_call_executes_classified_method(qmt_client) -> None:
    gateway = qmt.main.app.state.qmt_command_gateway
    gateway.register_owner("bridge-a")
    request_task = asyncio.create_task(
        qmt_client.post(
            "/v1/raw/qmt/call",
            json={
                "method": "get_local_data",
                "params": {"period": "1m"},
                "timeout_ms": 600000,
            },
        )
    )
    await _wait_for_pending(gateway)
    commands = gateway.poll("bridge-a", limit=1)

    assert len(commands) == 1
    assert commands[0].method == "call_native"
    assert commands[0].params == {
        "method": "get_local_data",
        "kwargs": {"period": "1m"},
    }
    gateway.post_result(
        "bridge-a",
        commands[0].command_id,
        ok=True,
        result={"000001.SZ": {"close": {"20260908093100": 10.5}}},
    )

    response = await request_task

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["method"] == "get_local_data"
    assert body["data"]["ok"] is True


@pytest.mark.asyncio
async def test_admin_call_rejects_passorder_in_datasource_guard(qmt_client) -> None:
    gateway = qmt.main.app.state.qmt_command_gateway
    gateway.register_owner("bridge-a")

    response = await qmt_client.post(
        "/v1/raw/qmt/call",
        json={"method": "passorder", "params": {}, "timeout_ms": 600000},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_METHOD_FAMILY_FORBIDDEN"
    assert gateway.health()["pendingCount"] == 0


@pytest.mark.asyncio
async def test_admin_call_rejects_unclassified_methods(qmt_client) -> None:
    gateway = qmt.main.app.state.qmt_command_gateway
    gateway.register_owner("bridge-a")

    response = await qmt_client.post(
        "/v1/raw/qmt/call",
        json={"method": "some_unknown_method", "params": {}, "timeout_ms": 600000},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_METHOD_UNCLASSIFIED"
    assert gateway.health()["pendingCount"] == 0


@pytest.mark.asyncio
async def test_admin_call_times_out_when_bridge_never_polls(qmt_client) -> None:
    gateway = qmt.main.app.state.qmt_command_gateway
    gateway.register_owner("bridge-a")

    response = await qmt_client.post(
        "/v1/raw/qmt/call",
        json={"method": "get_local_data", "params": {}, "timeout_ms": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == "QMT_ADMIN_CALL_TIMEOUT"
