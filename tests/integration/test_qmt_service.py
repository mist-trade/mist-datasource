"""Integration tests for QMT service."""

import pytest

import qmt.main
from qmt.services.qmt_service import QMTService
from src.adapter import create_qmt_adapter


@pytest.mark.asyncio
async def test_get_sector_overview():
    """Test getting sector overview."""
    adapter = create_qmt_adapter(path="/test", account_id="12345")
    await adapter.initialize()

    service = QMTService()
    original_adapter = qmt.main.qmt_adapter
    qmt.main.qmt_adapter = adapter

    try:
        overview = await service.get_sector_overview()

        assert "sector" in overview
        assert "total_stocks" in overview
        assert "sample_data" in overview
    finally:
        qmt.main.qmt_adapter = original_adapter
        await adapter.shutdown()


@pytest.mark.asyncio
async def test_get_account_overview_uses_stock_position_interface():
    """Test account overview calls the adapter's stock-position API."""

    class AccountAdapter:
        async def query_stock_positions(self):
            return [{"symbol": "600519.SH"}]

        async def query_stock_orders(self):
            return [{"orderId": 1}]

    service = QMTService()
    original_adapter = qmt.main.qmt_adapter
    qmt.main.qmt_adapter = AccountAdapter()

    try:
        overview = await service.get_account_overview()

        assert overview["positions"] == [{"symbol": "600519.SH"}]
        assert overview["position_count"] == 1
        assert overview["orders"] == [{"orderId": 1}]
        assert overview["order_count"] == 1
    finally:
        qmt.main.qmt_adapter = original_adapter
