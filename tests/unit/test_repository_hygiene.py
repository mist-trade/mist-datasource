"""Repository hygiene checks for local tooling metadata."""

from __future__ import annotations

import ast
from pathlib import Path


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
