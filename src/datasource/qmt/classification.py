"""QMT ContextInfo method classification map (admin-surface governance source).

治理源：thinktrader 官方文档字典（ContextInfo 行情/交易/账户方法面）。
首版保守：仅录入已确认安全的方法 + 显式录入已知交易/账户方法；其余未收录 =
unclassified = admin 面一律拒绝（随 probe 逐个升级）。

更新流程：先改治理文档 → 再改本映射（两步、可 review）。
"""

from src.datasource.admin.guard import AdminGuard, AdminGuardResult

# family 枚举：
#   market / market_download / reference / realtime_internal / trading / account
QMT_CLASSIFICATION: dict[str, str] = {
    # market（生产桥已使用 / thinktrader 行情函数文档）
    "get_market_data_ex": "market",
    "get_market_data": "market",
    "get_local_data": "market",
    "get_stock_list_in_sector": "reference",
    # 行情数据下载（add-qmt-history-download 专用命令的原生 API；官方文档
    # download_history_data / download_history_data2）
    "download_history_data": "market_download",
    "download_history_data2": "market_download",
    # 订阅类：生产由订阅命令通道负责（桥已有专用 handler），raw 不得触达
    "subscribe_quote": "realtime_internal",
    "subscribe_whole_quote": "realtime_internal",
    "unsubscribe_quote": "realtime_internal",
    "get_all_subscription": "realtime_internal",
    # 交易/账户（拒绝族：显式录入使拒绝原因明确）
    "passorder": "trading",
}

QMT_DENIED_FAMILIES = frozenset({"trading", "account", "realtime_internal"})

_ADMIN_GUARD = AdminGuard("qmt", QMT_CLASSIFICATION, QMT_DENIED_FAMILIES)


def evaluate_qmt_method(method: str) -> AdminGuardResult:
    return _ADMIN_GUARD.evaluate(method)
