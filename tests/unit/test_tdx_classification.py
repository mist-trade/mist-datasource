"""Unit tests for the TDX tqcenter classification map (task 3.2).

治理源：docs/references/tdxquant-interface-coverage.md。
判定语义：未分类拒绝 → 拒绝族拒绝 → 放行。
"""

from src.datasource.tdx.classification import (
    TDX_CLASSIFICATION,
    TDX_DENIED_FAMILIES,
    evaluate_tdx_method,
)


def test_documented_data_methods_are_allowed():
    allowed_expected = {
        "get_market_data": "market",
        "get_pricevol": "market",
        "get_trading_dates": "calendar",
        "get_stock_list": "reference",
        "get_stock_list_in_sector": "reference",
        "get_relation": "reference",
        "get_financial_data": "finance",
        "formula_zb": "formula",
        "refresh_kline": "admin",
        "refresh_cache": "admin",
    }
    for method, family in allowed_expected.items():
        verdict = evaluate_tdx_method(method)
        assert verdict.allowed is True, method
        assert verdict.family == family, method
        assert verdict.reason is None, method


def test_do_not_expose_trading_and_account_methods_are_denied():
    # coverage 文档 "Do Not Expose: Trading And Account" 章节逐方法
    do_not_expose = [
        "stock_account",
        "query_stock_asset",
        "query_stock_orders",
        "query_stock_positions",
        "order_stock",
        "cancel_order_stock",
    ]
    for method in do_not_expose:
        verdict = evaluate_tdx_method(method)
        assert verdict.allowed is False, method
        assert verdict.reason == "family_forbidden", method
        assert verdict.family in ("trading", "account"), method


def test_realtime_internal_methods_are_denied():
    # subscribe_hq 等归桥/生命周期所有，raw 诊断面不得触达
    for method in ["subscribe_hq", "unsubscribe_hq", "get_subscribe_hq_stock_list"]:
        verdict = evaluate_tdx_method(method)
        assert verdict.allowed is False, method
        assert verdict.family == "realtime_internal", method


def test_example_helper_and_unknown_methods_are_denied():
    # get_real_time_data 是示例 helper（非原生 API）；未分类方法 fail-closed
    for method in ["get_real_time_data", "get_report_data", "some_new_method"]:
        verdict = evaluate_tdx_method(method)
        assert verdict.allowed is False, method


def test_denied_families_are_exactly_the_documented_set():
    assert frozenset(
        {"trading", "account", "realtime_internal", "example_helper"}
    ) == TDX_DENIED_FAMILIES


def test_classification_map_covers_the_documented_surface():
    # coverage 文档现存条目抽查（数量级 + 关键锚点）；文档扩表时同步更新映射
    documented_spot_checks = {
        "get_market_data",
        "get_trading_dates",
        "get_stock_list_in_sector",
        "get_divid_factors",
        "get_financial_data",
        "formula_zb",
        "subscribe_hq",
        "refresh_kline",
        "download_file",
        "exec_to_tdx",
        "stock_account",
        "order_stock",
        "get_real_time_data",
    }
    missing = documented_spot_checks - set(TDX_CLASSIFICATION)
    assert missing == set()
    assert len(TDX_CLASSIFICATION) >= 50
