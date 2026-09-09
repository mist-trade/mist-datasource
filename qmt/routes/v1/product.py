from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from qmt.routes.v1.dependencies import get_qmt_gateway, get_qmt_provider
from src.datasource.contracts import (
    BEIJING_TZ,
    DatasourceError,
    ResponseEnvelope,
    ResponseMeta,
    serialize_response_data,
)
from src.datasource.metrics import record_admin_call
from src.datasource.qmt.operations.market import QmtBridgeError
from src.datasource.qmt.provider import QmtDatasourceProvider
from src.datasource.qmt.realtime.gateway import QmtCommandGateway

router = APIRouter()


class QmtV1Model(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


class QmtBarQueryRequest(QmtV1Model):
    fields: list[str] = Field(default_factory=list)
    stock_list: list[str]
    period: str = "1d"
    start_time: str = ""
    end_time: str = ""
    count: int = -1
    dividend_type: str = "none"
    fill_data: bool = False
    include_raw: bool = False


def _get_provider(request: Request) -> QmtDatasourceProvider | None:
    return get_qmt_provider(request)


def _get_gateway(request: Request) -> QmtCommandGateway | None:
    return get_qmt_gateway(request)


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid4())


def _meta() -> ResponseMeta:
    return ResponseMeta(transport="http", asOf=datetime.now(BEIJING_TZ).isoformat())


def _success(request: Request, data: Any) -> ResponseEnvelope:
    return ResponseEnvelope.success(
        request_id=_request_id(request),
        provider="qmt",
        data=serialize_response_data(data),
        meta=_meta(),
    )


def _failure(request: Request, exc: Exception) -> ResponseEnvelope:
    return ResponseEnvelope.failure(
        request_id=_request_id(request),
        provider="qmt",
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
        error_details = cast(dict[str, Any], details) if isinstance(details, dict) else {}
        return DatasourceError(
            code=str(code),
            message=str(message),
            retryable=bool(retryable),
            details=error_details,
        )

    return DatasourceError(
        code="QMT_PROVIDER_ERROR",
        message=str(exc),
        retryable=False,
        details={"exception": type(exc).__name__},
    )


def _provider_unavailable() -> DatasourceError:
    return DatasourceError(
        code="QMT_PROVIDER_UNAVAILABLE",
        message="QMT datasource provider is not initialized",
        retryable=True,
        details={},
    )


@router.post("/v1/bars/query")
async def query_bars(payload: QmtBarQueryRequest, request: Request):
    provider = _get_provider(request)
    if provider is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=_provider_unavailable(),
            meta=_meta(),
        )

    try:
        result = await provider.get_bars(
            stock_list=payload.stock_list,
            period=payload.period,
            start_time=payload.start_time,
            end_time=payload.end_time,
            count=payload.count,
            fields=payload.fields,
            dividend_type=payload.dividend_type,
            fill_data=payload.fill_data,
            include_raw=payload.include_raw,
            command_gateway=_get_gateway(request),
        )
    except QmtBridgeError as exc:
        return _failure(request, exc)
    return _success(request, result)


class QmtAdminCallRequest(QmtV1Model):
    """Admin escape hatch: execute a classified ContextInfo method.

    ``params`` is forwarded to the native method as keyword arguments. The
    classification guard (unclassified / trading-account deny families) is
    enforced in ``QmtDatasourceProvider.admin_call_native`` plus an in-bridge
    trading hard-deny (bridge v3.1).
    """

    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=600000, ge=1, le=1800000)


def _admin_result_from_error(exc: QmtBridgeError) -> str:
    if exc.code == "QMT_METHOD_UNCLASSIFIED":
        return "denied_unclassified"
    if exc.code == "QMT_METHOD_FAMILY_FORBIDDEN":
        return "denied_forbidden"
    if exc.code == "QMT_ADMIN_CALL_TIMEOUT":
        return "timeout"
    return "failed"


def _bounded_admin_method(method: str) -> str:
    normalized = (method or "").strip().lower()
    if not normalized:
        return "unclassified"
    return normalized[:64]


@router.post("/v1/raw/qmt/call")
async def raw_qmt_call(payload: QmtAdminCallRequest, request: Request):
    provider = _get_provider(request)
    gateway = _get_gateway(request)
    if provider is None or gateway is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=_provider_unavailable(),
            meta=_meta(),
        )

    try:
        result = await provider.admin_call_native(
            payload.method,
            payload.params,
            command_gateway=gateway,
            timeout_seconds=payload.timeout_ms / 1000,
        )
    except QmtBridgeError as exc:
        record_admin_call("qmt", _bounded_admin_method(payload.method), _admin_result_from_error(exc))
        return _failure(request, exc)
    record_admin_call("qmt", _bounded_admin_method(payload.method), "ok")
    return _success(request, result)
