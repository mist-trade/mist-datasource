import asyncio

from src.core.config import settings
from src.datasource.admin.guard import AdminGuard
from src.datasource.qmt.classification import (
    QMT_CLASSIFICATION as QMT_CLASSIFICATION,
)
from src.datasource.qmt.classification import (
    QMT_DENIED_FAMILIES as QMT_DENIED_FAMILIES,
)
from src.datasource.qmt.operations.market import (
    QmtBridgeError as QmtBridgeError,
)
from src.datasource.qmt.operations.market import QmtMarketOperations
from src.datasource.qmt.realtime.gateway import QmtCommandGateway


class QmtDatasourceProvider:
    def __init__(self) -> None:
        self._market = QmtMarketOperations()
        self._admin_guard = AdminGuard(
            "qmt", QMT_CLASSIFICATION, QMT_DENIED_FAMILIES
        )

    async def admin_call_native(
        self,
        method: str,
        params: dict[str, object] | None,
        *,
        command_gateway: QmtCommandGateway | None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Execute a classified ContextInfo method via the bridge (admin surface).

        执法单层：datasource 分类守卫（未分类/拒绝族拒）+ 桥内一行交易硬拒
        （TRADING_DENY_PATTERNS，见桥 v3.1）。同步执行会阻塞桥主循环至完成，
        因此发送前延长 busy_until（owner 租约放行，design D4）。
        """
        verdict = self._admin_guard.evaluate(method)
        if not verdict.allowed:
            raise QmtBridgeError(
                code=(
                    "QMT_METHOD_UNCLASSIFIED"
                    if verdict.reason == "unclassified"
                    else "QMT_METHOD_FAMILY_FORBIDDEN"
                ),
                message=f"Method '{method}' is forbidden: {verdict.reason}",
                retryable=False,
                details={"method": method, "reason": verdict.reason},
            )
        timeout_seconds = (
            settings.qmt.admin_call_timeout_ms / 1000
            if timeout_seconds is None
            else timeout_seconds
        )
        if command_gateway is None:
            raise QmtBridgeError(
                code="QMT_BRIDGE_UNAVAILABLE",
                message="QMT command gateway is not initialized",
                retryable=True,
            )
        command_gateway.extend_busy_until(timeout_seconds + 60)
        command = command_gateway.enqueue(
            "call_native",
            {"method": method, "kwargs": dict(params or {})},
            timeout_seconds=timeout_seconds,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            command_gateway.expire_timed_out()
            result = command_gateway.take_result(command.command_id)
            if result is None:
                await asyncio.sleep(0.05)
                continue
            return {
                "method": method,
                "result": result.result,
                "ok": result.ok,
                "error": result.error,
            }
        command_gateway.expire_timed_out()
        raise QmtBridgeError(
            code="QMT_ADMIN_CALL_TIMEOUT",
            message="QMT admin call result timed out",
            retryable=True,
            details={
                "method": method,
                "timeoutSeconds": timeout_seconds,
            },
        )

    async def get_bars(
        self,
        stock_list: list[str],
        *,
        period: str,
        start_time: str | None,
        end_time: str | None,
        count: int | None,
        fields: list[str] | None = None,
        dividend_type: str | None = None,
        fill_data: bool | None = None,
        include_raw: bool = False,
        command_gateway: QmtCommandGateway | None = None,
        bridge_timeout_seconds: float = 10.0,
    ) -> dict[str, object]:
        return await self._market.get_bars(
            stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            fields=fields,
            dividend_type=dividend_type,
            fill_data=fill_data,
            include_raw=include_raw,
            command_gateway=command_gateway,
            bridge_timeout_seconds=bridge_timeout_seconds,
        )

    async def collect_recent_bars(
        self,
        stock_list: list[str],
        period: str,
        count: int,
        *,
        command_gateway: QmtCommandGateway | None = None,
    ) -> dict[str, object]:
        return await self._market.collect_recent_bars(
            stock_list,
            period,
            count,
            command_gateway=command_gateway,
        )
