"""Repository hygiene checks for local tooling metadata."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

from src.adapter.qmt.client import QMTAdapter
from src.adapter.tdx.client import TDXAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_excludes_local_tool_caches() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    ignored_entries = {
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert ".uv-cache/" in ignored_entries
    assert ".ruff_cache/" in ignored_entries


def test_conftest_does_not_define_custom_event_loop_fixture() -> None:
    conftest = PROJECT_ROOT / "tests" / "conftest.py"
    tree = ast.parse(conftest.read_text(encoding="utf-8"), filename=str(conftest))
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    assert "event_loop" not in function_names


def test_tdx_routes_do_not_import_tdx_main_for_runtime_singletons() -> None:
    route_files = [
        PROJECT_ROOT / "tdx" / "routes" / filename
        for filename in (
            "client.py",
            "etf.py",
            "financial.py",
            "market.py",
            "sector.py",
            "stock.py",
            "v1.py",
            "value.py",
            "ws.py",
        )
    ]

    offenders: list[str] = []
    for route_file in route_files:
        tree = ast.parse(route_file.read_text(encoding="utf-8"), filename=str(route_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "tdx.main" for alias in node.names
            ):
                offenders.append(str(route_file.relative_to(PROJECT_ROOT)))
            if isinstance(node, ast.ImportFrom) and node.module == "tdx.main":
                offenders.append(str(route_file.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_tdx_routes_document_app_state_dependency_model() -> None:
    docs = (PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "app.state" in docs
    assert "import tdx.main" not in docs


def test_tdx_provider_uses_shared_native_key_normalization_and_configured_timeouts() -> None:
    provider_source = (PROJECT_ROOT / "src" / "datasource" / "tdx_provider.py").read_text(
        encoding="utf-8"
    )

    assert '.replace("_", "").replace(" ", "").lower()' not in provider_source
    assert "timeout_ms: int = 10000" not in provider_source
    assert 'payload.get("timeoutMs", 10000)' not in provider_source
    assert "settings.tdx.formula_timeout_ms" in provider_source


def _assert_selected_adapter_methods_are_typed(adapter_cls: type, required_methods: tuple[str, ...]) -> None:
    for method_name in required_methods:
        signature = inspect.signature(getattr(adapter_cls, method_name))
        assert signature.return_annotation is not inspect.Signature.empty, method_name
        assert signature.return_annotation is not Any, method_name
        assert signature.return_annotation not in {dict, list}, method_name
        for parameter_name, parameter in signature.parameters.items():
            if parameter_name == "self":
                continue
            assert parameter.annotation is not inspect.Signature.empty, (
                method_name,
                parameter_name,
            )


def test_tdx_adapter_selected_provider_methods_are_typed() -> None:
    _assert_selected_adapter_methods_are_typed(
        TDXAdapter,
        (
            "subscribe_quote",
            "get_market_snapshot",
            "get_gb_info",
            "get_sector_list",
            "get_kzz_info",
            "get_ipo_info",
            "get_trackzs_etf_info",
            "formula_format_data",
        ),
    )


def test_qmt_adapter_selected_provider_methods_are_typed() -> None:
    _assert_selected_adapter_methods_are_typed(
        QMTAdapter,
        (
            "subscribe_quote",
            "get_local_data",
            "get_full_kline",
            "get_divid_factors",
            "get_trading_dates",
        "get_financial_data",
        "get_sector_list",
            "get_cb_info",
            "get_ipo_info",
            "get_etf_info",
        ),
    )
