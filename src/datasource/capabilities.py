from typing import Literal

from pydantic import Field

from src.datasource.contracts import DatasourceModel

CapabilityStatus = Literal["supported", "planned", "unsupported"]


class ProviderCapabilityUnsupported(Exception):
    def __init__(
        self,
        *,
        provider: str,
        family: str,
        operation: str,
        fallback: str,
    ) -> None:
        super().__init__(f"{provider} does not support {family}:{operation}")
        self.code = "PROVIDER_CAPABILITY_UNSUPPORTED"
        self.message = f"Provider '{provider}' does not support capability '{family}'"
        self.retryable = False
        self.details = {
            "provider": provider,
            "family": family,
            "operation": operation,
            "fallback": fallback,
        }


class ProviderCapability(DatasourceModel):
    family: str
    status: CapabilityStatus
    stability: str
    provider_methods: list[str] = Field(default_factory=list, alias="providerMethods")
    unsupported_reason: str | None = Field(default=None, alias="unsupportedReason")


class ProviderManifest(DatasourceModel):
    id: str
    name: str
    status: str
    capabilities: list[ProviderCapability]


TDX_CAPABILITY_STATUSES: dict[str, tuple[CapabilityStatus, str, list[str], str | None]] = {
    "bars": ("supported", "stable", ["get_market_data"], None),
    "snapshots": ("supported", "stable", ["get_market_snapshot"], None),
    "price-volume": ("supported", "stable", ["get_pricevol"], None),
    "benchmarks": ("planned", "planned", ["get_benchmark_data"], None),
    "calendar": ("supported", "stable", ["get_trading_dates"], None),
    "securities": ("supported", "stable", ["get_stock_list"], None),
    "security-info": ("supported", "stable", ["get_stock_info", "get_more_info"], None),
    "security-search": ("planned", "planned", ["get_match_stkinfo"], None),
    "security-relations": ("supported", "stable", ["get_relation"], None),
    "sector-list": ("supported", "stable", ["get_sector_list"], None),
    "sector-members": ("supported", "stable", ["get_stock_list_in_sector"], None),
    "ipo-info": ("supported", "stable", ["get_ipo_info"], None),
    "share-capital": (
        "supported",
        "stable",
        ["get_gb_info", "get_gb_info_by_date"],
        None,
    ),
    "dividend-factors": ("supported", "stable", ["get_divid_factors"], None),
    "convertible-bonds": ("supported", "stable", ["get_kzz_info", "get_cb_info"], None),
    "etf-info": ("supported", "stable", ["get_trackzs_etf_info"], None),
    "reference-data": (
        "planned",
        "planned",
        ["get_relation", "get_ipo_info", "get_gb_info", "get_gb_info_by_date"],
        None,
    ),
    "instrument-data": (
        "planned",
        "planned",
        ["get_kzz_info", "get_cb_info", "get_trackzs_etf_info", "get_divid_factors"],
        None,
    ),
    "finance-report": (
        "supported",
        "stable",
        [
            "get_financial_data",
            "get_financial_data_by_date",
            "get_gp_one_data",
            "get_gpjy_value",
            "get_bkjy_value",
            "get_scjy_value",
        ],
        None,
    ),
    "financial-data": (
        "supported",
        "stable",
        ["get_financial_data", "get_financial_data_by_date"],
        None,
    ),
    "single-finance-value": ("supported", "stable", ["get_gp_one_data"], None),
    "stock-trade-aggregate": (
        "supported",
        "stable",
        ["get_gpjy_value", "get_gpjy_value_by_date"],
        None,
    ),
    "sector-trade-aggregate": (
        "supported",
        "stable",
        ["get_bkjy_value", "get_bkjy_value_by_date"],
        None,
    ),
    "market-trade-aggregate": (
        "supported",
        "stable",
        ["get_scjy_value", "get_scjy_value_by_date"],
        None,
    ),
    "formulas": (
        "supported",
        "operator",
        ["formula_zb", "formula_xg", "formula_exp", "formula_process_mul_xg"],
        None,
    ),
    "formula-data": (
        "supported",
        "operator",
        [
            "formula_format_data",
            "formula_set_data",
            "formula_set_data_info",
            "formula_get_data",
        ],
        None,
    ),
    "formula-metadata": (
        "supported",
        "operator",
        ["formula_get_all", "formula_get_info"],
        None,
    ),
    "formula-execution": (
        "supported",
        "operator",
        ["formula_zb", "formula_xg", "formula_exp"],
        None,
    ),
    "formula-batch-execution": (
        "supported",
        "operator",
        ["formula_process_mul_zb", "formula_process_mul_xg", "formula_process_mul_exp"],
        None,
    ),
    "raw-diagnostics": ("supported", "stable", ["raw_call"], None),
    "websocket-subscriptions": (
        "supported",
        "stable",
        ["subscribe_hq", "unsubscribe_hq", "get_subscribe_hq_stock_list"],
        None,
    ),
}

QMT_CAPABILITY_STATUSES: dict[str, tuple[CapabilityStatus, str, list[str], str | None]] = {
    "bars": ("planned", "planned", ["get_market_data"], None),
    "snapshots": ("planned", "planned", ["get_full_tick"], None),
    "price-volume": ("unsupported", "planned", [], "QMT price-volume mapping is not verified"),
    "benchmarks": ("unsupported", "planned", [], "QMT benchmark mapping is not verified"),
    "calendar": ("planned", "planned", ["get_trading_dates"], None),
    "securities": ("planned", "planned", ["get_stock_list"], None),
    "security-info": (
        "planned",
        "planned",
        ["get_instrument_detail", "get_instrument_type"],
        None,
    ),
    "security-search": ("unsupported", "planned", [], "QMT security search mapping is not verified"),
    "security-relations": ("unsupported", "planned", [], "QMT security relation mapping is not verified"),
    "sector-list": ("planned", "planned", ["get_sector_list"], None),
    "sector-members": ("planned", "planned", ["get_stock_list_in_sector"], None),
    "ipo-info": ("unsupported", "planned", [], "QMT IPO mapping is not verified"),
    "share-capital": ("unsupported", "planned", [], "QMT share-capital mapping is not verified"),
    "dividend-factors": ("unsupported", "planned", [], "QMT dividend-factor mapping is not verified"),
    "convertible-bonds": ("unsupported", "planned", [], "QMT convertible-bond mapping is not verified"),
    "etf-info": ("unsupported", "planned", [], "QMT ETF mapping is not verified"),
    "reference-data": ("unsupported", "planned", [], "QMT reference-data mapping is not verified"),
    "instrument-data": ("unsupported", "planned", [], "QMT instrument-data mapping is not verified"),
    "finance-report": ("unsupported", "planned", [], "QMT finance/report mapping is not verified"),
    "financial-data": ("unsupported", "planned", [], "QMT financial-data mapping is not verified"),
    "single-finance-value": (
        "unsupported",
        "planned",
        [],
        "QMT single finance value mapping is not verified",
    ),
    "stock-trade-aggregate": (
        "unsupported",
        "planned",
        [],
        "QMT stock trade aggregate mapping is not verified",
    ),
    "sector-trade-aggregate": (
        "unsupported",
        "planned",
        [],
        "QMT sector trade aggregate mapping is not verified",
    ),
    "market-trade-aggregate": (
        "unsupported",
        "planned",
        [],
        "QMT market trade aggregate mapping is not verified",
    ),
    "formulas": ("unsupported", "planned", [], "QMT formula integration is not implemented"),
    "formula-data": ("unsupported", "planned", [], "QMT formula data mapping is not verified"),
    "formula-metadata": (
        "unsupported",
        "planned",
        [],
        "QMT formula metadata mapping is not verified",
    ),
    "formula-execution": (
        "unsupported",
        "planned",
        [],
        "QMT formula execution mapping is not verified",
    ),
    "formula-batch-execution": (
        "unsupported",
        "planned",
        [],
        "QMT formula batch execution mapping is not verified",
    ),
    "raw-diagnostics": ("unsupported", "planned", [], "Raw TDX diagnostics are TDX-only"),
    "websocket-subscriptions": (
        "planned",
        "planned",
        [],
        "QMT subscription bridge is not implemented",
    ),
}


def build_provider_manifests(*, tdx_status: str) -> list[ProviderManifest]:
    return [
        ProviderManifest(
            id="tdx",
            name="TDX",
            status=tdx_status,
            capabilities=_capabilities_from_statuses(TDX_CAPABILITY_STATUSES),
        ),
        ProviderManifest(
            id="qmt",
            name="QMT",
            status="disabled",
            capabilities=_capabilities_from_statuses(QMT_CAPABILITY_STATUSES),
        ),
    ]


def _capabilities_from_statuses(
    statuses: dict[str, tuple[CapabilityStatus, str, list[str], str | None]],
) -> list[ProviderCapability]:
    return [
        ProviderCapability(
            family=family,
            status=status,
            stability=stability,
            providerMethods=provider_methods,
            unsupportedReason=unsupported_reason,
        )
        for family, (
            status,
            stability,
            provider_methods,
            unsupported_reason,
        ) in statuses.items()
    ]
