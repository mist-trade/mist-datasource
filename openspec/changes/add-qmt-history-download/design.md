# Design: add-qmt-history-download

## 1. 现状链路（取证 2026-09-09）

```
backend CollectorService.collectK / PostCloseSync
  → POST qmt-datasource /v1/bars/query
→ QmtMarketOperations.get_bars
  → 桥命令 {method:"get_market_data_ex", ...}
→ [终端内] _execute_history_command
  → ContextInfo.get_market_data_ex(...)   ← 只读终端本地缓存
```

问题：QMT 终端本地缓存的历史需要**显式下载**，实时订阅推送不回填历史缓存。
9/1 起缓存断供，`get_market_data_ex` 返回空 → 收盘同步 notReady → k 表缺口 +
巡检天天红。TDX 同理：历史就绪依赖操作员每晚手动盘后下载（2026-09-09 用户证实）。

**API 形态实证（2026-09-09 晚 probe，evidence/2026-09-09-qmt-download-api-probe.md）**：
终端 `ContextInfo` 上没有 `download_history_data`（getattr 三周期一致失败）——
官方文档示例本身是裸函数调用（框架注入到策略脚本全局命名空间）。早期 call_native
通用执行方案据此废弃（不可达 + 开洞）。

## 2. 关键决策

### D1 采集前置四步判定：统计缺失 → 真实数据过滤 → 下载 → 采集落库（用户决策 2026-09-09 晚修订）

bars/query 回归**纯读取**（30s 超时恢复够用）。下载是采集流程的**显式阶段**，
由 backend collector 编排。每个 (标的 × 周期 × 交易日) 在采集前走判定树：

```
① 已采集？      k 表该窗已有行 → 直接采集落库
② 真实数据判定  当日是否交易日（日历）→ 非交易日 → 无真实数据 → 跳过（不算缺口）
③ 缺 → 下载    调下载接口（QMT job / TDX refresh_kline 端点）→ 填充终端本地缓存
④ 采集落库      bars/query 读缓存 → upsert；仍无数据 → 当日无真实数据
                （疑似停牌）→ info 记录，不算 notReady 失败（停牌股每夜报缺口是噪声）
```

- **真实数据判定的两层**：交易日前置过滤（日历，①之前）+ 下载后验证（③之后仍空
  → 疑似停牌，info 不告警）。停牌无法在下载前可靠判定（数据源无停牌状态 API），
  以"下载后仍空"事后归类。
- **下载与读取解耦**：bars/query 纯读；下载经 datasource 下载端点显式提交。

### D2 异步 job 端点（不等待、不挂请求，用户决策）

- `POST /v1/qmt/download`：校验（stock_list 格式、base_periods ⊆ {1m,5m,1d}、
  数量 ≤ 64、日期窗合法）→ 创建 in-memory job（任务 = (symbol × base period) 组合，
  经命令网关让桥**串行**执行原生 `download_history_data`）→ 立即返回
  `{job_id, tasks}`；
- `GET /v1/qmt/download/{jobId}`：逐任务状态（pending/running/done/failed）+
  聚合（all_done / any_failed）；
- job 完成（全部任务终态）后保留结果供查询（TTL，如 1h）；
- **盘中硬门禁**（ActivityWindow）内拒绝提交（counter `in_session`）。

### D3 QMT 桥 v3.2：introspect + download 双命令，call_native 移除

- `introspect_methods {candidates}`：getattr(ContextInfo) 报告 + **script globals
  报告**（双注入面，对应 API 形态实证）——只读、绝不调用；
- `download_history_data {stockcode, periods, startTime, endTime}`：解析顺序
  **`globals().get("download_history_data")`（框架注入面）→
  `getattr(ContextInfo, ...)`（fallback）**，按 periods 顺序逐周期同步下载、
  逐周期状态汇总返回；
- **移除** `call_native` handler 与 `TRADING_DENY_PATTERNS`/
  `_NATIVE_METHOD_NAME_RE`（通用执行洞退役；v3.1 部署版含它，v3.2 覆盖时清掉）；
- `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.2`；
- 护栏不变：Python 3.6 + GBK + 无 threading + guardrail 测试。

### D4 busy_until（下载在途放行，机制沿用）

下载命令串行执行会阻塞桥主循环（心跳停摆）。datasource 在**发出每条 download
命令**时 `extend_busy_until(该命令超时 + 60s)`；owner 新鲜度评估
`stale if now > max(last_poll + 15s, busy_until)`；无在途时 15s 原判不变。
（`add-qmt-history-download` 前置 change `unify-terminal-admin-surface-guards`
的 call_native 亦复用；该 change 落地后其 call_native 随 REMOVED delta 退役，
busy_until 机制由本 change 的 download job 使用。）

### D5 降级与可观测

- job 计数器：`mist_datasource_qmt_history_download_total{result=ok|failed|
  in_session|disabled|unsupported}`（unsupported = 旧桥无 download 命令）；
- 提交被拒（盘中/非法参数）→ 有界 reason warn；桥执行失败 → 逐任务 failed 上报；
- job 全部完成后（聚合 all_done）**由 backend 轮询发现**并继续采集——datasource
  不反向回调 backend（少一个端点、更稳；轮询退避由 backend 控制）。

### D6 backend collector 三段编排（mist 仓）

- PostCloseSync / 手动 collect 流程前置：
  1. 统计缺失：按 (QMT 源标的 × 基础周期 × 目标窗) 查 k 表行数，枚举缺口；
  2. 有缺口 → 提交下载 job → 轮询（间隔 5–10s，预算 ≤ 下载超时）→ 完成/超时；
  3. 超时 → 既有 notReady/重试路径（数据可能已部分就位，下次轮询自愈）；
- 预算超时后仍提交下一轮晨间兜底（06:30）——既有重试结构复用；
- `DATASOURCE_HTTP_TIMEOUT_MS` 保持 30s 不动（bars/query 纯读；submit/poll
  轻调用另有短超时）。

### D7 TDX：下载端点（refresh_kline 定向下载）+ 纯读取（双源对称，用户决策）

- **TDX 下载端点**：`POST /v1/tdx/download`（`{stock_list, base_periods ⊆ {1m,5m,1d}}`）
  → 逐周期 `refresh_kline` → 逐周期状态返回；同步限时（实测 ~100ms，预算 600s）；
  symbol/period 校验前置；`raise_for_native_error` 适配 `ErrorId==0` 成功形状
  （实测 `Msg` 字段，文档样例为 `Error`——不依赖消息字段名）。
- **get_bars 保持纯读**（用户决策：双源对称，读取路径零下载副作用）——采集流程
  统一三段：统计缺失 → 下载（QMT job / TDX 端点）→ 读取。
- TDX refresh 无日期范围参数（终端托管下载范围）——已知限制，文档记录；对
  "补昨日/历史缺口"用途已实测够用（probe 闭环）。
- 无 TDX 桥改动：refresh_kline 走终端 HTTP（TdxHttpClient.call），TDX 桥
  （tqcenter 实时订阅）不参与。

### D8 范围与不变量

- bars/query **纯读取**（显式要求，双源对称：QMT 与 TDX 读取路径均零下载副作用）；
  夜间/晨间/手动 collect 同走三段流程；
- TDX 桥、实时链路、k 表数据：不动；
- `unify-terminal-admin-surface-guards` 已落地的 datasource-admin-surface
  （分类守卫 + busy_until + TDX raw）保留；本 change 携带其 QMT call_native
  的 REMOVED delta。

## 3. 风险与对策

| 风险 | 对策 |
|------|------|
| 桥内 `globals()` 无 download_history_data（版本差异） | introspect 双面探测先行；缺失 → job 失败 + 明确错误码（`QMT_DOWNLOAD_API_UNAVAILABLE`），不阻塞读取 |
| 下载阻塞桥主循环（串行、时长不可控） | 盘外执行（盘中提交被门禁拒）；busy_until 放行租约；job 串行限速 |
| backend 轮询风暴 | 轮询间隔 5–10s + 预算上限；超时走既有 notReady 重试路径 |
| 桥脚本 GBK 复制损坏 | 既有约定：手动 copy + 重启终端，禁 scp |
| QMT 下载无显式失败信号（原生返回 none） | 下载 best-effort；有效性由后续读取行数验证（失败即 notReady 既有路径） |
| TDX refresh_kline 首装大范围变慢 | 当前实测 ~100ms；若实测漂移 → 镜像 job 模型（本 change 不做） |

## 4. 部署序列（概要，细则见 tasks）

1. datasource 容器部署（download job 端点 + 桥 v3.2 + call_native 移除）；
2. backend 容器部署（collector 三段编排）；
3. 用户手动 copy 新 QMT 桥 v3.2 + 重启终端（避开交易时段）；TDX 无桥改动；
4. 验证：`bridgeBuildId=v3.2`、download job 实跑（000688 缺口补录）、
   bars/query 纯读确认、introspect 双面报告；
5. 次晨巡检卡核对：000688 转绿、整体 PASSED。