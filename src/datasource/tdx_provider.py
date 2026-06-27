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
