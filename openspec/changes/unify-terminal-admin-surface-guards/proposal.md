# Proposal: unify-terminal-admin-surface-guards

## Why

2026-09-09 数据缺口排查暴露：两源对终端通道的守卫哲学不一致，且各有缺陷——

- **QMT 桥命令通道**：白名单（逐方法 schema 校验）——生产契约正确；但没有受治理的
  通用执行入口，任何新能力都必须发桥版本 + 手动部署。
- **TDX `/v1/raw/tdx/call`**：**黑名单**守卫（`FORBIDDEN_RAW_METHODS` + `withdraw_`
  前缀）——"未禁即可调"，tqcenter 交易/账户方法漏禁即远程触发，黑名单随终端版本
  漂移永远追不全。
- **守卫位置也不一致**：QMT 的守卫在桥 handler 内；TDX 终端 HTTP（17709）本身无
  守卫，守卫在 datasource 侧且仅黑名单。

统一目标：**传输由终端决定（无法一致，也不该强行一致），但治理模型、守卫判定、
admin 面形状必须完全对称**——生产通道白名单（不动）+ datasource 分类守卫
（新增，双源同构、三段 fail-closed）。

## What Changes

- **每源一份 checked-in 分类映射**（同构结构、同更新流程：先治理文档 → 再映射）：
  QMT = ContextInfo 方法面（thinktrader 官方文档字典；**trading/account 为拒绝族**，
  `passorder` 显式录入）；TDX = tqcenter 方法面（coverage 文档；
  **trading/account/execution 为拒绝族**）。
- **共享三段 fail-closed 守卫组件**（一个实现，两源实例）：未分类拒绝 →
  拒绝族拒绝 → 放行。TDX raw_call 黑名单退役；QMT 由此获得分类守卫的执行口。
- **QMT**：桥新增 `call_native` 命令（单层执法 + **一行交易硬拒**——静态元组拒
  `passorder` 等交易/账户模式）+ datasource admin 路由 `/v1/raw/qmt/call` +
  owner 租约按在途命令放行（`busy_until`）。
- **TDX**：`raw_call` 接入分类守卫（黑名单退役）；**桥零改动**。
- **admin 面可观测**：统一计数器 `mist_datasource_admin_call_total{source,method,
  result}` + 结构化日志；路由保持 compose 网内、无公共暴露。
- **不做（归后续 change）**：`introspect_methods` 与 `download_history_data` 命令
  归 `add-qmt-history-download`（其桥发版 v3.2 一次携带）；不改两源生产数据通道
  的既有白名单语义；不做 k 表/采集行为变更；TDX 桥不动。

## Capabilities

### 新增 capability：`datasource-admin-surface`

- 双源分类映射驱动的三段 fail-closed 守卫（未分类拒 / 拒绝族拒 / 放行）
- QMT call_native（单层执法 + 桥内一行交易硬拒）+ busy_until 租约放行
- TDX raw_call 接入同款守卫（黑名单退役）
- admin 调用可观测；网内私有不变

## Impact

- 新增：`src/datasource/tdx/classification.py`、`src/datasource/qmt/classification.py`、
  `src/datasource/admin/guard.py`
- 修改：`src/datasource/tdx/provider.py`（raw_call 接守卫，黑名单退役）、
  `src/datasource/qmt/realtime/gateway.py`（busy_until）、
  `qmt/builtin_bridge/mist_qmt_realtime_bridge.py`（**仅 call_native**，v3.1）、
  `qmt/routes/v1/`（`/v1/raw/qmt/call`）、`tdx/routes/v1/product.py`（守卫接入）、
  `src/datasource/metrics.py`、`src/core/config.py`
- 新增配置：`QMT_ADMIN_CALL_TIMEOUT_MS` / `TDX_ADMIN_CALL_TIMEOUT_MS`
  （默认 600000，上限 1800000）
- QMT 桥 `bridgeBuildId` v3.0 → v3.1（**仅 call_native**）；需用户手动 copy
  （GBK，禁 scp）+ 重启终端；TDX 无桥改动，仅 datasource 容器部署
- backend 零改动；`add-qmt-history-download` 接力（busy_until 验收、
  introspect + download 命令随其 v3.2 发版）