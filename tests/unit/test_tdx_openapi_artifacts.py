import json
from pathlib import Path

from tdx.main import app

ROOT = Path(__file__).resolve().parents[2]
OPENAPI_JSON = ROOT / "docs" / "references" / "tdx-openapi.json"
OPENAPI_SUMMARY = ROOT / "docs" / "references" / "tdx-openapi-summary.md"


def test_tdx_openapi_json_matches_fastapi_schema() -> None:
    exported = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    current = app.openapi()

    assert exported["openapi"] == current["openapi"]
    assert exported["info"] == current["info"]
    assert exported["paths"] == current["paths"]
    assert exported["components"]["schemas"] == current["components"]["schemas"]
    assert "/v1/finance/financial-data/query" in exported["paths"]
    assert "/v1/reports/data/query" not in exported["paths"]


def test_tdx_openapi_summary_documents_contract_shapes() -> None:
    summary = OPENAPI_SUMMARY.read_text(encoding="utf-8")

    assert "# TDX OpenAPI Summary" in summary
    assert "POST /v1/finance/financial-data/query" in summary
    assert "Request Body" in summary
    assert "Responses" in summary
    assert "TdxFinancialDataQueryRequest" in summary
    assert "/v1/reports/data/query" not in summary
