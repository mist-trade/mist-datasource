from datetime import datetime
from typing import Any

from src.datasource.contracts import BEIJING_TZ, normalize_beijing_iso
from src.datasource.tdx_models import TdxBar, TdxSnapshot


def normalize_symbol(code: str) -> str:
    value = code.strip().upper()
    if len(value) >= 8 and value[:2] in {"SH", "SZ"}:
        return f"{value[2:]}.{value[:2]}"
    if "." in value:
        stock_code, market = value.split(".", 1)
        return f"{stock_code}.{market}"
    return value


def to_tdx_code(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if "." not in normalized:
        return normalized
    stock_code, market = normalized.split(".", 1)
    return f"{market}{stock_code}"


def to_tdx_http_code(symbol: str) -> str:
    return normalize_symbol(symbol)


def beijing_iso(value: str | datetime | None = None) -> str:
    if value is None:
        value = datetime.now(BEIJING_TZ)
    normalized = normalize_beijing_iso(value)
    if normalized is None:
        msg = "beijing_iso cannot normalize None after current time fallback"
        raise ValueError(msg)
    return normalized


def normalize_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def normalize_tdx_bar_rows(symbol: str, period: str, native: dict[str, Any]) -> list[TdxBar]:
    normalized_symbol = normalize_symbol(symbol)
    open_values = _series_for_symbol(native, "open", normalized_symbol)
    high_values = _series_for_symbol(native, "high", normalized_symbol)
    low_values = _series_for_symbol(native, "low", normalized_symbol)
    close_values = _series_for_symbol(native, "close", normalized_symbol)
    volume_values = _series_for_symbol(native, "volume", normalized_symbol)
    amount_values = _series_for_symbol(native, "amount", normalized_symbol)

    timestamps = sorted(
        set().union(
            open_values,
            high_values,
            low_values,
            close_values,
            volume_values,
            amount_values,
        )
    )

    return [
        TdxBar(
            symbol=normalized_symbol,
            period=period,
            barTime=beijing_iso(timestamp),
            open=normalize_number(open_values.get(timestamp)),
            high=normalize_number(high_values.get(timestamp)),
            low=normalize_number(low_values.get(timestamp)),
            close=normalize_number(close_values.get(timestamp)),
            volume=normalize_number(volume_values.get(timestamp)),
            amount=normalize_number(amount_values.get(timestamp)),
            provider="tdx",
            receivedAt=beijing_iso(),
        )
        for timestamp in timestamps
    ]


def normalize_tdx_snapshot(symbol: str, native: dict[str, Any]) -> TdxSnapshot:
    normalized_symbol = normalize_symbol(symbol)

    return TdxSnapshot(
        symbol=normalized_symbol,
        last=normalize_number(_get_native_value(native, "now")),
        open=normalize_number(_get_native_value(native, "open")),
        high=normalize_number(_get_native_value(native, "max")),
        low=normalize_number(_get_native_value(native, "min")),
        lastClose=normalize_number(_get_native_value(native, "lastclose")),
        volume=normalize_number(_get_native_value(native, "volume")),
        amount=normalize_number(_get_native_value(native, "amount")),
        provider="tdx",
        asOf=beijing_iso(_get_native_value(native, "asof")),
    )


def _series_for_symbol(
    native: dict[str, Any],
    field_name: str,
    normalized_symbol: str,
) -> dict[str, Any]:
    field_map = _get_native_value(native, field_name)

    candidate_keys = (
        to_tdx_code(normalized_symbol),
        normalized_symbol,
        normalized_symbol.lower(),
        to_tdx_code(normalized_symbol).lower(),
    )

    if _looks_like_dataframe(field_map):
        return _dataframe_row_for_symbol(field_map, candidate_keys)

    if not isinstance(field_map, dict):
        return {}

    for key in candidate_keys:
        values = field_map.get(key)
        if isinstance(values, dict):
            return values

    return {}


def _looks_like_dataframe(value: Any) -> bool:
    return all(hasattr(value, attr) for attr in ("loc", "index", "columns"))


def _dataframe_row_for_symbol(field_value: Any, candidate_keys: tuple[str, ...]) -> dict[str, Any]:
    index_values = {str(index_value) for index_value in field_value.index}
    for key in candidate_keys:
        if key not in index_values:
            continue
        row = field_value.loc[key]
        if hasattr(row, "to_dict"):
            return row.to_dict()
        return dict(row)
    return {}


def _get_native_value(native: dict[str, Any], field_name: str) -> Any:
    expected = _native_key_token(field_name)
    for key, value in native.items():
        if _native_key_token(key) == expected:
            return value
    return None


def _native_key_token(value: str) -> str:
    return value.replace("_", "").replace(" ", "").lower()
