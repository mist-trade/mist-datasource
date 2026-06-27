from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from src.datasource.capabilities import ProviderCapabilityUnsupported, build_provider_manifests
from src.datasource.contracts import BEIJING_TZ, DatasourceError, ResponseEnvelope, ResponseMeta
from src.datasource.tdx_http_client import TdxHttpError
from src.datasource.tdx_models import (
    RawTdxCallRequest,
    TdxBarQueryRequest,
    TdxConvertibleBondInfoQueryRequest,
    TdxDividendFactorsQueryRequest,
    TdxIpoInfoQueryRequest,
    TdxPriceVolumeQueryRequest,
    TdxSectorListQueryRequest,
    TdxSecuritiesQueryRequest,
    TdxSecurityInfoQueryRequest,
    TdxSecurityRelationsQueryRequest,
    TdxShareCapitalQueryRequest,
    TdxSnapshotQueryRequest,
    TdxTrackingEtfsQueryRequest,
    TdxTradingDatesQueryRequest,
)

router = APIRouter()


class TdxV1Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class SectorQueryRequest(TdxV1Model):
    provider: Literal["tdx", "qmt"] = "tdx"
    sector: str


class FormulaCallRequest(TdxV1Model):
    provider: Literal["tdx", "qmt"] = "tdx"
    name: str
    args: dict[str, Any] | list[Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)


def _get_provider() -> Any:
    import tdx.main

    return tdx.main.tdx_provider


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid4())


def _meta() -> ResponseMeta:
    return ResponseMeta(transport="http", asOf=datetime.now(BEIJING_TZ))


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


def _success(request: Request, data: Any, *, provider: str = "tdx") -> ResponseEnvelope:
    return ResponseEnvelope.success(
        request_id=_request_id(request),
        provider=provider,
        data=_dump(data),
        meta=_meta(),
    )


def _failure(request: Request, exc: Exception, *, provider: str = "tdx") -> ResponseEnvelope:
    return ResponseEnvelope.failure(
        request_id=_request_id(request),
        provider=provider,
        error=_to_datasource_error(exc),
        meta=_meta(),
    )


def _to_datasource_error(exc: Exception) -> DatasourceError:
    if isinstance(exc, DatasourceError):
        return exc

    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    retryable = getattr(exc, "retryable", None)
    details = getattr(exc, "details", None)
    if code and message is not None and retryable is not None:
        return DatasourceError(
            code=str(code),
            message=str(message),
            retryable=bool(retryable),
            details=details if isinstance(details, dict) else {},
        )

    return DatasourceError(
        code="TDX_PROVIDER_ERROR",
        message=str(exc),
        retryable=False,
        details={"exception": type(exc).__name__},
    )


def _provider_unavailable(provider: str) -> DatasourceError:
    return DatasourceError(
        code=f"{provider.upper()}_PROVIDER_UNAVAILABLE",
        message=f"{provider.upper()} datasource provider is not initialized",
        retryable=True,
        details={},
    )


async def _wrap(key: str, awaitable) -> dict[str, Any]:
    return {key: await awaitable}


async def _call_provider(
    request: Request,
    operation,
    *,
    provider_id: str = "tdx",
    capability_family: str,
    operation_name: str,
):
    if provider_id != "tdx":
        return _failure(
            request,
            ProviderCapabilityUnsupported(
                provider=provider_id,
                family=capability_family,
                operation=operation_name,
                fallback="Use provider 'tdx' for this endpoint until QMT support is implemented.",
            ),
            provider=provider_id,
        )

    provider = _get_provider()
    if provider is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider=provider_id,
            error=_provider_unavailable(provider_id),
            meta=_meta(),
        )

    try:
        return _success(request, await operation(provider), provider=provider_id)
    except TdxHttpError as exc:
        return _failure(request, exc, provider=provider_id)
    except Exception as exc:
        return _failure(request, exc, provider=provider_id)


@router.get("/providers")
async def providers(request: Request):
    provider = _get_provider()
    status = "available" if provider is not None else "unavailable"
    return _success(
        request,
        {"providers": build_provider_manifests(tdx_status=status)},
    )


@router.post("/v1/bars/query")
async def query_bars(payload: TdxBarQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "bars",
            provider.get_bars(
                payload.symbols,
                period=payload.period,
                start_time=payload.start_time,
                end_time=payload.end_time,
                count=payload.count,
            ),
        ),
        provider_id=payload.provider,
        capability_family="bars",
        operation_name="bars/query",
    )


@router.post("/v1/snapshots/query")
async def query_snapshots(payload: TdxSnapshotQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "snapshots",
            provider.get_snapshots(payload.symbols, fields=payload.fields),
        ),
        provider_id=payload.provider,
        capability_family="snapshots",
        operation_name="snapshots/query",
    )


@router.post("/v1/price-volume/query")
async def query_price_volume(payload: TdxPriceVolumeQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "items",
            provider.get_price_volume(payload.symbols, fields=payload.fields),
        ),
        provider_id=payload.provider,
        capability_family="price-volume",
        operation_name="price-volume/query",
    )


@router.post("/v1/calendar/trading-dates/query")
async def query_trading_dates(payload: TdxTradingDatesQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "tradingDates",
            provider.get_trading_dates(
                payload.market,
                start_time=payload.start_time,
                end_time=payload.end_time,
                count=payload.count,
            ),
        ),
        provider_id=payload.provider,
        capability_family="calendar",
        operation_name="trading-dates/query",
    )


@router.post("/v1/securities/query")
async def query_securities(payload: TdxSecuritiesQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("securities", provider.get_securities(payload.market)),
        provider_id=payload.provider,
        capability_family="securities",
        operation_name="securities/query",
    )


@router.post("/v1/securities/info/query")
async def query_security_info(payload: TdxSecurityInfoQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("securities", provider.get_security_info(payload.symbols)),
        provider_id=payload.provider,
        capability_family="security-info",
        operation_name="securities/info/query",
    )


@router.post("/v1/raw/tdx/call")
async def raw_tdx_call(payload: RawTdxCallRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("result", provider.raw_call(payload.method, payload.params)),
        capability_family="raw-diagnostics",
        operation_name="raw/tdx/call",
    )


@router.post("/v1/sectors/query")
async def query_sectors(payload: SectorQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("symbols", provider.get_sector_members(payload.sector)),
        provider_id=payload.provider,
        capability_family="sector-members",
        operation_name="sectors/query",
    )


@router.post("/v1/sectors/list/query")
async def query_sector_list(payload: TdxSectorListQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("sectors", provider.get_sector_list(payload.list_type)),
        provider_id=payload.provider,
        capability_family="sector-list",
        operation_name="sectors/list/query",
    )


@router.post("/v1/reference/relations/query")
async def query_security_relations(payload: TdxSecurityRelationsQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("relations", provider.get_security_relations(payload.symbol)),
        provider_id=payload.provider,
        capability_family="security-relations",
        operation_name="reference/relations/query",
    )


@router.post("/v1/reference/ipo/query")
async def query_ipo_info(payload: TdxIpoInfoQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("items", provider.get_ipo_info(payload.ipo_type, payload.ipo_date)),
        provider_id=payload.provider,
        capability_family="ipo-info",
        operation_name="reference/ipo/query",
    )


@router.post("/v1/reference/share-capital/query")
async def query_share_capital(payload: TdxShareCapitalQueryRequest, request: Request):
    async def operation(provider):
        if payload.start_date or payload.end_date:
            return await _wrap(
                "items",
                provider.get_share_capital_by_date(
                    payload.symbol,
                    payload.start_date or "",
                    payload.end_date or "",
                ),
            )
        return await _wrap(
            "items",
            provider.get_share_capital(payload.symbol, payload.date_list, payload.count),
        )

    return await _call_provider(
        request,
        operation,
        provider_id=payload.provider,
        capability_family="share-capital",
        operation_name="reference/share-capital/query",
    )


@router.post("/v1/reference/dividend-factors/query")
async def query_dividend_factors(payload: TdxDividendFactorsQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "items",
            provider.get_dividend_factors(
                payload.symbol,
                payload.start_time,
                payload.end_time,
            ),
        ),
        provider_id=payload.provider,
        capability_family="dividend-factors",
        operation_name="reference/dividend-factors/query",
    )


@router.post("/v1/instruments/convertible-bonds/query")
async def query_convertible_bonds(
    payload: TdxConvertibleBondInfoQueryRequest,
    request: Request,
):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "items",
            provider.get_convertible_bond_info(
                payload.symbol,
                fields=payload.fields,
                native_method=payload.native_method,
            ),
        ),
        provider_id=payload.provider,
        capability_family="convertible-bonds",
        operation_name="instruments/convertible-bonds/query",
    )


@router.post("/v1/instruments/tracking-etfs/query")
async def query_tracking_etfs(payload: TdxTrackingEtfsQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("items", provider.get_tracking_etfs(payload.index_symbol)),
        provider_id=payload.provider,
        capability_family="etf-info",
        operation_name="instruments/tracking-etfs/query",
    )


@router.post("/v1/formulas/call")
async def call_formula(payload: FormulaCallRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "result",
            provider.call_formula(payload.name, payload.args, payload.context),
        ),
        provider_id=payload.provider,
        capability_family="formulas",
        operation_name="formulas/call",
    )
