# Design: unify-terminal-admin-surface-guards

## 1. 现状盘点（取证 2026-09-09）

| | QMT | TDX |
|---|---|---|
| 终端内宿主 | QMT 策略脚本环境（`ContextInfo`，**含 passorder 交易面**） | TdxW PYPlugins（`tqcenter`，实时订阅 SDK） |
| 实时通道 | 桥 TCP 直推（9003→容器9004） | 桥 TCP 直推（:9003） |
| 历史/数据通道 | **桥命令轮询**（同一桥，白名单守卫在桥 handler） | **终端 HTTP 17709**（TdxW 原生，独立于桥） |
| admin 逃生口 | 无 | `/v1/raw/tdx/call`（黑名单守卫在 datasource） |
| 生产守卫 | 桥 handler 白名单 | 隐式白名单（`TdxMarketOperations` 写死方法 + 类型化模型） |

结论：传输由终端决定，**无法也不应强行一致**；但治理模型（分类源、守卫判定）、
执法层职责**可以且应该完全对称**。

## 2. 关键决策

### D1 治理源：每源一份 checked-in 分类映射（同构）

| | QMT 分类映射 | TDX 分类映射 |
|---|---|---|
| 方法面来源 | thinktrader 官方文档字典（ContextInfo 行情/交易/账户/…） | `docs/references/tdxquant-interface-coverage.md`（tq 方法面，约 40 项） |
| 拒绝族 | **trading / account**（`passorder` 显式录入） | **trading / account / execution**（coverage "Do Not Expose" 章节） |
| 结构 | `method → {family}`，逐项带文档锚点注释 | 同左 |

- 两份映射同构（同一 dataclass/结构），同一更新流程：**先改治理文档 → 再改映射**
  （两步、可 review）；
- checked-in 常量（运行时不解析 markdown），同步测试锁定与文档的对应关系；
- QMT 首版保守：仅录入已确认安全的 market/reference 方法 + 显式录入已知交易/
  账户方法；其余不录入（= unclassified 拒绝），随 probe 逐个升级。

### D2 共享三段 fail-closed 守卫（一个组件，两源实例）

`src/datasource/admin/guard.py`：
```
guard.evaluate(source, method):
  1. method ∉ 分类映射        → deny(METHOD_UNCLASSIFIED)   # 强制先治理后暴露
  2. family ∈ 拒绝族          → deny(METHOD_FAMILY_FORBIDDEN)  # 与任何开关无关
  3. else                     → allow
```
- TDX：`raw_call` 接入守卫（替换 `FORBIDDEN_RAW_METHODS`/prefixes 黑名单）；
  行为变化 = 原先可调的未分类方法被拒——**这是目的**。
- QMT：`call_native` 命令发送前过同一守卫。

### D3 对称执法（形状一致，传输各用原生）

- **TDX**：既有 `raw_call` 换新守卫（D2）。TdxW HTTP 为封闭服务，终端侧无法加
  守卫——**TDX 执法仅 datasource 一层，属终端约束而非设计选择**。
- **QMT**：新增桥命令 `call_native {method, params}` →
  datasource 分类守卫（**单层执法**）+ **桥内一行交易硬拒**（`passorder` 等交易/
  账户模式，静态元组，startswith 匹配）→ `getattr(ContextInfo, method)` 执行。
- **半通用入口 = 已确认的设计偏离（用户认可 2026-09-09）**：既有桥逐命令硬编码，
  `call_native` 是第一个参数形状不逐方法建模的入口——以"datasource 分类守卫 +
  桥内交易硬拒 + 结果 JSON 安全化 + 不承担订阅类职责"为边界。收益：探索性方法
  无需发桥版本，显著降低桥重发版频率。
- **安全前提（tripwire）**：执行面的安全性依赖**终端未开通交易权限**（2026-09-09
  用户证实当前状态）。未来任一终端开通交易权限前，必须先在桥内补交易拒列表/
  白名单——作为变更前置条件。

### D4 owner 租约按在途命令放行（busy_until）

`call_native` 同步执行会阻塞桥主循环（心跳停摆），与"终端死亡"在心跳上不可区分。
datasource 维护 per-source `busy_until`：
- 发出长耗时命令时 `busy_until = max(busy_until, now + 该命令超时 + 60s)`；
- owner 新鲜度评估：`stale if now > max(last_poll + 15s, busy_until)`；
- 超过 busy_until 无轮询 → 照常判 stale（租约释放 → 重注册 → journal 对账，
  已验证恢复路径）；
- **无在途命令时 15s 原判不变，死亡检测零损失**；
- `owner_stale_after_seconds` 参数本身不动。
`add-qmt-history-download` 的下载命令复用此机制（其 task 1.5 在实施时改为验收
本 change 落地的行为）。

### D5 降级与超时（admin 面）

- `QMT_ADMIN_CALL_TIMEOUT_MS` / `TDX_ADMIN_CALL_TIMEOUT_MS`：默认 `600000`，
  上限 `1800000`（首装/大范围操作可能很慢）；
- 超时 → 命令结果放弃等待（终端侧副作用可能已发生，如实返回 timeout + warn）；
- 计数器与 history-download 对齐：
  `result=ok|timeout|failed|denied_unclassified|denied_forbidden|disabled`；
  **执行类 admin 调用在 ActivityWindow 内会附加 warn**（提醒正在阻塞实时桥）；
  admin 面不做硬性盘中门禁（操作员显式行为，多在盘外排障；硬门禁属于
  `add-qmt-history-download` 的采集自动路径）。

### D6 QMT 桥护栏（本 change 仅 call_native）

- Python 3.6 + `# coding:gbk`（新语法禁用）；禁 `threading` import；
- `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.1`（health 可见，部署验证依据）；
- 新增 handler 纳入既有 `test_bigqmt_bridge_guardrails.py` 约束；
- `_compute_runtime_fingerprint` 的函数名清单不改，handler 字节码变化自然驱动
  fingerprint 更新。

### D7 可观测性

- 计数器：`mist_datasource_admin_call_total{source, method, result}`（method 基数
  有界：仅分类表内方法名；未分类记 `method="unclassified"`）。
- 结构化日志：info（method/耗时/结果规模有界）+ 拒绝 warn（reason 有界）。
- admin 路由保持 compose 网内，宿主端口面不变。

### D8 范围与不变量

- 生产数据通道：QMT 桥白名单、TDX 类型化调用——**不动**；
- TDX 桥（tqcenter 实时订阅）：**无改动**；
- 采集行为/k 表：**无改动**；
- **归后续 change**：`introspect_methods` 与 `download_history_data` 桥命令、
  datasource 下载/刷新编排 → `add-qmt-history-download`（其桥发版 v3.2 一次
  携带两命令；自省服务其 task 2.4 可用性探测）；本 change 先行，其 busy_until
  由该 change 验收复用。

## 3. 风险与对策

| 风险 | 对策 |
|------|------|
| QMT `call_native` 执行面被滥用（passorder 等） | datasource 分类守卫（未分类/拒绝族拒）+ **桥内一行交易硬拒** + 内网私有 + 限时；guardrail 测试锁定 |
| 终端未来开通交易权限 | tripwire 已写入 spec：开权限前必须先补桥内交易拒列表/白名单（变更前置条件） |
| 分类映射与治理文档漂移 | 同步测试（方法数/分类抽查对照文档锚点）；两步更新流程 |
| 未分类拒绝打断既有排障习惯 | QMT 首版保守分类本就无既有习惯；TDX 已知在用方法均有分类，真遇未分类 → 走"先分类再用"一次性成本 |
| 长耗时 admin 命令阻塞桥主循环 | busy_until 放行 + 超时上限 1800s + 操作员多在盘外排障；恢复路径已验证 |
| 桥脚本 GBK 复制损坏 | 部署手册沿用既有约定：用户手动 copy + 重启终端，禁 scp |
| QMT 下载类执行无显式错误（原生返回 none） | admin 执行为 best-effort；结果如实返回由操作员判读 |

## 4. 部署序列（概要，细则见 tasks）

1. datasource 容器部署（守卫组件 + 分类映射 + busy_until + QMT admin 路由；
   TDX raw 守卫即时生效）；
2. 用户手动 copy 新 QMT 桥（v3.1：仅 call_native）+ 重启终端（避开交易时段）；
   TDX 无桥改动；
3. 验证：health `bridgeBuildId=v3.1`、TDX raw 守卫矩阵（放行/未分类拒/拒绝族拒）、
   QMT call_native 实跑、busy_until 行为（在途不误判死亡）；
4. 接力：`add-qmt-history-download`（v3.2 桥 + 下载编排 + refresh 前置）。