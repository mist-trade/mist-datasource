# Tasks: add-qmt-history-download

## 1. datasource 侧：QMT 下载编排与降级

- [ ] 1.1 `[mist-datasource]` `QmtMarketOperations.get_bars` 前置编排：发同步下载命令
  （一次覆盖 1m/5m/1d，范围取自请求），限时等待结果，随后照常读取；
  读 `QMT_HISTORY_DOWNLOAD_ENABLED` / `QMT_HISTORY_DOWNLOAD_TIMEOUT_MS`。
- [ ] 1.2 `[mist-datasource]` 进程内 memo 去重（symbol+basePeriod+range，TTL ≈10min），
  同一采集轮内同标的后续任务跳过重复下载。
- [ ] 1.3 `[mist-datasource]` 降级矩阵落地（ok/timeout/failed/unsupported/in_session/
  disabled），计数器 `mist_datasource_qmt_history_download_total{result}` + 有界
  reason warn（unsupported 仅首次告警）；datasource→桥命令读超时对 download 命令按
  下载预算放宽。
- [ ] 1.4 `[mist-datasource]` **盘中硬门禁**：复用 `ActivityWindow`
  （`09:15-11:30,13:00-15:00` UTC+8，env `MIST_ACTIVITY_WINDOWS` 同源），窗口内跳过
  下载（counter `in_session`）、读取照常——盘中手动 collect 天然安全。
- [ ] 1.5 `[mist-datasource]` **owner 租约按在途下载放行**：机制由前置 change
  `unify-terminal-admin-surface-guards`（task 1.3）落地（per-source `busy_until`、
  `stale if now > max(last_poll+15s, busy_until)`、`owner_stale_after_seconds`
  保持 15s）；本任务仅**验收**：下载命令在途期间不误判死亡、超时后恢复正常判定。
- [ ] 1.6 `[mist-datasource tests]` 单测：下载 ok/超时/失败/旧桥 unsupported/盘中
  in_session/开关 off 六条路径 + memo 去重行为 + **busy_until 放行与到期判死**；
  降级后读取行为与现状逐字段一致；超时后仍受益于终端侧已落缓存。

## 2. 桥侧：introspect_methods + download_history_data（v3.2 一次发版）

- [ ] 2.1 `[mist-datasource]` 桥新增两个命令 handler：
  - `introspect_methods`：candidates 校验（≤32、标识符正则）、
    `getattr(ContextInfo, name, None)` 只读报告（available/type/doc 有界）、
    **绝不调用**（服务本 change task 2.4 的可用性探测）；
  - `download_history_data`：参数校验（stockcode/periods/start_time/end_time），
    顺序调用原生 `download_history_data` 三次（1m/5m/1d，显式起止时间），
    汇总每周期完成状态返回；
  `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.2`
  （v3.1 = 前置 change `unify-terminal-admin-surface-guards` 的 call_native）。
- [ ] 2.2 `[mist-datasource tests]` guardrail：两个新 handler 通过
  `test_bigqmt_bridge_guardrails.py`（Python 3.6 语法、GBK、无 threading）。
- [ ] 2.3 `[mist-datasource tests]` 集成：命令结果同轮返回（无迟到结果机制）；
  download/introspect 执行期间桥主循环阻塞、完成后恢复轮询的行为建模。
- [ ] 2.4 `[hil]` QMT 可用性探测：经 v3.2 桥 `introspect_methods` 实测
  `download_history_data` 在终端 `ContextInfo` 的存在性与签名（记录证据）；
  若终端无此方法 → 按 design D1 决策门回本 change 讨论，不擅自接受主循环阻塞。

## 3. TDX 侧：refresh_kline 前置

- [ ] 3.1 `[mist-datasource]` 生产 probe（`/v1/raw/tdx/call`，文档已定型语义，probe
  只实测）：单标的单周期延迟（定 timeout 默认值）、盘中行为抽查、`ErrorId` 形状
  确认；异常则按 D8 回退（`refresh_cache` 或仅降级读取）并修订 tdx delta。
- [ ] 3.2 `[mist-datasource]` `TdxMarketOperations.get_bars` 前置编排：顺序三次
  `client.call("refresh_kline", ...)`（1m/5m/1d，各自限时）→ 照常 `get_market_data`；
  读 `TDX_HISTORY_REFRESH_ENABLED` / `TDX_HISTORY_REFRESH_TIMEOUT_MS`；
  memo 去重与 QMT 同构。
- [ ] 3.3 `[mist-datasource]` 降级矩阵落地（ok/timeout/failed/unsupported/in_session/
  disabled），计数器 `mist_datasource_tdx_history_refresh_total{result}` + 有界
  reason warn（unsupported 仅首次告警）；**`raise_for_native_error` 适配
  `ErrorId==0` 成功形状**（官方响应把成功信息放在 `Error` 字段）；不新增公共端点；
  盘中硬门禁与 QMT 同构（复用 `ActivityWindow`）。
- [ ] 3.4 `[mist-datasource tests]` 单测：六条降级路径（含 in_session）+ 端点面不变
  （OpenAPI snapshot 无新公共路由）+ 三周期顺序执行与超时短路。

## 4. 部署与验证

- [ ] 4.1 `[mist-datasource]` CI 全绿（pyright/pylint 全仓 + 单测 + 集成）；
  compose/env 增加 `QMT_HISTORY_DOWNLOAD_ENABLED`/`QMT_HISTORY_DOWNLOAD_TIMEOUT_MS`/
  `TDX_HISTORY_REFRESH_ENABLED`/`TDX_HISTORY_REFRESH_TIMEOUT_MS`
  （mist-deploy defaults + test 断言，参照 NOTIFICATION_CHANNELS 模式）。
- [ ] 4.2 `[deploy]` 部署 datasource 容器（旧 QMT 桥下验证 unsupported 降级 + 计数器；
  TDX refresh 直接生效验证）。
- [ ] 4.3 `[deploy]` 复核 busy_until 放行与 OO 告警规则：采集夜下载在途期间不得产生
  owner-stale/ws-disconnect 假告警；无下载在途时 15s 死亡检测不变；盘中实时监测
  仍由快照 `StallDetector` 覆盖。
- [ ] 4.4 `[hil]` 用户手动 copy 新 QMT 桥脚本（GBK，禁 scp）+ 重启 QMT 终端（避开交易
  时段）；验证 health `bridgeBuildId=v3.1`、实时流无中断。
- [ ] 4.5 `[hil]` 实跑验证：QMT 000688 历史采集 count>0（counter ok）；TDX 任一标的
  历史采集 counter ok；夜间采集后复核无假告警；盘中手动 collect 验证 in_session 门禁。
- [ ] 4.6 `[ops]` 补录 000688 的 14 条缺口（5m/30m × 9/1–9/8、日线 × 9/4–9/8、
  1m × 9/8，逐日逐周期 collect）；k 表矩阵核对。
- [ ] 4.7 `[ops]` 次晨 09:05 巡检卡核对：000688 转绿、整体 PASSED（或仅剩真实异常）。
