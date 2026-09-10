# Tasks: add-qmt-history-download

## 1. datasource 侧：download job 端点 + call_native 退役

- [x] 1.1 `[mist-datasource]` 新增 job 注册表/编排模块
  `src/datasource/qmt/history_download.py`：in-memory job（任务 =
  symbol × base period，经命令网关串行 enqueue 原生
  `download_history_data`）、逐任务状态、聚合、TTL 清理。
- [x] 1.2 `[mist-datasource]` 路由：`POST /v1/raw/qmt/download`（校验：
  symbol 格式、base_periods ⊆ {1m,5m,1d}、≤64 标的、日期合法；ActivityWindow
  门禁 → `in_session`）+ `GET /v1/raw/qmt/download/{job_id}`（逐任务+聚合）。
- [x] 1.3 `[mist-datasource]` **call_native 面退役**：删
  `/v1/raw/qmt/call` 路由、`QmtAdminCallRequest`、`_admin_result_from_error`、
  `provider.admin_call_native`、`src/datasource/qmt/classification.py`；
  busy_until 机制保留（download 命令在途放行）。
- [x] 1.4 `[mist-datasource]` 可观测性：job 计数器
  `mist_datasource_qmt_history_download_total{result}` + 提交/拒绝/逐任务
  warn（reason 有界）。
- [ ] 1.5 `[mist-datasource]` 配置：`QMT_DOWNLOAD_JOB_ENABLED`（datasource，
  默认 on）；`QMT_ADMIN_CALL_TIMEOUT_MS` 配置随 call_native 退役删除
  （mist-deploy 同步）。

## 2. QMT 桥 v3.2：introspect + download 双命令

- [x] 2.1 `[mist-datasource]` 桥新增 `introspect_methods`：candidates 校验
  （≤32、标识符正则）、**双面只读报告**（ContextInfo attrs + script globals，
  available/type/doc 有界）、绝不调用。
- [x] 2.2 `[mist-datasource]` 桥新增 `download_history_data`：解析顺序
  `globals().get` → `getattr(ContextInfo, ...)` fallback；按 periods 顺序
  逐周期同步下载、逐周期状态汇总；`bridgeBuildId` →
  `mist-qmt-realtime-bridge-v3.2`。
- [x] 2.3 `[mist-datasource]` 桥移除 `call_native` handler、
  `TRADING_DENY_PATTERNS`、`_NATIVE_METHOD_NAME_RE`、`import re`（如无他用）。
- [x] 2.4 `[mist-datasource tests]` guardrail：双新 handler 过
  `test_bigqmt_bridge_guardrails.py`（3.6/GBK/无 threading）+ call_native
  移除断言（源码不再包含）。

## 3. backend collector 三段编排（mist 仓）

- [ ] 3.1 `[mist]` 统计缺失：QMT 源标的 × 基础周期(1m/5m/1d) × 目标窗查 k 表，
  枚举缺口（跳过已完整窗口）。
- [ ] 3.2 `[mist]` 下载提交与轮询：缺口 → `POST /v1/raw/qmt/download` 提交 job
  → 轮询 status（5–10s 间隔，预算 ≤ 600s，超时走既有 notReady 路径）。
- [ ] 3.3 `[mist]` 编排挂接：夜间/晨间同步与手动 collect 前置该三段（TDX 源
  标的不提交——refresh 由 datasource get_bars 内置）。
- [ ] 3.4 `[mist tests]` 单测：缺口枚举、提交/轮询（完成/超时/拒绝）、TDX 跳过。

## 4. 部署与验证

- [x] 4.1 `[mist-datasource]` CI 全绿（pytest 全仓 + pyright）+ compose/env
  增加 `QMT_DOWNLOAD_JOB_ENABLED`（mist-deploy defaults + 断言）+ 移除
  `QMT_ADMIN_CALL_TIMEOUT_MS`（随 call_native 退役）。
- [ ] 4.2 `[deploy]` 部署 datasource 容器 + backend 容器（编排上线）。
- [ ] 4.3 `[hil]` 用户手动 copy QMT 桥 v3.2 + 重启终端（避开交易时段）；
  验证 `bridgeBuildId=v3.2`、实时流无中断、call_native 已从桥面消失。
- [ ] 4.4 `[hil]` 验证矩阵：download job 实跑（000688 缺口补录）→ 逐任务
  状态 → k 表核对；introspect 双面报告实跑（`download_history_data`
  可用性终证）；bars/query 无下载副作用确认。
- [ ] 4.5 `[ops]` 次晨 09:05 巡检卡核对：000688 转绿、整体 PASSED。

## 5. TDX 侧：下载端点（无读取内前置——纯读取对称）

- [x] 5.1 `[mist-datasource]` 生产 probe（完成，证据 evidence/2026-09-09-tdx-refresh-kline-probe.md：12 次 refresh 全 ErrorId=0、延迟 16-114ms、9/8 读回 240/48/1 全对；**盘中行为抽查待盘中补测**）。
- [ ] 5.2 `[mist-datasource]` **TDX 下载端点**：`POST /v1/tdx/download`（`{stock_list, base_periods ⊆ {1m,5m,1d}}`）→ 逐周期 `refresh_kline` → 逐周期状态返回；symbol/period 校验前置；同步限时（实测 ~100ms，预算 600s）；`raise_for_native_error` 适配 `ErrorId==0` 成功形状（实测 `Msg` 字段）。
- [x] 5.3 `[mist-datasource tests]` 单测：端点逐周期调用/非法周期拒绝/`ErrorId` 归一化；盘中抽查留 HIL（5.1 尾巴）。
- [x] 5.4 `[mist-datasource]` **get_bars 保持纯读**：确认读取路径无 refresh 前置（delta 已按纯读取修订）。
