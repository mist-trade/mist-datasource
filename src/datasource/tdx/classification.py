"""TDX tqcenter method classification map (admin-surface governance source).

治理源：docs/references/tdxquant-interface-coverage.md（2026-06-27 评审，
2026-09-09 移植为 checked-in 映射）。更新流程：先改 coverage 文档 → 再改本映射
（两步、可 review）。未收录的方法 = unclassified = admin 面一律拒绝。
"""

from src.datasource.admin.guard import AdminGuard, AdminGuardResult

# family 枚举（coverage "Endpoint family" 归组）：
#   market / calendar / reference / finance / formula /
#   realtime_internal / admin / sector_admin / trading / account
TDX_CLASSIFICATION: dict[str, str] = {
    # Phase 1: Core Market, Calendar, Sector, Security
    "get_market_data": "market",
    "get_market_snapshot": "realtime_internal",  # builtin realtime bridge 专用
    "get_pricevol": "market",
    "get_benchmark_data": "market",
    "get_trading_dates": "calendar",
    "get_stock_list": "reference",
    "get_valid_stock_codes": "reference",
    "get_stock_info": "reference",
    "get_more_info": "reference",
    "get_match_stkinfo": "reference",
    "get_sector_list": "reference",
    "get_stock_list_in_sector": "reference",
    # Phase 2: Reference And Instrument Data
    "get_relation": "reference",
    "get_ipo_info": "reference",
    "get_gb_info": "reference",
    "get_gb_info_by_date": "reference",
    "get_divid_factors": "reference",
    "get_kzz_info": "reference",
    "get_cb_info": "reference",
    "get_trackzs_etf_info": "reference",
    # Phase 3: Finance And Report Data
    "get_financial_data": "finance",
    "get_financial_data_by_date": "finance",
    "get_gp_one_data": "finance",
    "get_gpjy_value": "finance",
    "get_gpjy_value_by_date": "finance",
    "get_bkjy_value": "finance",
    "get_bkjy_value_by_date": "finance",
    "get_scjy_value": "finance",
    "get_scjy_value_by_date": "finance",
    # Phase 4: Formula Data And Execution
    "formula_format_data": "formula",
    "formula_set_data": "formula",
    "formula_set_data_info": "formula",
    "formula_get_data": "formula",
    "formula_get_all": "formula",
    "formula_get_info": "formula",
    "formula_zb": "formula",
    "formula_xg": "formula",
    "formula_exp": "formula",
    "formula_process_mul_zb": "formula",
    "formula_process_mul_xg": "formula",
    "formula_process_mul_exp": "formula",
    # Runtime/Internal（internal-only：归桥/生命周期，raw 不得触达）
    "subscribe_hq": "realtime_internal",
    "unsubscribe_hq": "realtime_internal",
    "get_subscribe_hq_stock_list": "realtime_internal",
    # Admin/Operator Or Raw-Only Utilities（admin-only：raw 逃生口即其 admin 面）
    "refresh_cache": "admin",
    "refresh_kline": "admin",
    "download_file": "admin",
    "exec_to_tdx": "admin",
    "send_message": "admin",
    "send_file": "admin",
    "send_warn": "admin",
    "send_bt_data": "admin",
    "send_trade_warn": "admin",
    "send_warnings_for_stocks": "admin",
    "create_sector": "sector_admin",
    "delete_sector": "sector_admin",
    "rename_sector": "sector_admin",
    "clear_sector": "sector_admin",
    "get_user_sector": "sector_admin",
    "send_user_block": "sector_admin",
    # Do Not Expose: Trading And Account（账户/交易边界）
    "stock_account": "account",
    "query_stock_asset": "account",
    "query_stock_orders": "trading",
    "query_stock_positions": "account",
    "order_stock": "trading",
    "cancel_order_stock": "trading",
    # Example Helpers And Non-APIs（非原生 API，拒绝）
    "get_real_time_data": "example_helper",
}

# raw 诊断面拒绝族：交易/账户（datasource 边界外）、实时订阅内部方法
# （归桥/生命周期）、非原生 API。admin/sector_admin 经 raw 放行（操作员工作流）。
TDX_DENIED_FAMILIES = frozenset(
    {"trading", "account", "realtime_internal", "example_helper"}
)


def evaluate_tdx_method(method: str) -> AdminGuardResult:
    return AdminGuard(
        "tdx", TDX_CLASSIFICATION, TDX_DENIED_FAMILIES
    ).evaluate(method)
