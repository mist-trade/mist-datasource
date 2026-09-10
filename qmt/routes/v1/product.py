import re
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from qmt.routes.v1.dependencies import (
    get_qmt_download_registry,
    get_qmt_gateway,
    get_qmt_provider,
)
from src.core.config import settings
from src.datasource.contracts import (
    BEIJING_TZ,
    DatasourceError,
    ResponseEnvelope,
    ResponseMeta,
    serialize_response_data,
)
from src.datasource.metrics import record_qmt_history_download
from src.datasource.qmt.history_download import QmtHistoryDownloadRegistry
from src.datasource.qmt.operations.market import QmtBridgeError
from src.datasource.qmt.provider import QmtDatasourceProvider
from src.datasource.qmt.realtime.gateway import QmtCommandGateway
from src.datasource.realtime.stall_detector import ActivityWindow

router = APIRouter()

_ACTIVITY_WINDOW = ActivityWindow()


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


def _get_download_registry(request: Request) -> QmtHistoryDownloadRegistry | None:
    return get_qmt_download_registry(request)


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


class QmtDownloadJobRequest(QmtV1Model):
    """Submit a history download job (QMT terminal local cache refresh).

    ``base_periods`` must be a subset of the stored base periods {1m,5m,1d}
    (other periods are synthesized from them). The job runs serially in the
    bridge; poll ``GET /v1/qmt/download/{job_id}`` for completion.
    """

    stock_list: list[str] = Field(min_length=1, max_length=64)
    base_periods: list[str] = Field(min_length=1, max_length=3)
    start_time: str = Field(pattern=r"^\d{8}(\d{6})?$")
    end_time: str = Field(pattern=r"^\d{8}(\d{6})?$")


BASE_PERIOD_ALLOWLIST = {"1m", "5m", "1d"}
_SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def _validate_download_request(payload: QmtDownloadJobRequest) -> str | None:
    if any(not _SYMBOL_RE.match(s.strip().upper()) for s in payload.stock_list):
        return "invalid_symbol_format"
    if any(p not in BASE_PERIOD_ALLOWLIST for p in payload.base_periods):
        return "invalid_base_period"
    if payload.start_time >= payload.end_time:
        return "invalid_time_range"
    return None


@router.post("/v1/qmt/download")
async def submit_qmt_download(payload: QmtDownloadJobRequest, request: Request):
    registry = _get_download_registry(request)
    gateway = _get_gateway(request)
    if registry is None or gateway is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=_provider_unavailable(),
            meta=_meta(),
        )
    if not settings.qmt.download_job_enabled:
        record_qmt_history_download("disabled")
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=DatasourceError(
                code="QMT_DOWNLOAD_DISABLED",
                message="QMT download job surface is disabled",
                retryable=True,
                details={},
            ),
            meta=_meta(),
        )
    if _ACTIVITY_WINDOW.in_window():
        record_qmt_history_download("in_session")
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=DatasourceError(
                code="QMT_DOWNLOAD_IN_SESSION",
                message="Download submissions are refused during trading hours",
                retryable=True,
                details={},
            ),
            meta=_meta(),
        )
    validation_error = _validate_download_request(payload)
    if validation_error is not None:
        record_qmt_history_download("invalid")
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=DatasourceError(
                code="QMT_DOWNLOAD_REQUEST_INVALID",
                message=f"Download request rejected: {validation_error}",
                retryable=True,
                details={"reason": validation_error},
            ),
            meta=_meta(),
        )

    job = registry.submit_download_job(
        stock_list=[s.strip().upper() for s in payload.stock_list],
        base_periods=list(payload.base_periods),
        start_time=payload.start_time,
        end_time=payload.end_time,
        timeout_seconds=settings.qmt.download_command_timeout_ms / 1000,
    )
    record_qmt_history_download("submitted")
    return _success(request, job)


@router.get("/v1/qmt/download/{job_id}")
async def qmt_download_status(job_id: str, request: Request):
    registry = _get_download_registry(request)
    status = registry.job_status(job_id) if registry else None
    if status is None:
        return ResponseEnvelope.failure(
            request_id=_request_id(request),
            provider="qmt",
            error=DatasourceError(
                code="QMT_DOWNLOAD_JOB_NOT_FOUND",
                message=f"Download job {job_id} not found or expired",
                retryable=False,
                details={"jobId": job_id},
            ),
            meta=_meta(),
        )
    return _success(request, status)
