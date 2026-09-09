"""Unit tests for the QMT ContextInfo classification map (task 1.1)."""

from src.datasource.qmt.classification import (
    QMT_CLASSIFICATION,
    QMT_DENIED_FAMILIES,
    evaluate_qmt_method,
)


def test_confirmed_safe_market_methods_are_allowed():
    for method in ["get_market_data_ex", "get_market_data", "get_local_data"]:
        verdict = evaluate_qmt_method(method)
        assert verdict.allowed is True
        assert verdict.family == "market"
        assert verdict.reason is None


def test_passorder_is_classified_into_denied_trading_family():
    verdict = evaluate_qmt_method("passorder")
    assert verdict.allowed is False
    assert verdict.family == "trading"
    assert verdict.reason == "family_forbidden"


def test_subscription_methods_are_denied_as_realtime_internal():
    for method in [
        "subscribe_quote",
        "subscribe_whole_quote",
        "unsubscribe_quote",
        "get_all_subscription",
    ]:
        verdict = evaluate_qmt_method(method)
        assert verdict.allowed is False
        assert verdict.family == "realtime_internal"
        assert verdict.reason == "family_forbidden"


def test_unclassified_methods_are_denied():
    for method in ["some_future_method", "do_something_else"]:
        verdict = evaluate_qmt_method(method)
        assert verdict.allowed is False
        assert verdict.reason == "unclassified"


def test_evaluation_normalizes_case_and_whitespace():
    assert evaluate_qmt_method("  GET_MARKET_DATA_EX  ").allowed is True
    assert evaluate_qmt_method("PASSORDER").allowed is False


def test_denied_families_are_exactly_the_documented_set():
    assert frozenset(
        {"trading", "account", "realtime_internal"}
    ) == QMT_DENIED_FAMILIES
    assert QMT_CLASSIFICATION["passorder"] == "trading"
