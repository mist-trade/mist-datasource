from src.datasource.capabilities import ProviderCapabilityUnsupported
from src.datasource.contracts import DatasourceError, ResponseEnvelope, ResponseMeta
from src.datasource.tdx_models import TdxBarQueryRequest, TdxWsMessage


def test_success_envelope_has_stable_shape():
    envelope = ResponseEnvelope.success(
        request_id="req_test",
        provider="tdx",
        data={"items": []},
        meta=ResponseMeta(
            sourceLatencyMs=12,
            transport="http",
            asOf="2026-06-26T10:00:03+08:00",
        ),
    )

    payload = envelope.model_dump()

    assert payload["ok"] is True
    assert payload["requestId"] == "req_test"
    assert payload["provider"] == "tdx"
    assert payload["data"] == {"items": []}
    assert payload["error"] is None
    assert payload["meta"]["transport"] == "http"


def test_response_meta_normalizes_naive_as_of_to_beijing_iso():
    meta = ResponseMeta(
        sourceLatencyMs=1,
        transport="http",
        asOf="2026-06-26T10:00:03",
    )

    assert meta.model_dump()["asOf"] == "2026-06-26T10:00:03+08:00"


def test_error_envelope_has_stable_error_code():
    envelope = ResponseEnvelope.failure(
        request_id="req_test",
        provider="tdx",
        error=DatasourceError(
            code="TDX_HTTP_UNAVAILABLE",
            message="TDX HTTP endpoint is unavailable",
            retryable=True,
            details={"url": "http://127.0.0.1:17709/"},
        ),
    )

    payload = envelope.model_dump()

    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "TDX_HTTP_UNAVAILABLE"
    assert payload["error"]["retryable"] is True


def test_tdx_requests_and_ws_messages_use_camel_case_aliases():
    request = TdxBarQueryRequest(
        symbols=["600519.SH"],
        period="1m",
        startTime="2026-06-26T09:30:00+08:00",
        endTime="2026-06-26T10:00:00+08:00",
        count=10,
        includeRaw=True,
    )
    message = TdxWsMessage(
        type="bar",
        requestId="req_test",
        eventId="evt_test",
        provider="tdx",
        data={"symbol": "600519.SH"},
    )

    request_payload = request.model_dump()
    message_payload = message.model_dump()

    assert request_payload["startTime"] == "2026-06-26T09:30:00+08:00"
    assert request_payload["endTime"] == "2026-06-26T10:00:00+08:00"
    assert request_payload["includeRaw"] is True
    assert message_payload["requestId"] == "req_test"
    assert message_payload["eventId"] == "evt_test"


def test_tdx_ws_message_uses_structured_meta_and_error_models():
    message = TdxWsMessage.model_validate(
        {
            "type": "error",
            "error": {"code": "X", "message": "bad", "retryable": True, "details": {}},
            "meta": {"transport": "ws", "asOf": "2026-06-26T10:00:00"},
        }
    )

    payload = message.model_dump()

    assert isinstance(message.error, DatasourceError)
    assert isinstance(message.meta, ResponseMeta)
    assert payload["error"]["code"] == "X"
    assert payload["meta"]["asOf"] == "2026-06-26T10:00:00+08:00"


def test_provider_capability_unsupported_has_stable_error_shape():
    error = ProviderCapabilityUnsupported(
        provider="qmt",
        family="formulas",
        operation="formula_zb",
        fallback="Use TDX provider or wait for QMT formula support.",
    )

    assert error.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
    assert error.retryable is False
    assert error.details == {
        "provider": "qmt",
        "family": "formulas",
        "operation": "formula_zb",
        "fallback": "Use TDX provider or wait for QMT formula support.",
    }
