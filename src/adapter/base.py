"""Base adapter abstract class for market data providers."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Protocol


class MarketDataAdapter(ABC):
    """交易引擎适配器基类.

    仅定义 initialize/shutdown 抽象方法。
    TDX/QMT 各自在自己的 adapter 中定义全部方法，不共享签名。
    """

    @abstractmethod
    async def initialize(self) -> None:
        """初始化连接."""

    @abstractmethod
    async def shutdown(self) -> None:
        """关闭连接."""


class AdapterLifecycle(Protocol):
    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...


class QmtDataAdapter(AdapterLifecycle, Protocol):
    async def get_stock_list(self, market: str = "0") -> list[str]: ...

    async def get_stock_list_in_sector(
        self,
        block_code: str = "沪深300",
        block_type: int = 0,
        list_type: int = 0,
    ) -> list[str]: ...

    async def get_market_data(
        self,
        stock_list: list[str],
        fields: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def subscribe_quote(self, stock_list: list[str]) -> AsyncIterator[dict[str, Any]]: ...

    async def get_local_data(
        self,
        stock_list: list[str],
        fields: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def get_full_tick(self, code_list: list[str]) -> dict[str, Any]: ...

    async def get_full_kline(
        self,
        stock_list: list[str],
        period: str = "1m",
        fields: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        count: int = 1,
        dividend_type: str = "none",
    ) -> dict[str, Any]: ...

    async def get_divid_factors(
        self,
        stock_code: str,
        start_time: str = "",
        end_time: str = "",
    ) -> dict[str, Any]: ...

    async def download_history_data(
        self,
        stock_code: str,
        period: str,
        start_time: str = "",
        end_time: str = "",
        incrementally: bool | None = None,
    ) -> None: ...

    async def download_history_data2(
        self,
        stock_list: list[str],
        period: str,
        start_time: str = "",
        end_time: str = "",
    ) -> None: ...

    async def get_trading_dates(
        self,
        market: str,
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
    ) -> list[str]: ...

    async def get_trading_calendar(
        self,
        market: str,
        start_time: str = "",
        end_time: str = "",
    ) -> list[str]: ...

    async def get_holidays(self) -> list[str]: ...

    async def download_holiday_data(self) -> None: ...

    async def get_period_list(self) -> list[str]: ...

    async def get_instrument_detail(
        self,
        stock_code: str,
        iscomplete: bool = False,
    ) -> dict[str, Any] | None: ...

    async def get_instrument_type(self, stock_code: str) -> dict[str, Any] | None: ...

    async def get_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        report_type: str = "report_time",
    ) -> dict[str, Any]: ...

    async def download_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
    ) -> None: ...

    async def download_financial_data2(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
    ) -> None: ...

    async def get_sector_list(self) -> list[str]: ...

    async def download_sector_data(self) -> None: ...

    async def get_index_weight(self, index_code: str) -> dict[str, Any]: ...

    async def download_index_weight(self) -> None: ...

    async def create_sector_folder(
        self,
        parent_node: str,
        folder_name: str,
        overwrite: bool = True,
    ) -> str: ...

    async def create_sector(
        self,
        parent_node: str = "",
        sector_name: str = "",
        overwrite: bool = True,
    ) -> str: ...

    async def add_sector(self, sector_name: str, stock_list: list[str]) -> None: ...

    async def remove_stock_from_sector(
        self,
        sector_name: str,
        stock_list: list[str],
    ) -> bool: ...

    async def remove_sector(self, sector_name: str) -> None: ...

    async def reset_sector(self, sector_name: str, stock_list: list[str]) -> bool: ...

    async def get_cb_info(self, stock_code: str) -> dict[str, Any]: ...

    async def download_cb_data(self) -> None: ...

    async def get_ipo_info(
        self,
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict[str, Any]]: ...

    async def get_etf_info(self) -> Any: ...

    async def download_etf_info(self) -> None: ...

    async def order_stock(
        self,
        stock_code: str,
        order_type: int,
        volume: int,
        price_type: int,
        price: float,
        strategy_name: str = "",
        order_remark: str = "",
    ) -> int: ...

    async def query_stock_orders(self) -> list[dict[str, Any]]: ...

    async def query_stock_positions(self) -> list[dict[str, Any]]: ...


class TdxDataAdapter(AdapterLifecycle, Protocol):
    async def get_stock_list_in_sector(
        self,
        block_code: str = "通达信88",
        block_type: int = 0,
        list_type: int = 0,
    ) -> list[str]: ...

    async def get_market_data(
        self,
        stock_list: list[str],
        fields: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def subscribe_hq(self, stock_list: list[str], callback: Any) -> Any: ...

    async def unsubscribe_hq(self, stock_list: list[str] | None = None) -> Any: ...
