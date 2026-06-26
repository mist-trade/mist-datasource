from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from src.datasource.contracts import BEIJING_TZ, DatasourceError, ResponseEnvelope, ResponseMeta
from src.datasource.tdx_http_client import TdxHttpError
from src.datasource.tdx_models import RawTdxCallRequest, TdxBarQueryRequest, TdxSnapshotQueryRequest

router = APIRouter()


class TdxV1Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class SectorQueryRequest(TdxV1Model):
    sector: str


class FormulaCallRequest(TdxV1Model):
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


def _success(request: Request, data: Any) -> ResponseEnvelope:
    return ResponseEnvelope.success(
        request_id=_request_id(request),
        provider="tdx",
        data=_dump(data),
        meta=_meta(),
    )


def _failure(request: Request, exc: Exception) -> ResponseEnvelope:
    return ResponseEnvelope.failure(
        request_id=_request_id(request),
        provider="tdx",
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


def _provider_unavailable() -> DatasourceError:
    return DatasourceError(
        code="TDX_PROVIDER_UNAVAILABLE",
        message="TDX datasource provider is not initialized",
        retryable=True,
        details={},
    )


async def _wrap(key: str, awaitable) -> dict[str, Any]:
    return {key: await awaitable}


async def _call_provider(request: Request, operation):
    provider = _get_provider()
    if provider is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="tdx",
            error=_provider_unavailable(),
            meta=_meta(),
        )

    try:
        return _success(request, await operation(provider))
    except TdxHttpError as exc:
        return _failure(request, exc)
    except Exception as exc:
        return _failure(request, exc)


@router.get("/providers")
async def providers(request: Request):
    provider = _get_provider()
    status = "available" if provider is not None else "unavailable"
    return _success(
        request,
        {
            "providers": [
                {
                    "id": "tdx",
                    "name": "TDX",
                    "status": status,
                }
            ]
        },
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
    )


@router.post("/v1/snapshots/query")
async def query_snapshots(payload: TdxSnapshotQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "snapshots",
            provider.get_snapshots(payload.symbols, fields=payload.fields),
        ),
    )


@router.post("/v1/raw/tdx/call")
async def raw_tdx_call(payload: RawTdxCallRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("result", provider.raw_call(payload.method, payload.params)),
    )


@router.post("/v1/sectors/query")
async def query_sectors(payload: SectorQueryRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap("symbols", provider.get_sector_members(payload.sector)),
    )


@router.post("/v1/formulas/call")
async def call_formula(payload: FormulaCallRequest, request: Request):
    return await _call_provider(
        request,
        lambda provider: _wrap(
            "result",
            provider.call_formula(payload.name, payload.args, payload.context),
        ),
    )
