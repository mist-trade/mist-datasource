from typing import Any

from fastapi import Request

from src.datasource.tdx.history_download import TdxHistoryDownloadRegistry


def get_tdx_provider(request: Request) -> Any:
    return getattr(request.app.state, "tdx_provider", None)


def get_tdx_download_registry(request: Request) -> TdxHistoryDownloadRegistry | None:
    registry = getattr(request.app.state, "tdx_download_registry", None)
    return registry if isinstance(registry, TdxHistoryDownloadRegistry) else None
