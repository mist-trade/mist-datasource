# Specification: datasource-admin-surface (partial delta carried by add-qmt-history-download)

> 本文件是 `unify-terminal-admin-surface-guards` 之外、由本 change 携带的补充
> delta：退役 QMT call_native 通用执行面（专用 download 命令落地后，通用执行洞
> 不再有必要性）。归档顺序：先 `unify-terminal-admin-surface-guards`，再本 change。

## REMOVED Requirements

### Requirement: QMT call_native enforces the classification guard with a trading hard-deny

**Reason for removal**: 通用 `ContextInfo` 执行入口（call_native）的存在意义是
"探索性方法无需发桥版本"。专用 `download_history_data` 桥命令落地后，下载能力
有了专属入口；call_native 此前无生产调用方（路由上线数小时、零使用），继续保留
即在终端内维护一个受治理的通用执行洞。分类映射（QMT ContextInfo 面）的唯一消费
方随之消失，一并退役。

**替代**：下载能力由 `qmt-market-history` 的专用 download job 端点承接
（提交/状态/盘中门禁，见 qmt-market-history delta）。TDX raw_call 的分类守卫
不受影响（TDX 逃生口为操作员排障面，守卫保留）。

#### Scenario: QMT admin execution surface is retired

- **WHEN** the change is implemented and deployed
- **THEN** the datasource MUST NOT expose `/v1/raw/qmt/call` (route removed)
- **AND** `QmtDatasourceProvider` MUST NOT expose `admin_call_native`
- **AND** the bridge v3.2 MUST NOT contain a `call_native` handler
- **AND** the QMT classification map MUST be removed from the codebase
  (the TDX classification map and guard remain in place)
