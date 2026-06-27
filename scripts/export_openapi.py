"""Export the TDX FastAPI OpenAPI contract and a readable route summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tdx.main import app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_PATH = ROOT / "docs" / "references" / "tdx-openapi.json"
DEFAULT_SUMMARY_PATH = ROOT / "docs" / "references" / "tdx-openapi-summary.md"


def _schema_name(schema: Any) -> str:
    if not isinstance(schema, dict):
        return ""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    if "items" in schema:
        item_name = _schema_name(schema["items"])
        return f"array[{item_name}]" if item_name else "array"
    if "anyOf" in schema:
        names = [_schema_name(item) for item in schema["anyOf"]]
        return " | ".join(name for name in names if name)
    schema_type = schema.get("type")
    return str(schema_type) if schema_type else json.dumps(schema, ensure_ascii=False, sort_keys=True)


def _request_body_schema(operation: dict[str, Any]) -> str:
    content = operation.get("requestBody", {}).get("content", {})
    json_content = content.get("application/json", {})
    return _schema_name(json_content.get("schema")) or "-"


def _response_schemas(operation: dict[str, Any]) -> list[str]:
    responses: list[str] = []
    for status_code, response in operation.get("responses", {}).items():
        content = response.get("content", {}) if isinstance(response, dict) else {}
        json_content = content.get("application/json", {})
        schema_name = _schema_name(json_content.get("schema")) or "-"
        responses.append(f"{status_code}: {schema_name}")
    return responses or ["-"]


def _parameters(operation: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        name = parameter.get("name", "-")
        location = parameter.get("in", "-")
        required = parameter.get("required", False)
        schema_name = _schema_name(parameter.get("schema", {})) or "-"
        rows.append(f"{name} ({location}, {schema_name}, required={str(required).lower()})")
    return rows or ["-"]


def build_summary(openapi: dict[str, Any]) -> str:
    lines = [
        "# TDX OpenAPI Summary",
        "",
        f"Title: {openapi.get('info', {}).get('title', '-')}",
        f"Version: {openapi.get('info', {}).get('version', '-')}",
        "",
        "Generated from `tdx.main:app.openapi()`.",
        "",
    ]

    for path in sorted(openapi.get("paths", {})):
        path_item = openapi["paths"][path]
        for method in sorted(path_item):
            operation = path_item[method]
            if not isinstance(operation, dict):
                continue
            method_upper = method.upper()
            lines.extend(
                [
                    f"## {method_upper} {path}",
                    "",
                    f"- Operation ID: `{operation.get('operationId', '-')}`",
                    f"- Tags: {', '.join(operation.get('tags', [])) or '-'}",
                    f"- Summary: {operation.get('summary', '-')}",
                    f"- Request Body: `{_request_body_schema(operation)}`",
                    f"- Parameters: {'; '.join(_parameters(operation))}",
                    f"- Responses: {'; '.join(_response_schemas(operation))}",
                    "",
                ]
            )

    schemas = sorted(openapi.get("components", {}).get("schemas", {}))
    lines.extend(
        [
            "## Schemas",
            "",
            *[f"- `{schema}`" for schema in schemas],
            "",
        ]
    )
    return "\n".join(lines)


def export_openapi(json_path: Path, summary_path: Path) -> None:
    openapi = app.openapi()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(openapi, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(build_summary(openapi), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    args = parser.parse_args()

    export_openapi(args.json, args.summary)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.summary}")


if __name__ == "__main__":
    main()
