from typing import Any

from src.core.config import settings
from src.datasource.tdx_http_client import TdxHttpClient
from src.datasource.tdx_models import TdxBar, TdxSnapshot
from src.datasource.tdx_normalization import (
    normalize_symbol,
    normalize_tdx_bar_rows,
    normalize_tdx_snapshot,
    to_tdx_http_code,
)

TDX_MARKET_DATA_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount"]
TDX_HEALTH_PROBE_SYMBOL = "600519.SH"


class TdxDatasourceProvider:
    def __init__(self, client: TdxHttpClient | None = None) -> None:
        self.client = client or TdxHttpClient(settings.tdx.http_url)

    async def get_bars(
        self,
        symbols: list[str],
        *,
        period: str,
        start_time: str | None,
        end_time: str | None,
        count: int | None,
    ) -> list[TdxBar]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_market_data",
            {
                "stock_list": tdx_symbols,
                "field_list": TDX_MARKET_DATA_FIELDS,
                "period": period,
                "start_time": start_time,
                "end_time": end_time,
                "count": count,
            },
        )

        bars: list[TdxBar] = []
        for symbol in tdx_symbols:
            bars.extend(normalize_tdx_bar_rows(symbol, period, native))
        return bars

    async def collect_recent_bars(
        self,
        symbols: list[str],
        period: str,
        count: int,
    ) -> list[TdxBar]:
        return await self.get_bars(
            symbols,
            period=period,
            start_time=None,
            end_time=None,
            count=count,
        )

    async def get_snapshots(
        self,
        symbols: list[str],
        fields: list[str] | None = None,
    ) -> list[TdxSnapshot]:
        snapshots: list[TdxSnapshot] = []
        for symbol in symbols:
            tdx_symbol = to_tdx_http_code(symbol)
            native = await self.client.call(
                "get_market_snapshot",
                {
                    "stock_code": tdx_symbol,
                    "field_list": fields or [],
                },
            )
            snapshots.append(normalize_tdx_snapshot(tdx_symbol, native))
        return snapshots

    async def raw_call(self, method: str, params: dict[str, Any] | list[Any] | None = None) -> Any:
        return await self.client.call(method, params)

    async def get_sector_members(self, sector: str) -> list[str]:
        native = await self.client.call(
            "get_stock_list_in_sector",
            {
                "block_code": sector,
            },
        )
        return [normalize_symbol(symbol) for symbol in native]

    async def call_formula(
        self,
        name: str,
        args: dict[str, Any] | list[Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        return await self.client.call(
            name,
            {
                "args": args,
                "context": context or {},
            },
        )

    async def health(self) -> dict[str, Any]:
        try:
            await self.client.call(
                "get_market_snapshot",
                {
                    "stock_code": TDX_HEALTH_PROBE_SYMBOL,
                    "field_list": [],
                },
            )
        except Exception as exc:
            return {
                "tdxHttpReachable": False,
                "lastError": str(exc),
            }

        return {
            "tdxHttpReachable": True,
            "lastError": None,
        }

    async def aclose(self) -> None:
        await self.client.aclose()
