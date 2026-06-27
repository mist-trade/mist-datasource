import asyncio
from typing import Any

from src.core.config import settings
from src.datasource.tdx_http_client import TdxHttpClient
from src.datasource.tdx_models import TdxBar, TdxSnapshot
from src.datasource.tdx_normalization import (
    normalize_symbol,
    normalize_tdx_bar_rows,
    normalize_tdx_snapshot,
    to_tdx_code,
    to_tdx_http_code,
)

TDX_MARKET_DATA_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount"]
TDX_HEALTH_PROBE_SYMBOL = "600519.SH"


class TdxFormulaRequestLimitError(Exception):
    def __init__(
        self,
        *,
        limit: str,
        observed: int,
        maximum: int,
    ) -> None:
        super().__init__(f"Formula request exceeds {limit} limit")
        self.code = "FORMULA_REQUEST_LIMIT_EXCEEDED"
        self.message = f"Formula request exceeds {limit} limit"
        self.retryable = False
        self.details = {
            "limit": limit,
            "observed": observed,
            "maximum": maximum,
        }


class TdxFormulaTimeoutError(Exception):
    def __init__(self, *, method: str, timeout_ms: int) -> None:
        super().__init__(f"Formula method {method} timed out after {timeout_ms} ms")
        self.code = "FORMULA_TIMEOUT"
        self.message = f"Formula method {method} timed out after {timeout_ms} ms"
        self.retryable = True
        self.details = {
            "method": method,
            "timeoutMs": timeout_ms,
        }


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

    async def get_price_volume(
        self,
        symbols: list[str],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_pricevol",
            {
                "stock_list": tdx_symbols,
                "field_list": fields or [],
            },
        )
        return [_normalize_price_volume_item(symbol, native) for symbol in tdx_symbols]

    async def get_trading_dates(
        self,
        market: str,
        start_time: str | None = None,
        end_time: str | None = None,
        count: int | None = None,
    ) -> list[str]:
        native = await self.client.call(
            "get_trading_dates",
            {
                "market": market,
                "start_time": start_time or "",
                "end_time": end_time or "",
                "count": count if count is not None else -1,
            },
        )
        values = _unwrap_tdx_value(native)
        if isinstance(values, list | tuple):
            return [str(value) for value in values]
        return []

    async def get_securities(self, market: str = "5") -> list[dict[str, Any]]:
        native = await self.client.call("get_stock_list", {"market": market})
        values = _unwrap_tdx_value(native)
        if not isinstance(values, list | tuple):
            return []
        return [_normalize_security_item(item) for item in values]

    async def get_security_info(self, symbols: list[str]) -> list[dict[str, Any]]:
        securities: list[dict[str, Any]] = []
        for symbol in symbols:
            tdx_symbol = to_tdx_http_code(symbol)
            stock_info = await self.client.call("get_stock_info", {"stock_code": tdx_symbol})
            more_info = await self.client.call(
                "get_more_info",
                {
                    "stock_code": tdx_symbol,
                    "field_list": [],
                },
            )
            securities.append(_normalize_security_info(tdx_symbol, stock_info, more_info))
        return securities

    async def get_security_relations(self, symbol: str) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call("get_relation", {"stock_code": tdx_symbol})
        return _normalize_relation_items(tdx_symbol, native)

    async def get_ipo_info(self, ipo_type: int = 0, ipo_date: int = 0) -> list[dict[str, Any]]:
        native = await self.client.call(
            "get_ipo_info",
            {
                "ipo_type": ipo_type,
                "ipo_date": ipo_date,
            },
        )
        return [_normalize_ipo_item(item) for item in _native_items(native, "IPOStocks")]

    async def get_share_capital(
        self,
        symbol: str,
        date_list: list[str],
        count: int,
    ) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call(
            "get_gb_info",
            {
                "stock_code": tdx_symbol,
                "date_list": date_list,
                "count": count,
            },
        )
        return [_normalize_share_capital_item(tdx_symbol, item) for item in _native_items(native)]

    async def get_share_capital_by_date(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call(
            "get_gb_info_by_date",
            {
                "stock_code": tdx_symbol,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [_normalize_share_capital_item(tdx_symbol, item) for item in _native_items(native)]

    async def get_dividend_factors(
        self,
        symbol: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call(
            "get_divid_factors",
            {
                "stock_code": tdx_symbol,
                "start_time": start_time or "",
                "end_time": end_time or "",
            },
        )
        return [
            _normalize_dividend_factor_item(tdx_symbol, item)
            for item in _native_items(native, "Factors")
        ]

    async def get_convertible_bond_info(
        self,
        symbol: str,
        fields: list[str] | None = None,
        native_method: str = "get_kzz_info",
    ) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call(
            native_method,
            {
                "stock_code": tdx_symbol,
                "field_list": fields or [],
            },
        )
        return [
            _normalize_convertible_bond_item(tdx_symbol, item)
            for item in _native_items(native)
        ]

    async def get_tracking_etfs(self, index_symbol: str) -> list[dict[str, Any]]:
        native = await self.client.call("get_trackzs_etf_info", {"zs_code": index_symbol})
        return [
            _normalize_tracking_etf_item(index_symbol, item)
            for item in _native_items(native, "ETFs")
        ]

    async def get_financial_data(
        self,
        symbols: list[str],
        fields: list[str],
        start_time: str = "",
        end_time: str = "",
        report_type: str = "report_time",
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_financial_data",
            {
                "stock_list": tdx_symbols,
                "field_list": fields,
                "start_time": start_time,
                "end_time": end_time,
                "report_type": report_type,
            },
        )
        return _normalize_financial_data_items(tdx_symbols, fields, native)

    async def get_financial_data_by_date(
        self,
        symbols: list[str],
        fields: list[str],
        year: int = 0,
        mmdd: int = 0,
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_financial_data_by_date",
            {
                "stock_list": tdx_symbols,
                "field_list": fields,
                "year": year,
                "mmdd": mmdd,
            },
        )
        return _normalize_financial_data_items(tdx_symbols, fields, native)

    async def get_single_finance_values(
        self,
        symbols: list[str],
        fields: list[str],
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_gp_one_data",
            {
                "stock_list": tdx_symbols,
                "field_list": fields,
            },
        )
        return _normalize_single_finance_value_items(tdx_symbols, fields, native)

    async def get_stock_trade_aggregate(
        self,
        symbols: list[str],
        fields: list[str],
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_gpjy_value",
            {
                "stock_list": tdx_symbols,
                "field_list": fields,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return _normalize_trade_aggregate_items("stock", tdx_symbols, fields, native)

    async def get_stock_trade_aggregate_by_date(
        self,
        symbols: list[str],
        fields: list[str],
        year: int = 0,
        mmdd: int = 0,
    ) -> list[dict[str, Any]]:
        tdx_symbols = [to_tdx_http_code(symbol) for symbol in symbols]
        native = await self.client.call(
            "get_gpjy_value_by_date",
            {
                "stock_list": tdx_symbols,
                "field_list": fields,
                "year": year,
                "mmdd": mmdd,
            },
        )
        return _normalize_trade_aggregate_items("stock", tdx_symbols, fields, native)

    async def get_sector_trade_aggregate(
        self,
        sector_codes: list[str],
        fields: list[str],
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict[str, Any]]:
        native = await self.client.call(
            "get_bkjy_value",
            {
                "stock_list": sector_codes,
                "field_list": fields,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return _normalize_trade_aggregate_items("sector", sector_codes, fields, native)

    async def get_sector_trade_aggregate_by_date(
        self,
        sector_codes: list[str],
        fields: list[str],
        year: int = 0,
        mmdd: int = 0,
    ) -> list[dict[str, Any]]:
        native = await self.client.call(
            "get_bkjy_value_by_date",
            {
                "stock_list": sector_codes,
                "field_list": fields,
                "year": year,
                "mmdd": mmdd,
            },
        )
        return _normalize_trade_aggregate_items("sector", sector_codes, fields, native)

    async def get_market_trade_aggregate(
        self,
        fields: list[str],
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict[str, Any]]:
        native = await self.client.call(
            "get_scjy_value",
            {
                "field_list": fields,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return _normalize_trade_aggregate_items("market", [None], fields, native)

    async def get_market_trade_aggregate_by_date(
        self,
        fields: list[str],
        year: int = 0,
        mmdd: int = 0,
    ) -> list[dict[str, Any]]:
        native = await self.client.call(
            "get_scjy_value_by_date",
            {
                "field_list": fields,
                "year": year,
                "mmdd": mmdd,
            },
        )
        return _normalize_trade_aggregate_items("market", [None], fields, native)

    async def get_report_data(self, symbol: str) -> list[dict[str, Any]]:
        tdx_symbol = to_tdx_http_code(symbol)
        native = await self.client.call("get_report_data", {"stock_code": tdx_symbol})
        return _normalize_report_data_items(tdx_symbol, native)

    async def format_formula_data(
        self,
        data: dict[str, Any],
        timeout_ms: int = 10000,
    ) -> list[dict[str, Any]]:
        native = await self._call_formula_method(
            "formula_format_data",
            {"data_dict": data},
            timeout_ms=timeout_ms,
        )
        return _normalize_formula_data_items(native)

    async def set_formula_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        native = await self._call_formula_method(
            "formula_set_data",
            {
                "stock_code": payload.get("stockCode", ""),
                "stock_period": payload.get("stockPeriod", "1d"),
                "stock_data": payload.get("stockData", []),
                "count": payload.get("count", -1),
                "dividend_type": payload.get("dividendType", 0),
            },
            timeout_ms=int(payload.get("timeoutMs", 10000)),
        )
        return _normalize_formula_operation_result(native)

    async def set_formula_data_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        native = await self._call_formula_method(
            "formula_set_data_info",
            {
                "stock_code": payload.get("stockCode", ""),
                "stock_period": payload.get("stockPeriod", "1d"),
                "start_time": payload.get("startTime", ""),
                "end_time": payload.get("endTime", ""),
                "count": payload.get("count", -1),
                "dividend_type": payload.get("dividendType", 0),
            },
            timeout_ms=int(payload.get("timeoutMs", 10000)),
        )
        return _normalize_formula_operation_result(native)

    async def get_formula_data(self, timeout_ms: int = 10000) -> dict[str, Any]:
        native = await self._call_formula_method("formula_get_data", {}, timeout_ms=timeout_ms)
        return _normalize_formula_data_item(native)

    async def get_formula_list(
        self,
        formula_type: int = 0,
        timeout_ms: int = 10000,
    ) -> list[dict[str, Any]]:
        native = await self._call_formula_method(
            "formula_get_all",
            {"formula_type": formula_type},
            timeout_ms=timeout_ms,
        )
        return [_normalize_formula_metadata_item(item) for item in _native_items(native)]

    async def get_formula_info(
        self,
        formula_type: int,
        formula_code: str,
        timeout_ms: int = 10000,
    ) -> dict[str, Any]:
        native = await self._call_formula_method(
            "formula_get_info",
            {
                "formula_type": formula_type,
                "formula_code": formula_code,
            },
            timeout_ms=timeout_ms,
        )
        return _normalize_formula_info_item(native)

    async def execute_formula(
        self,
        kind: str,
        formula_name: str,
        formula_arg: str,
        xsflag: int | None,
        timeout_ms: int,
    ) -> dict[str, Any]:
        method = _formula_execution_method(kind)
        params = {
            "formula_name": formula_name,
            "formula_arg": formula_arg,
        }
        if kind == "zb" and xsflag is not None:
            params["xsflag"] = xsflag
        native = await self._call_formula_method(method, params, timeout_ms=timeout_ms)
        return _normalize_formula_execution_result(kind, formula_name, native)

    async def execute_formula_batch(
        self,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        method = _formula_batch_method(kind)
        native = await self._call_formula_method(
            method,
            {
                "formula_name": payload.get("formulaName", ""),
                "formula_arg": payload.get("formulaArg", ""),
                "return_count": payload.get("returnCount", 1),
                "return_date": payload.get("returnDate", False),
                "stock_list": payload.get("stockList", []),
                "stock_period": payload.get("stockPeriod", "1d"),
                "start_time": payload.get("startTime", ""),
                "end_time": payload.get("endTime", ""),
                "count": payload.get("count", -1),
                "dividend_type": payload.get("dividendType", 0),
            },
            timeout_ms=int(payload.get("timeoutMs", 10000)),
        )
        return _normalize_formula_batch_result(kind, payload.get("formulaName", ""), native)

    async def _call_formula_method(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                self.client.call(method, params),
                timeout=max(timeout_ms, 1) / 1000,
            )
        except TimeoutError as exc:
            raise TdxFormulaTimeoutError(method=method, timeout_ms=timeout_ms) from exc

    async def raw_call(self, method: str, params: dict[str, Any] | list[Any] | None = None) -> Any:
        return await self.client.call(method, params)

    async def get_sector_list(self, list_type: int = 0) -> list[dict[str, Any]]:
        native = await self.client.call("get_sector_list", {"list_type": list_type})
        values = _unwrap_tdx_value(native)
        if not isinstance(values, list | tuple):
            return []
        return [_normalize_sector_item(item) for item in values]

    async def get_sector_members(self, sector: str) -> list[str]:
        native = await self.client.call(
            "get_stock_list_in_sector",
            {
                "block_code": sector,
            },
        )
        members = _unwrap_tdx_value(native)
        if not isinstance(members, list | tuple):
            return []
        return [normalize_symbol(str(symbol)) for symbol in members]

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


def _unwrap_tdx_value(native: Any) -> Any:
    if not isinstance(native, dict):
        return native
    for key, value in native.items():
        if key.replace("_", "").replace(" ", "").lower() == "value":
            return value
    return native


def _normalize_security_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        symbol = _first_native_value(item, "symbol", "code", "stock_code", "Code")
        name = _first_native_value(item, "name", "Name", "stock_name")
        return {
            "symbol": normalize_symbol(str(symbol)) if symbol else "",
            "name": str(name) if name is not None else None,
            "provider": "tdx",
            "raw": item,
        }
    if isinstance(item, list | tuple):
        symbol = str(item[0]) if item else ""
        name = str(item[1]) if len(item) > 1 else None
        return {
            "symbol": normalize_symbol(symbol),
            "name": name,
            "provider": "tdx",
            "raw": list(item),
        }
    return {
        "symbol": normalize_symbol(str(item)),
        "name": None,
        "provider": "tdx",
    }


def _normalize_security_info(
    symbol: str,
    stock_info: Any,
    more_info: Any,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "stockInfo": stock_info,
        "moreInfo": more_info,
    }
    stock_info_dict = stock_info if isinstance(stock_info, dict) else {}
    more_info_dict = more_info if isinstance(more_info, dict) else {}
    name = _first_native_value(stock_info_dict, "name", "Name", "stock_name")
    market = _first_native_value(stock_info_dict, "market", "Market")
    if market is None:
        normalized_symbol = normalize_symbol(symbol)
        market = normalized_symbol.split(".", 1)[1] if "." in normalized_symbol else None
    return {
        "symbol": normalize_symbol(symbol),
        "name": str(name) if name is not None else None,
        "market": str(market) if market is not None else None,
        "provider": "tdx",
        "raw": raw,
        "more": more_info_dict,
    }


def _normalize_sector_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        code = _first_native_value(item, "code", "Code", "block_code", "BlockCode")
        name = _first_native_value(item, "name", "Name", "block_name", "BlockName")
        return {
            "code": str(code) if code is not None else "",
            "name": str(name) if name is not None else None,
            "provider": "tdx",
            "raw": item,
        }
    if isinstance(item, list | tuple):
        return {
            "code": str(item[0]) if item else "",
            "name": str(item[1]) if len(item) > 1 else None,
            "provider": "tdx",
            "raw": list(item),
        }
    return {
        "code": str(item),
        "name": None,
        "provider": "tdx",
    }


def _normalize_price_volume_item(symbol: str, native: Any) -> dict[str, Any]:
    normalized_symbol = normalize_symbol(symbol)
    native_item = _native_item_for_symbol(native, normalized_symbol)
    native_dict = native_item if isinstance(native_item, dict) else {}
    return {
        "symbol": normalized_symbol,
        "price": _optional_float(_first_native_value(native_dict, "price", "now", "Now", "last")),
        "volume": _optional_float(_first_native_value(native_dict, "volume", "Volume")),
        "amount": _optional_float(_first_native_value(native_dict, "amount", "Amount")),
        "provider": "tdx",
        "raw": native_item,
    }


def _normalize_relation_items(symbol: str, native: Any) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    relations: list[dict[str, Any]] = []

    if isinstance(values, dict):
        sector_values = _first_native_value(values, "RelatedSectors", "sectors", "sector_list")
        stock_values = _first_native_value(values, "RelatedStocks", "stocks", "stock_list")
        if sector_values is not None or stock_values is not None:
            relations.extend(
                _normalize_relation_group(symbol, "sector", _as_sequence(sector_values))
            )
            relations.extend(_normalize_relation_group(symbol, "stock", _as_sequence(stock_values)))
            return relations
        return [_normalize_relation_item(symbol, values, "unknown")]

    return _normalize_relation_group(symbol, "unknown", _as_sequence(values))


def _normalize_relation_group(
    symbol: str,
    category: str,
    values: list[Any],
) -> list[dict[str, Any]]:
    return [_normalize_relation_item(symbol, item, category) for item in values]


def _normalize_relation_item(
    symbol: str,
    item: Any,
    default_category: str,
) -> dict[str, Any]:
    normalized_symbol = normalize_symbol(symbol)
    if isinstance(item, dict):
        code = _first_native_value(item, "code", "Code", "block_code", "stock_code")
        name = _first_native_value(item, "name", "Name", "block_name")
        category = _first_native_value(item, "category", "Type", "type")
        return {
            "symbol": normalized_symbol,
            "category": str(category) if category is not None else default_category,
            "code": str(code) if code is not None else "",
            "name": str(name) if name is not None else None,
            "provider": "tdx",
            "raw": item,
        }
    return {
        "symbol": normalized_symbol,
        "category": default_category,
        "code": normalize_symbol(str(item)) if default_category == "stock" else str(item),
        "name": None,
        "provider": "tdx",
        "raw": item,
    }


def _normalize_ipo_item(item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    code = _first_native_value(native, "code", "Code")
    name = _first_native_value(native, "name", "Name")
    subscribe_code = _first_native_value(native, "SGCode", "subscribeCode")
    subscribe_date = _first_native_value(native, "SGDate", "subscribeDate")
    issue_price = _first_native_value(native, "SGPrice", "issuePrice")
    return {
        "code": str(code) if code is not None else "",
        "name": str(name) if name is not None else None,
        "subscribeCode": str(subscribe_code) if subscribe_code is not None else None,
        "subscribeDate": str(subscribe_date) if subscribe_date is not None else None,
        "issuePrice": _optional_float(issue_price),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_share_capital_item(symbol: str, item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    date = _first_native_value(native, "Date", "date")
    total_share_capital = _first_native_value(native, "Zgb", "TotalShare", "totalShareCapital")
    float_share_capital = _first_native_value(native, "Ltgb", "FlowShare", "floatShareCapital")
    return {
        "symbol": normalize_symbol(symbol),
        "date": str(date) if date is not None else None,
        "totalShareCapital": _optional_float(total_share_capital),
        "floatShareCapital": _optional_float(float_share_capital),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_dividend_factor_item(symbol: str, item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    date = _first_native_value(native, "Date", "date")
    factor_type = _first_native_value(native, "Type", "type")
    bonus = _first_native_value(native, "Bonus", "bonus")
    allot_price = _first_native_value(native, "AlloPrice", "AllotPrice", "allotPrice")
    share_bonus = _first_native_value(native, "ShareBonus", "shareBonus")
    allotment = _first_native_value(native, "Allotment", "allotment")
    return {
        "symbol": normalize_symbol(symbol),
        "date": str(date) if date is not None else None,
        "type": str(factor_type) if factor_type is not None else None,
        "bonus": _optional_float(bonus),
        "allotPrice": _optional_float(allot_price),
        "shareBonus": _optional_float(share_bonus),
        "allotment": _optional_float(allotment),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_convertible_bond_item(symbol: str, item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    bond_code = _first_native_value(native, "KZZCode", "Code", "code", "stock_code")
    underlying_symbol = _first_native_value(native, "HSCode", "underlyingSymbol")
    convert_price = _first_native_value(native, "ZGPrice", "convertPrice")
    bond_price = _first_native_value(native, "KZZPrice", "bondPrice")
    underlying_price = _first_native_value(native, "AGPrice", "underlyingPrice")
    premium_rate = _first_native_value(native, "KZZYj", "premiumRate")
    convert_value = _first_native_value(native, "ZGValue", "convertValue")
    remaining_size = _first_native_value(native, "RestScope", "remainingSize")
    return {
        "symbol": normalize_symbol(symbol),
        "bondCode": str(bond_code) if bond_code is not None else None,
        "underlyingSymbol": str(underlying_symbol) if underlying_symbol is not None else None,
        "convertPrice": _optional_float(convert_price),
        "bondPrice": _optional_float(bond_price),
        "underlyingPrice": _optional_float(underlying_price),
        "premiumRate": _optional_float(premium_rate),
        "convertValue": _optional_float(convert_value),
        "remainingSize": _optional_float(remaining_size),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_tracking_etf_item(index_symbol: str, item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    code = _first_native_value(native, "Code", "code")
    name = _first_native_value(native, "Name", "name")
    price = _first_native_value(native, "NowPrice", "price")
    pre_close = _first_native_value(native, "PreClose", "preClose")
    iopv = _first_native_value(native, "IOPV", "iopv")
    fund_size = _first_native_value(native, "Sz", "size")
    return {
        "indexSymbol": index_symbol,
        "symbol": normalize_symbol(str(code)) if code is not None else "",
        "name": str(name) if name is not None else None,
        "price": _optional_float(price),
        "preClose": _optional_float(pre_close),
        "iopv": _optional_float(iopv),
        "size": _optional_float(fund_size),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_financial_data_items(
    symbols: list[str],
    fields: list[str],
    native: Any,
) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    items: list[dict[str, Any]] = []

    for symbol in symbols:
        raw_record = _record_for_code(values, symbol)
        for field_name in fields:
            field_value = _lookup_symbol_field(values, symbol, field_name)
            if field_value is None:
                continue
            items.append(
                {
                    "symbol": normalize_symbol(symbol),
                    "field": field_name,
                    "value": _scalar_value(field_value),
                    "announceTime": _metadata_value(raw_record, "announce_time"),
                    "tagTime": _metadata_value(raw_record, "tag_time"),
                    "provider": "tdx",
                    "raw": raw_record,
                }
            )

    return items


def _normalize_single_finance_value_items(
    symbols: list[str],
    fields: list[str],
    native: Any,
) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    items: list[dict[str, Any]] = []
    for symbol in symbols:
        for field_name in fields:
            field_value = _lookup_symbol_field(values, symbol, field_name)
            if field_value is None:
                continue
            items.append(
                {
                    "symbol": normalize_symbol(symbol),
                    "field": field_name,
                    "value": _scalar_value(field_value),
                    "provider": "tdx",
                    "raw": values,
                }
            )
    return items


def _normalize_trade_aggregate_items(
    scope: str,
    codes: list[str | None],
    fields: list[str],
    native: Any,
) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    items: list[dict[str, Any]] = []
    for code in codes:
        for field_name in fields:
            native_value = _lookup_aggregate_value(values, code, field_name)
            if native_value is None:
                continue
            for event in _aggregate_events(native_value):
                date, raw_values = _aggregate_event_parts(event)
                items.append(
                    {
                        "scope": scope,
                        "code": _normalize_aggregate_code(scope, code),
                        "field": field_name,
                        "date": str(date) if date is not None else None,
                        "values": _numeric_values(raw_values),
                        "provider": "tdx",
                        "raw": event,
                    }
                )
    return items


def _normalize_report_data_items(symbol: str, native: Any) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    normalized_symbol = normalize_symbol(symbol)
    if isinstance(values, dict):
        return [
            {
                "symbol": normalized_symbol,
                "field": str(field_name),
                "value": value,
                "provider": "tdx",
                "raw": values,
            }
            for field_name, value in values.items()
        ]
    if isinstance(values, list | tuple):
        return [
            {
                "symbol": normalized_symbol,
                "field": str(index),
                "value": item,
                "provider": "tdx",
                "raw": values,
            }
            for index, item in enumerate(values)
        ]
    if values is None:
        return []
    return [
        {
            "symbol": normalized_symbol,
            "field": "value",
            "value": values,
            "provider": "tdx",
            "raw": values,
        }
    ]


def _normalize_formula_data_items(native: Any) -> list[dict[str, Any]]:
    values = _unwrap_tdx_value(native)
    if isinstance(values, dict):
        return [
            {
                "symbol": normalize_symbol(str(symbol)),
                "rows": _as_sequence(rows),
                "provider": "tdx",
                "raw": rows,
            }
            for symbol, rows in values.items()
        ]
    if isinstance(values, list | tuple):
        return [
            {
                "symbol": None,
                "rows": _as_sequence(values),
                "provider": "tdx",
                "raw": values,
            }
        ]
    return []


def _normalize_formula_data_item(native: Any) -> dict[str, Any]:
    items = _normalize_formula_data_items(native)
    if items:
        return items[0]
    values = _unwrap_tdx_value(native)
    return {
        "symbol": None,
        "rows": _as_sequence(values),
        "provider": "tdx",
        "raw": values,
    }


def _normalize_formula_operation_result(native: Any) -> dict[str, Any]:
    values = _unwrap_tdx_value(native)
    if isinstance(values, dict):
        message = _first_native_value(values, "Result", "message", "Message")
        return {
            "ok": True,
            "message": str(message) if message is not None else "OK",
            "provider": "tdx",
            "raw": values,
        }
    if isinstance(values, bool):
        return {"ok": values, "message": "OK" if values else "FAILED", "provider": "tdx", "raw": values}
    return {"ok": True, "message": str(values), "provider": "tdx", "raw": values}


def _normalize_formula_metadata_item(item: Any) -> dict[str, Any]:
    native = item if isinstance(item, dict) else {"value": item}
    code = _first_native_value(native, "FormulaCode", "Code", "code")
    name = _first_native_value(native, "FormulaName", "Name", "name")
    formula_type = _first_native_value(native, "Type", "formulaType", "type")
    is_system = _first_native_value(native, "IsSystem", "isSystem")
    return {
        "code": str(code) if code is not None else "",
        "name": str(name) if name is not None else None,
        "type": _optional_int(formula_type),
        "isSystem": _optional_bool(is_system),
        "provider": "tdx",
        "raw": item,
    }


def _normalize_formula_info_item(native: Any) -> dict[str, Any]:
    values = _unwrap_tdx_value(native)
    item = values if isinstance(values, dict) else {"value": values}
    metadata = _normalize_formula_metadata_item(item)
    metadata["params"] = _as_sequence(_first_native_value(item, "Params", "params"))
    metadata["lines"] = _as_sequence(_first_native_value(item, "Lines", "lines"))
    return metadata


def _normalize_formula_execution_result(
    kind: str,
    formula_name: str,
    native: Any,
) -> dict[str, Any]:
    values = _unwrap_tdx_value(native)
    return {
        "kind": kind,
        "formulaName": formula_name,
        "values": values,
        "provider": "tdx",
        "raw": values,
    }


def _normalize_formula_batch_result(
    kind: str,
    formula_name: str,
    native: Any,
) -> dict[str, Any]:
    values = _unwrap_tdx_value(native)
    return {
        "kind": kind,
        "formulaName": formula_name,
        "items": _native_items(values),
        "provider": "tdx",
        "raw": values,
    }


def _formula_execution_method(kind: str) -> str:
    methods = {
        "zb": "formula_zb",
        "xg": "formula_xg",
        "exp": "formula_exp",
    }
    return methods[kind]


def _formula_batch_method(kind: str) -> str:
    methods = {
        "zb": "formula_process_mul_zb",
        "xg": "formula_process_mul_xg",
        "exp": "formula_process_mul_exp",
    }
    return methods[kind]


def _native_items(native: Any, *preferred_list_fields: str) -> list[Any]:
    values = _unwrap_tdx_value(native)
    if isinstance(values, list | tuple):
        return list(values)
    if isinstance(values, dict):
        for field_name in preferred_list_fields:
            field_value = _first_native_value(values, field_name)
            if isinstance(field_value, list | tuple):
                return list(field_value)
        return [values]
    if values is None:
        return []
    return [values]


def _native_item_for_symbol(native: Any, symbol: str) -> Any:
    values = _unwrap_tdx_value(native)
    candidates = {symbol, to_tdx_http_code(symbol), normalize_symbol(symbol), to_tdx_code(symbol)}
    if isinstance(values, dict):
        for key, value in values.items():
            if str(key).upper() in {candidate.upper() for candidate in candidates}:
                return value
        return values
    if isinstance(values, list | tuple):
        for item in values:
            if isinstance(item, dict):
                item_symbol = _first_native_value(item, "symbol", "code", "stock_code", "Code")
                if item_symbol and normalize_symbol(str(item_symbol)) == normalize_symbol(symbol):
                    return item
    return values


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _record_for_code(values: Any, code: str | None) -> Any:
    if code is None:
        return values if isinstance(values, dict) else {}
    if not isinstance(values, dict):
        return values

    candidates = _code_candidates(code)
    for key, value in values.items():
        if str(key).upper() in candidates:
            return value
    return values


def _lookup_symbol_field(values: Any, symbol: str, field_name: str) -> Any:
    if not isinstance(values, dict):
        return values

    symbol_record = _record_for_code(values, symbol)
    if isinstance(symbol_record, dict):
        direct_value = _first_native_value(symbol_record, field_name)
        if direct_value is not None:
            if symbol_record is values and isinstance(direct_value, dict):
                nested_value = _record_for_code(direct_value, symbol)
                if nested_value is not direct_value:
                    return nested_value
            return direct_value

    field_record = _first_native_value(values, field_name)
    if isinstance(field_record, dict):
        symbol_value = _record_for_code(field_record, symbol)
        if symbol_value is not field_record:
            return symbol_value

    if symbol_record is not values:
        return symbol_record
    return _first_native_value(values, field_name)


def _lookup_aggregate_value(values: Any, code: str | None, field_name: str) -> Any:
    if not isinstance(values, dict):
        return values
    if code is None:
        return _first_native_value(values, field_name)

    code_record = _record_for_code(values, code)
    if isinstance(code_record, dict):
        direct_value = _first_native_value(code_record, field_name)
        if direct_value is not None:
            return direct_value

    field_record = _first_native_value(values, field_name)
    if isinstance(field_record, dict):
        code_value = _record_for_code(field_record, code)
        if code_value is not field_record:
            return code_value
    return None


def _code_candidates(code: str) -> set[str]:
    return {
        str(code).upper(),
        normalize_symbol(str(code)).upper(),
        to_tdx_code(str(code)).upper(),
    }


def _metadata_value(record: Any, field_name: str) -> str | None:
    if not isinstance(record, dict):
        return None
    value = _first_native_value(record, field_name)
    return str(value) if value is not None else None


def _scalar_value(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_scalar_value(item) for item in value]
    if isinstance(value, dict):
        return value
    numeric_value = _optional_float(value)
    if numeric_value is not None:
        return numeric_value
    return value


def _aggregate_events(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        if not value:
            return []
        if any(isinstance(item, dict) for item in value):
            return list(value)
        return [value]
    return [value]


def _aggregate_event_parts(event: Any) -> tuple[Any | None, Any]:
    if isinstance(event, dict):
        date = _first_native_value(event, "Date", "date")
        raw_values = _first_native_value(event, "Value", "value", "values")
        if raw_values is None:
            raw_values = {
                key: value
                for key, value in event.items()
                if str(key).replace("_", "").lower() != "date"
            }
        return date, raw_values
    return None, event


def _normalize_aggregate_code(scope: str, code: str | None) -> str | None:
    if code is None:
        return None
    if scope == "stock":
        return normalize_symbol(code)
    return str(code)


def _numeric_values(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return [_scalar_value(item) for item in value]
    if isinstance(value, dict):
        return [_scalar_value(item) for item in value.values()]
    return [_scalar_value(value)]


def _first_native_value(native: dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        expected = field_name.replace("_", "").replace(" ", "").lower()
        for key, value in native.items():
            if str(key).replace("_", "").replace(" ", "").lower() == expected:
                return value
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None
