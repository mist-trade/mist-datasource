# Proposal: add-qmt-history-download

## Why

2026-09-08/09 生产数据缺口审计实锤：**两个终端的历史 K 线都依赖显式下载，而采集
从不触发下载**——

- **QMT**：`get_market_data_ex` 只读终端本地缓存，从不触发下载。9/1 起缓存断供 →
  000688 缺 14 条 K 无法补录。
- **TDX**：历史就绪依赖**操作员每晚手动盘后下载**（2026-09-09 用户证实）。手动下载
  未跑/晚于 22:30 同步时点的夜晚（9/2、9/4、9/7、9/8），盘中 K 全部缺失，盘前巡检
  klines 维度天天红。8/20–8/31 的完整只是手动习惯恰好覆盖。

**API 形态实证（2026-09-09 晚 probe，evidence/2026-09-09-qmt-download-api-probe.md）**：
终端 `ContextInfo` 上没有 `download_history_data`——它是 QMT 框架注入到**策略脚本
全局命名空间**的函数（官方文档示例即裸调用）。因此早期"call_native 通用执行"的
方案不可达，已废弃。

## What Changes

- **下载与读取解耦（用户决策）**：`bars/query` 回归**纯读取**（30s 超时恢复够用）；
  下载是显式的独立阶段——采集流程改为"**统计缺失 → 提交下载 → 完成后获取**"。
- **datasource 下载 job 端点**（QMT）：
  - `POST /v1/qmt/download`：提交 `{stock_list, base_periods(1m/5m/1d),
    start_time, end_time}` → in-memory job，经命令网关让桥**串行下载** → 立即返回
    `{job_id, tasks}`（不等待）；
  - `GET /v1/qmt/download/{jobId}`：逐任务状态 + 聚合；
  - **盘中硬门禁**（ActivityWindow）内拒绝提交（counter `in_session`）。
- **QMT 桥 v3.2**：新增 `introspect_methods`（只读方法面报告，ContextInfo attrs +
  script globals 双面）与 `download_history_data`（经 `globals()` 解析裸全局 API，
  三基础周期顺序下载、逐周期状态汇总）两个 handler；**移除 call_native**（本 change
  携带 datasource-admin-surface 的 REMOVED delta——通用执行洞退役）。
- **backend collector 三段编排**（mist 仓）：夜间/手动同步前——统计缺失 → 提交
  下载 job → 轮询完成 → 既有逐任务采集。
- **TDX 不引入 job 模型**：`refresh_kline` 生产实测 ~100ms（终端托管范围），
  `get_bars` 内同步前置足够（task 3.2，不对称有实测依据）。
- **不做**：不做 k 表数据规范化（接缝由消费方处理）；TDX 桥不动。

## Capabilities

### 新增 capability：`qmt-market-history`

- 下载 job 端点（提交/状态、盘中门禁、桥串行执行）
- 桥 download handler 经 `globals()` 解析裸全局 API（ContextInfo fallback）
- bars/query 纯读取（显式要求：读不做下载）

### 修改 capability：`datasource-admin-surface`（REMOVED delta）

- 移除 QMT call_native 执行面（路由 + 分类映射 + 桥 handler）——有了专用下载
  命令后通用执行洞退役；TDX 侧守卫不变。

## Impact

- `src/datasource/qmt/history_download.py`（job 注册表/编排）、
  `qmt/routes/v1/product.py`（download 提交/状态路由）
- `src/datasource/qmt/provider.py`（撤 admin_call_native）、
  `src/datasource/qmt/classification.py`（删除）、
  `src/datasource/admin/guard.py`（保留，TDX 使用）、
  `tdx/routes/v1/product.py`（introspect 路由接入）
- `qmt/builtin_bridge/mist_qmt_realtime_bridge.py`：+`introspect_methods`/
  `download_history_data`，−`call_native`/`TRADING_DENY_PATTERNS`；v3.1 → v3.2
- mist 仓：collector 统计缺失 + 提交/轮询编排（新模块）；bars/query 纯读不变；
  `DATASOURCE_HTTP_TIMEOUT_MS` 保持 30s 不动
- 新增配置：`QMT_DOWNLOAD_JOB_ENABLED`（datasource，默认 on）
- 部署：datasource 容器 + QMT 桥 v3.2（用户手动 copy 一次）+ backend 容器（编排）