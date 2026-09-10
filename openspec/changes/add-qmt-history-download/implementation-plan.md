# Implementation Plan: add-qmt-history-download

> 对应 spec：`openspec/changes/add-qmt-history-download/`（proposal/design/tasks/specs deltas ×3）
> 架构（用户确认 2026-09-09）：**下载与读取解耦**——datasource 提供 download job
> 端点（提交/状态，桥串行执行），backend collector 三段编排（统计缺失 → 提交 →
> 轮询完成 → 读取）；**call_native 执行面退役**（专用 download 命令替代）；TDX
> 桥零改动。QMT 桥一次发版 v3.2（introspect + download，移除 call_native）。

## 0. 前置事实（已核实/实测）

- 命令流：`QmtCommandGateway.enqueue(method, params, timeout_seconds)` → 轮询
  `take_result(command_id)`；busy_until 已落地（`extend_busy_until`，
  `unify-terminal-admin-surface-guards` task 1.3）。
- API 形态：`download_history_data` 是**框架注入的策略脚本全局函数**（不在
  ContextInfo 上——probe 实证）；签名 `(stockcode, period, startTime, endTime,
  [incrementally])`，返回 none。
- QMT raw 路由现状：`/v1/raw/qmt/call`（call_native，75ea98b 已部署）——本 change
  移除；`/v1/raw/tdx/call` 保留（黑名单已换分类守卫）。
- backend collector：`/v1/collector/collect` → datasource `/v1/bars/query`
  （axios `DATASOURCE_HTTP_TIMEOUT_MS=30000`——纯读保持不动）。
- 盘中门禁判定器：`src/datasource/realtime/stall_detector.py::ActivityWindow`
  （复用，不新建时段逻辑）。

## 1. datasource 新增：download job 模块

### 1.1 `src/datasource/qmt/history_download.py`
```python
class DownloadTask: symbol; base_period; state(pending|running|done|failed); error
class DownloadJob: job_id; tasks; created_at; aggregate() -> str

class QmtHistoryDownloadRegistry:
    def __init__(self, *, command_gateway: QmtCommandGateway,
                 clock, ttl_seconds=3600, max_tasks_per_job=192)
    def submit(stock_list, base_periods, start_time, end_time) -> {job_id, tasks}
        # 校验：symbol 正则、base_periods ⊆ {1m,5m,1d}、≤64 标的、日期合法
        # 任务 = (symbol × base period) 组合；in-memory 注册 + TTL 清理
    def job_status(job_id) -> {state, tasks:[...]} | None
    async def _run_job(job) -> None
        # 串行：逐任务 enqueue("download_history_data", {stockcode, periods:
        #   [p], startTime, endTime}, timeout_seconds=budget) → extend_busy_until
        #   (timeout+60) → 轮询 take_result → 更新任务状态
        # 全部终态后保留 job 供查询（TTL 后清理）
```
- 编排逻辑：gateway 复用既有 enqueue/take_result（无迟到结果机制）；命令网关
  的 `extend_busy_until` 在每条命令发出时调用。
- ActivityWindow 门禁在路由层（1.2），不在 registry（registry 纯机制）。

### 1.2 `src/core/config.py`
- `QMTSettings.download_job_enabled: bool = True`（env
  `QMT_DOWNLOAD_JOB_ENABLED`）。

### 1.3 `src/datasource/metrics.py`
- Counter `mist_datasource_qmt_history_download_total{result=
  ok|failed|in_session|disabled|unsupported}`（提交门禁/执行结果按 job 记）。

## 2. datasource 路由（`qmt/routes/v1/product.py`）

### 2.1 新增
- `POST /v1/qmt/download`：
  `QmtDownloadJobRequest {stock_list, base_periods, start_time, end_time}`
  → ActivityWindow.in_window() → `in_session` 拒绝；
  `settings.qmt.download_job_enabled=off` → `disabled` 拒绝；
  否则 `registry.submit(...)` → `_success({job_id, tasks})`。
- `GET /v1/qmt/download/{jobId}` → `_success(registry.job_status(...))`；
  未知 job_id → 404 语义 failure。

### 2.2 移除（call_native 退役，REMOVED delta 对应）
- 删 `/v1/raw/qmt/call` 路由 + `QmtAdminCallRequest` + `_admin_result_from_error`
  + `record_admin_call` 调用点（QMT 侧；TDX 路由的 admin 计数保留）。
- 删 `provider.admin_call_native`；删 `src/datasource/qmt/classification.py`；
  `guard.py` 保留（TDX 使用）。

## 3. QMT 桥 v3.2（`qmt/builtin_bridge/mist_qmt_realtime_bridge.py`）

- `_execute_history_command` 新增分支：
  - `introspect_methods {candidates}`：逐候选双面报告
    `{contextinfo: {available, type, doc}, globals: {available, type}}`；
    getattr/globals.get 只读、绝不调用；candidates ≤ 32 + 标识符正则。
  - `download_history_data {stockcode, periods, startTime, endTime}`：
    `dl = globals().get("download_history_data") or
     getattr(ContextInfo, "download_history_data", None)`；
    不可调用 → `QMT_DOWNLOAD_API_UNAVAILABLE`；
    可调用 → 逐周期 `dl(stockcode, period, startTime, endTime)` 顺序执行、
    逐周期状态汇总返回。
- **移除** `call_native` handler、`TRADING_DENY_PATTERNS`、
  `_NATIVE_METHOD_NAME_RE`（`import re` 若无他用一并删）。
- `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.2`。
- 既有 `get_market_data_ex`/`get_stock_list_in_sector`/health/introspection
  分支不动。

## 4. backend collector 三段编排（mist 仓）

### 4.1 新增 `apps/mist/src/collector/history-download.client.ts`
- `submitDownloadJob(securities, basePeriods, window)` → axios POST
  `/v1/qmt/download`（timeout 10s）→ `{jobId, tasks}`；
- `pollDownloadJob(jobId)` → axios GET（间隔 5–10s，预算
  `QMT_DOWNLOAD_JOB_BUDGET_MS` 默认 600000）→ 聚合状态。

### 4.2 `post-close-sync.service.ts`（或 collector.service.ts）挂接
- 同步任务构建前：QMT 源标的 × 基础周期(1m/5m/1d) × 目标窗查 k 表缺口 →
  有缺口 → submit → poll → 完成（或预算超时降级）→ 继续既有逐任务
  `collectKForSource`（bars/query 纯读，缓存命中）；
- TDX 源标的跳过（其 refresh 在 datasource get_bars 内置，task 3.2）；
- 计数/日志：缺口数、job 状态、预算超时 warn（reason 有界）。

### 4.3 `apps/mist/src/collector/collector.module.ts`
- 注册 history-download client（HttpService 复用）。

## 5. 测试

| 文件 | 覆盖 |
|------|------|
| `tests/unit/test_qmt_history_download.py` | job 生命周期（submit/串行执行/逐任务状态/TTL）、校验拒绝、busy_until 在途放行 |
| `tests/unit/test_qmt_admin_surface_removal.py`（或并入既有） | `/v1/raw/qmt/call` 404/移除断言；classification.py 不存在断言 |
| `tests/unit/test_bigqmt_bridge_guardrails.py`（增补） | introspect 双面报告（globals+ContextInfo）、download handler globals 解析（namespace 注入假 download_history_data）、call_native 移除 |
| `tests/integration/test_qmt_download_routes.py` | submit/status 全链（含 in_session/无效参数/unsupported 旧桥） |
| mist `apps/mist/src/collector/*.spec.ts` | 缺口枚举、submit/poll（完成/超时）、TDX 跳过 |

## 6. 验证命令

```bash
# mist-datasource
uv run ruff check . && uv run pyright && uv run pytest tests -q
node -e "...openspec validate add-qmt-history-download..."
# mist
pnpm jest apps/mist/src/collector --silent? → 按仓实际命令；pnpm build:docker 校验
# mist-deploy
pwsh-preview -NoProfile -File scripts/test-docker-compose-config.ps1
```

## 7. 部署与联动（概要）

1. datasource 容器部署（job 端点 + 桥 v3.2 + call_native 退役）；
2. backend 容器部署（三段编排上线）；
3. 用户手动 copy QMT 桥 v3.2 + 重启终端（一次）；
4. 补录 000688 的 14 条（download job 实跑）→ 次晨巡检核对转绿。