# Tasks: unify-terminal-admin-surface-guards

## 1. 共享治理与守卫基础设施

- [x] 1.1 `[mist-datasource]` 分类映射：`src/datasource/tdx/classification.py`
  （tqcenter 面，源 coverage 文档，约 40 项）+ `src/datasource/qmt/classification.py`
  （ContextInfo 面，首版保守：确认安全的方法 + 显式录入交易/账户方法），
  同构结构、逐项文档锚点注释。
- [x] 1.2 `[mist-datasource]` 共享守卫组件 `src/datasource/admin/guard.py`：
  三段 fail-closed（unclassified / family-forbidden / allow），按源实例化。
- [x] 1.3 `[mist-datasource]` `busy_until` 租约放行：per-source 状态、
  `max(last_poll+15s, busy_until)` 评估接入 `src/datasource/qmt/realtime/gateway.py`
  （`_owner_is_stale` + `health()` ownerStale 同一判定）；
  `owner_stale_after_seconds` 保持 15s。
- [x] 1.4 `[mist-datasource]` 可观测性：`mist_datasource_admin_call_total{source,
  method,result}`（method 基数有界）+ info/warn 结构化日志。
- [x] 1.5 `[mist-datasource]` 配置：`QMT_ADMIN_CALL_TIMEOUT_MS` /
  `TDX_ADMIN_CALL_TIMEOUT_MS`（默认 600000，上限 1800000，配置校验）。

## 2. QMT 侧：call_native（本 change 仅此一个新命令）

- [x] 2.1 `[mist-datasource]` 桥新增 `call_native` 命令：schema 校验、**一行交易
  硬拒**（passorder 等交易/账户模式，静态元组，startswith 匹配）→
  `getattr(ContextInfo, method)` 执行；`bridgeBuildId` →
  `mist-qmt-realtime-bridge-v3.1`。
- [x] 2.2 `[mist-datasource]` datasource 侧 `admin_call_native`：guard.evaluate →
  拒则抛 → `extend_busy_until(timeout + 60)` → `enqueue("call_native", ...)` →
  既有轮询模式取结果（超时 `QMT_ADMIN_CALL_TIMEOUT`）。
- [x] 2.3 `[mist-datasource]` admin 路由：`POST /v1/raw/qmt/call`
  （guard + busy_until + 六态计数）。
- [x] 2.4 `[mist-datasource tests]` 单测：六态 + 交易硬拒独立生效 + busy_until
  （在途不误判/到期判死/幂等取 max）+ guardrail（Python 3.6/GBK/无 threading）+
  集成（命令同轮返回）。

## 3. TDX 侧：raw_call 守卫 v2

- [x] 3.1 `[mist-datasource]` `raw_call` 接入守卫（替换
  `FORBIDDEN_RAW_METHODS`/prefixes）；未分类/拒绝族两段判定；桥零改动。
- [x] 3.2 `[mist-datasource tests]` 单测：放行（get_market_data/refresh_kline/
  refresh_cache）、未分类拒绝、Do-Not-Expose 章节逐方法拒绝、前缀绕过
  （大小写/空白规范化）拒绝。

## 4. 部署与联动

- [x] 4.1 `[mist-datasource]` CI 全绿（pyright/pylint 全仓 + 单测 + 集成）；
  compose/env 增加 `QMT_ADMIN_CALL_TIMEOUT_MS`/`TDX_ADMIN_CALL_TIMEOUT_MS`
  （mist-deploy defaults + test 断言，参照 NOTIFICATION_CHANNELS 模式）。
- [ ] 4.2 `[deploy]` 部署 datasource 容器（TDX raw 守卫即时生效；QMT admin 路由
  就绪待 v3.1 桥）。
- [ ] 4.3 `[hil]` 用户手动 copy 新 QMT 桥（v3.1，仅 call_native）+ 重启终端
  （避开交易时段）；验证 `bridgeBuildId=v3.1`、实时流无中断。
- [ ] 4.4 `[hil]` 验证矩阵：TDX raw 放行（get_market_data/refresh_kline/
  refresh_cache）、未分类拒、拒绝族拒；QMT call_native 实跑（分类安全方法）；
  busy_until（在途不误判死亡）。
- [ ] 4.5 `[mist-datasource]` 联动：`add-qmt-history-download` 接力（其 v3.2 桥
  携带 introspect_methods + download_history_data；其 task 1.5 转验收本 change 的
  busy_until 行为）。
