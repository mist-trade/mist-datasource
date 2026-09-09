# Design: add-qmt-history-download

## 1. 现状链路（取证 2026-09-09）

```
backend CollectorService.collectK / PostCloseSync
  → POST qmt-datasource /v1/...
→ QmtMarketOperations.get_bars (src/datasource/qmt/operations/market.py)
  → 桥命令 {method:"get_market_data_ex", params:{stock_list, period, start_time, end_time, ...}}
→ [终端内] mist_qmt_realtime_bridge._execute_history_command
  → ContextInfo.get_market_data_ex(...)   ← 只读终端本地缓存
→ 结果经命令网关返回，datasource 归一化后落库
```

问题：QMT 终端本地缓存的历史需要**显式下载**（`download_history_data`），实时订阅
推送不回填历史缓存。9/1 起缓存断供，`get_market_data_ex` 返回空 → 收盘同步 notReady
→ k 表缺口 + 巡检天天红。TDX 同理：历史就绪依赖操作员每晚手动盘后下载（2026-09-09
用户证实），手动未跑/晚于 22:30 的夜晚同步即空。

## 2. 关键决策

### D1 同步下载定案（用户决策 2026-09-09）+ 盘中硬门禁 + owner 租约按在途放行

**两源均按同步下载设计，异步视为不可用**（QMT 官方文档只记载同步版
`download_history_data`；`download_history_data2` 未见于 ContextInfo 文档，不作为
依赖）。同步下载会阻塞执行线程——接受此代价，边界与后果显式化：

- **阻塞范围**：QMT 桥主循环在下载期间停摆（心跳/命令轮询暂停）；TDX 侧终端 HTTP
  调用阻塞直至刷新完成（终端弹加载界面）。
- **恢复路径**（QMT）：阻塞结束 → 桥恢复轮询 → owner 重注册（generation++）→
  journal 对账。该链路与终端重启同构，生产已验证（9/1、9/8 重启自动恢复）。
- **盘中硬门禁（用户决策 2026-09-09）**：A 股活动时段内（复用既有
  `ActivityWindow`，默认 `09:15-11:30,13:00-15:00` UTC+8，env
  `MIST_ACTIVITY_WINDOWS` 同源）**禁止触发下载/刷新**——QMT 与 TDX 一律跳过，
  counter `result=in_session`，照常执行读取。盘中手动 collect 因此天然安全
  （不 stall 实时），代价是盘中采集拿不到历史（等同现状 notReady）。
- **owner 租约：按在途下载命令放行，不做全局阈值调整（用户决策 2026-09-09）**：
  死亡探测的本质 = 桥轮询（心跳）停摆 15s（`owner_stale_after_seconds`，
  `gateway.py:124`）即判 stale——但采集命令在途时的停摆是预期行为而非死亡，
  二者在心跳上不可区分。datasource 维护 per-source 的 `busy_until` 状态：
  发出 download 命令时 `busy_until = max(busy_until, now + 该命令超时 + 60s)`；
  owner 新鲜度评估改为 `stale if now > max(last_poll + 15s, busy_until)`。
  在途窗口内死亡探测自动放宽（仍有界）；**无下载在途时 15s 原判不变，真实死亡
  检测零损失**；`owner_stale_after_seconds` 本身不动。

### D2 编排放 datasource 侧，读 K 前限时等待（同步命令，无需迟到结果机制）

`get_bars` 流程变为：
1. 若 `*_HISTORY_*_ENABLED=on` 且不在盘中门禁窗口：发下载/刷新命令（**一次覆盖
   该标的全部基础周期**，见 D2a）；
2. 同步等待命令结果（datasource→桥/终端 HTTP 的读超时按下载预算放宽，
   `QMT_HISTORY_DOWNLOAD_TIMEOUT_MS` / `TDX_HISTORY_REFRESH_TIMEOUT_MS`，
   默认 600000，上限 1800000）；
3. 无论下载成败，**照常发读取命令**（降级 = 现状行为，只读本地缓存）。
   注：即使 datasource 超时放弃等待，桥/终端侧下载已完成、本地缓存已落，
   降级读取仍受益。

**简化**：命令结果与命令同轮返回（桥在轮询周期内同步执行），**不需要**迟到结果、
retained-result 关联、命令网关扩展——`download` 命令只是"耗时较长"的普通命令。

### D2a 下载粒度：每次触发下载全部基础周期（用户决策 2026-09-09）

下载触发时**一次下载该标的的全部基础周期 1m / 5m / 1d**（QMT 三次调用、TDX 三次
`refresh_kline`），而非按读取请求的周期映射：

- 30m 由 5m 合成、日线由 1d 存储（官方文档两源一致），全基础周期下载后任意周期
  读取都被覆盖，且后续任务命中缓存即快速返回；
- 去重：datasource 进程内 memo（symbol+basePeriod+range，TTL 约 10 分钟），
  同一同步轮内同标的的后续任务（4 任务/标的/夜）跳过重复下载
  （16 任务/夜 → 最多 12 次下载而非 48 次）；
- 下载范围 = 读取请求的 start/end（不额外外扩）。

### D3 降级矩阵（部署顺序无关化）

| 情形 | 行为 | 观测 |
|------|------|------|
| 下载完成 ok | 正常读取 | counter `result=ok` |
| 下载超时（datasource 放弃等待，终端侧可能已完成） | 照常读取 | counter `result=timeout` + warn（reason=download_timeout） |
| 下载命令失败 | 照常读取 | counter `result=failed` + warn（原生错误进 error 字段） |
| 旧桥不支持（QMT_COMMAND_UNSUPPORTED） | 照常读取 | counter `result=unsupported` + 启动后首次 warn |
| **盘中（ActivityWindow 内）** | **跳过下载/刷新，照常读取** | counter `result=in_session` |
| 开关 off | 不发下载命令 | counter `result=disabled` |

因此 **datasource 先部署、桥后更新，任何顺序都不破坏现状**。

### D4 配置

- `QMT_HISTORY_DOWNLOAD_ENABLED` / `TDX_HISTORY_REFRESH_ENABLED`：`on`/`off`，
  默认 `on`（独立 kill-switch，免重启回滚）。
- `QMT_HISTORY_DOWNLOAD_TIMEOUT_MS` / `TDX_HISTORY_REFRESH_TIMEOUT_MS`：
  默认 `600000`（10 分钟，覆盖首装大范围下载），上限 `1800000`；
  TDX 预算覆盖至多三次顺序刷新（单次超时即短路跳过余下）。
- `owner_stale_after_seconds` 保持 15s 不动（在途下载由 `busy_until` 放行，
  见 D1）。
- 不设 shadow 模式（确定性逻辑变更，降级路径即天然回退）。

### D5 范围

- QMT 与 TDX **都在范围内**；只挂各自 `get_bars`（采集路径）；实时 WS/订阅链路
  不经过它，零影响。
- 手动 `/v1/collector/collect` 与夜间/晨间同步同走此路径，自动受益。
- TDX 无桥脚本改动（refresh_kline 走终端 HTTP 通道，见 D8）。

### D6 QMT 桥护栏（guardrails 全部继续适用）

- Python 3.6 + `# coding:gbk`（`| None` / f-string=`/ dataclass 等新语法禁用）；
- 禁 `threading` import；
- `bridgeBuildId` → `mist-qmt-realtime-bridge-v3.1`（health 可见，部署验证依据）；
- 新增 handler 纳入既有 `test_bigqmt_bridge_guardrails.py` 约束；
- `_compute_runtime_fingerprint` 的函数名清单不改：`_execute_history_command`
  字节码变化自然驱动 fingerprint 更新。

### D7 可观测性

- 计数器（按源独立，result 六态）：
  - `mist_datasource_qmt_history_download_total{result=ok|timeout|failed|unsupported|in_session|disabled}`
  - `mist_datasource_tdx_history_refresh_total{result=ok|timeout|failed|unsupported|in_session|disabled}`
- warn 日志：判断点（timeout/failed/unsupported）各一条，reason 用有界枚举，
  原生错误只进 `error=` 字段；info 生命周期日志（下载/刷新开始/完成耗时）。

### D8 TDX：refresh_kline 前置（admin 设计补全，官方文档已核实 + 生产实测）

**官方语义**（help.tdx.com.cn ctx.stock.md，2026-09-09 核对）：

> "根据股票和周期刷新历史K线缓存，**如果本地没有下载完整的日线等数据，则可以调用
> 这个函数定向下载**某些品种某些周期的历史K线数据"

- 签名：`refresh_kline(stock_list: List[str], period: str)`；period **只支持
  `1d`/`1m`/`5m`**，其它周期由这三种生成 → 按用户决策每次触发顺序调三次
  （1m → 5m → 1d）。
- **阻塞式**（原文）："使用后会在客户端弹出刷新数据的加载界面，**加载完成后才会有
  返回**" → datasource 限时等待；TDX 采集管线内**顺序执行、不并发轰终端**。
- **盘中限制**（原文）："如果在盘中交易时间段下载 1m 和 5m 分钟线，只能下载到截止
  上个交易日的数据"——与用途匹配（历史采集针对既往交易日）。
- **响应形状**：成功返回 `{"ErrorId": "0", "Msg": "refresh kline cache success.",
  "run_id": "-99"}` —— **成功以 `ErrorId==0` 判定**；消息字段实测为 `Msg`
  （官方文档样例写的是 `Error`，以实测为准，归一化不依赖消息字段名），
  否则会把成功误判为失败（`raise_for_native_error` 需适配此形状）。
- **生产实测证据（2026-09-09 01:34，`/v1/raw/tdx/call`）**：
  `refresh_kline({stock_list:["000688.SH"], period:"1m"})` → 92ms、ErrorId=0；
  随后 raw `get_market_data`（1m，20260908 当日）返回 **240 根完整日线内分钟条**
  （09:31:00–15:00:00）——该数据此前在 QMT/TDX 采集侧均为空，**"刷新→缓存填充→
  可读"链路实证闭环**；5m 同样验证（121ms + 缓存可读，KlineTotal 8113）。
- **无桥脚本改动**：TDX 历史走终端 HTTP（`TdxHttpClient.call`），`refresh_kline` 是
  同通道的另一个 method call；TDX 桥（tqcenter 实时订阅）不参与，部署仅 datasource
  容器。

## 3. 风险与对策

| 风险 | 对策 |
|------|------|
| 同步下载阻塞 QMT 桥主循环（用户知情接受） | 仅采集管线触发；定时任务在盘外；**盘中硬门禁直接禁止**；超时上限 1800s；owner stale→重注册→journal 对账为已验证恢复路径 |
| 下载在途期 owner 心跳停摆被误判死亡 | `busy_until` 按在途命令放行（D1），`owner_stale_after_seconds` 15s 不动；OO 告警规则复核兜底 |
| 盘中手动 collect | **硬门禁**：跳过下载/刷新（counter `in_session`），读取照常，无 stall |
| 下载拖长收盘同步（16 任务 × 3 周期） | 进程内 memo 去重（D2a）；单命令限时；超时降级读取 |
| 桥脚本 GBK 复制损坏 | 部署手册沿用既有约定：用户手动 copy + 重启终端，禁 scp |
| QMT 下载失败无显式错误（原生返回 none） | 下载为 best-effort；有效性由后续读取行数验证（失败即 notReady 既有路径） |
| TDX `refresh_kline` 实测与文档不符 | 已生产实测吻合（D8 证据）；若后续版本行为漂移，回退 `refresh_cache` 或仅降级读取，delta 随结论微调 |

## 4. 部署序列（概要，细则见 tasks）

1. datasource 容器部署（QMT/TDX 下载前置 + 降级路径 + busy_until 放行；旧 QMT 桥下
   自动 unsupported 降级，TDX 直接生效）；
2. 用户手动 copy 新 QMT 桥脚本进终端 + 重启终端（避开交易时段）；TDX 无桥改动；
3. 验证：health `bridgeBuildId=v3.1`、两侧计数器 ok、实跑 QMT/TDX 各一次历史采集、
   复核夜间告警（无 stale 假告警）；
4. 补录 000688 的 14 条缺口；次晨巡检卡核对转绿。