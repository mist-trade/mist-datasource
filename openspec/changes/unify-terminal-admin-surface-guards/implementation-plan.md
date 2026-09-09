# Implementation Plan: unify-terminal-admin-surface-guards

> 对应 spec：`openspec/changes/unify-terminal-admin-surface-guards/`（proposal/design/tasks/specs delta）
> 范围：datasource 分类守卫（双源对称）+ QMT call_native（含一行交易硬拒）+
> busy_until 租约放行。**introspect_methods / download_history_data 不在本 change**
> （归 `add-qmt-history-download`，其桥发版 v3.2 一次携带）。TDX 桥零改动。

## 0. 前置事实（已核实）

- QMT 命令流：`QmtCommandGateway.enqueue(method, params, timeout_seconds)` → 轮询
  `take_result(command_id)` → `_resolve_bridge_result`；gateway 无方法白名单
  （白名单在桥 handler）；`_owner_is_stale` 基于 `owner_stale_after_seconds=15.0`
  （`gateway.py:124/137`），`health()` 输出 `ownerStale`，`get_bars` 前置检查
  （`operations/market.py:55`）。
- TDX raw：`TdxProvider.raw_call`（`provider.py:349`）黑名单
  `FORBIDDEN_RAW_METHODS`/`FORBIDDEN_RAW_PREFIXES`（`provider.py:57` 附近）。
- 路由：QMT `qmt/routes/v1/product.py`（`/v1/bars/query` 在此）；TDX
  `tdx/routes/v1/product.py`（`/v1/raw/tdx/call` 在 :292）。
- metrics：`src/datasource/metrics.py`（`record_*` 模式，Counter）。
- 配置：`src/core/config.py` 的 `settings`。

## 1. 新增文件（3 个）

### 1.1 `src/datasource/tdx/classification.py`
```python
# 治理源：docs/references/tdxquant-interface-coverage.md（逐项锚点注释）
# method -> family；family ∈ {market, reference, finance, formula, admin_refresh,
#                             calendar, trading, account, execution, ...}
TDX_CLASSIFICATION: dict[str, str] = {
    "get_market_data": "market",
    "refresh_kline": "admin_refresh",
    "refresh_cache": "admin_refresh",
    "get_trading_dates": "calendar",
    # ... coverage 文档现存约 40 项逐条移植（含 trading/account/execution 族，
    #     显式录入使拒绝原因明确）
}
TDX_DENIED_FAMILIES = frozenset({"trading", "account", "execution"})

def classify(method: str) -> ClassificationResult  # (classified, family, allowed)
    # 输入规范化：strip + lower；未分类 → allowed=False, reason=unclassified
```

### 1.2 `src/datasource/qmt/classification.py`
```python
# 治理源：thinktrader 官方文档字典（ContextInfo 方法面）
# 首版保守：仅录入已确认安全的 market/reference 方法 + 显式录入已知交易/账户方法
QMT_CLASSIFICATION: dict[str, str] = {
    "get_market_data_ex": "market",
    "get_market_data": "market",
    "get_local_data": "market",
    "get_stock_list_in_sector": "reference",
    "get_trading_dates": "calendar",
    "passorder": "trading",          # 显式录入拒绝族（拒绝原因明确）
    # ... 其余方法首版不录入（= unclassified 拒绝），随 probe 逐个升级
}
QMT_DENIED_FAMILIES = frozenset({"trading", "account"})
```

### 1.3 `src/datasource/admin/guard.py`
```python
class AdminGuardResult: allowed: bool; reason: str | None  # unclassified|family_forbidden
class AdminGuard:  # 按源实例化
    def __init__(self, source: str, classification: dict, denied_families: frozenset)
    def evaluate(self, method: str) -> AdminGuardResult
      # 1. strip/lower 后查映射；未分类 → deny("unclassified")
      # 2. family ∈ denied → deny("family_forbidden")
      # 3. else allow
```

## 2. 修改文件

### 2.1 `src/datasource/tdx/provider.py`
- `raw_call`：删除 `FORBIDDEN_RAW_METHODS`/`FORBIDDEN_RAW_PREFIXES` 判定，改为
  `AdminGuard("tdx", ...).evaluate(method)`；拒绝抛 `TdxMethodForbiddenError`
  （保留既有异常类型，payload 加 reason）。

### 2.2 `src/datasource/qmt/realtime/gateway.py`
- `QmtCommandGateway` 新增 `_busy_until: float = 0.0` 与
  `extend_busy_until(seconds)`（`busy_until = max(busy_until, now + seconds)`）；
- `_owner_is_stale(now)`：`(now - last_heartbeat > owner_stale_after_seconds)
  and (now >= self._busy_until)`；
- `health()` 的 `ownerStale` 字段走同一判定（`operations/market.py:55` 前置检查
  自动一致）；
- `enqueue` 不变；busy_until 由调用方（admin 路由 / 未来下载编排）显式延长。

### 2.3 `src/datasource/qmt/provider.py`
- 新增 `admin_call_native(method, params, timeout_seconds) -> dict`：
  guard.evaluate → 拒则抛；通过则 `extend_busy_until(timeout + 60)` →
  `enqueue("call_native", {...})` → 既有轮询模式取结果（超时 →
  `QmtBridgeError(QMT_ADMIN_CALL_TIMEOUT, retryable=True)`）。

### 2.4 `qmt/builtin_bridge/mist_qmt_realtime_bridge.py`（Python 3.6 + GBK）
- `_execute_history_command` 分支新增：
  - `call_native`：`method` 匹配 `TRADING_DENY_PATTERNS`（模块级元组：
    `("passorder", "trade", "order_", "account", "withdraw")`，startswith 匹配）
    → 拒绝（`QMT_ADMIN_METHOD_FORBIDDEN`）；否则 `getattr(ContextInfo, method)`
    执行 params 中 `args`/`kwargs`，返回 `_history_json_safe(result)`。
- `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.1`。
- 不新增 import；不动回调/轮询结构（guardrail 约束）。
- **注意**：`introspect_methods`/`download_history_data` 两个 handler 不在本
  change（归 `add-qmt-history-download`，其桥发版 v3.2 一次携带）。

### 2.5 路由
- `qmt/routes/v1/product.py`（或新建 `qmt/routes/admin.py` 挂 v1 router）：新增
  `POST /v1/raw/qmt/call`。
- `tdx/routes/v1/product.py`：`/v1/raw/tdx/call` 行为不变（守卫在 provider 层）。
- 两路由保持 compose 网内；OpenAPI 不新增公共语义（照 raw-diagnostics 既有模式）。

### 2.6 `src/datasource/metrics.py`
- `record_admin_call(source: str, method: str, result: str)` →
  Counter `mist_datasource_admin_call_total{source, method, result}`；
  method 有界（未分类记 `"unclassified"`；超长截断）。

### 2.7 `src/core/config.py`
- `qmt_admin_call_timeout_ms: int = 600000`、`tdx_admin_call_timeout_ms: int = 600000`
  （校验 ≤ 1800000、> 0）。

### 2.8 `mist-deploy`
- `scripts/common/deploy-defaults.ps1`：两个 timeout 默认值；
- `docker/compose.yaml`：qmt/tdx datasource environment 两个变量；
- `docker/.env.example` + `scripts/test-docker-compose-config.ps1` 断言
  （参照 NOTIFICATION_CHANNELS 模式）。

## 3. 测试（pytest）

| 文件 | 覆盖 |
|------|------|
| `tests/unit/test_admin_guard.py` | 三段判定矩阵（两源）：放行/未分类/拒绝族；大小写与空白规范化 |
| `tests/unit/test_tdx_classification.py` | coverage 条目移植完整性（数量+关键锚点）；Do-Not-Expose 逐方法 ∈ 拒绝族 |
| `tests/unit/test_qmt_classification.py` | 首版条目；passorder ∈ trading |
| `tests/unit/test_tdx_provider_raw_guard.py`（改造既有） | 未分类拒/拒绝族拒/放行/异常 payload |
| `tests/unit/test_qmt_gateway_busy_until.py`（新增） | 在途不误判死亡、到期判死、health ownerStale 一致、extend_busy_until 幂等取 max |
| `tests/unit/test_qmt_admin_routes.py`（新增） | 六态路由行为、交易硬拒独立生效（mock） |
| `tests/unit/test_bigqmt_bridge_guardrails.py`（增补） | call_native handler：3.6 语法/GBK/无 threading/交易硬拒生效 |
| `tests/integration/test_qmt_v1.py`（增补） | 路由 ↔ 网关 ↔ 桥 mock 全链（含超时短路） |

## 4. 验证命令

```bash
# 全仓静态与测试（本仓铁律：改动必须全仓跑）
uv run pyright && uv run pylint src qmt tdx
uv run pytest tests -q
node -e "...openspec validate unify-terminal-admin-surface-guards..."
# 部署后 HIL（见 spec tasks 4.x）
```

## 5. 部署与联动（概要）

1. mist-deploy defaults/compose 断言随本仓一起提交；
2. datasource 容器部署（TDX raw 守卫即时生效；QMT admin 路由就绪待 v3.1 桥）；
3. 用户手动 copy QMT 桥 v3.1（仅 call_native）+ 重启终端（盘外）→ 验证
   `bridgeBuildId`；
4. HIL 矩阵：TDX 放行/未分类拒/拒绝族拒；QMT call_native 实跑（分类安全方法）；
   busy_until（在途不误判）；
5. 联动：`add-qmt-history-download` 接力（v3.2 桥携带 introspect_methods +
   download_history_data 两命令；其 task 1.5 转验收本 change 的 busy_until）。
