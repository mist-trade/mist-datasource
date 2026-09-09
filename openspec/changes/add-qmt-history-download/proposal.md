# Proposal: add-qmt-history-download

## Why

2026-09-08/09 生产数据缺口审计实锤：**两个终端的历史 K 线都依赖显式下载，而采集
从不触发下载**——

- **QMT**：`get_market_data_ex` 只读终端本地缓存，从不触发下载。9/1 起缓存断供 →
  000688 缺 14 条 K 无法补录。
- **TDX**：历史就绪依赖**操作员每晚手动盘后下载**（2026-09-09 用户证实）。手动下载
  未跑/晚于 22:30 同步时点的夜晚（9/2、9/4、9/7、9/8），000001/399006/880003 的盘中 K
  全部缺失，盘前巡检 klines 维度天天红。8/20–8/31 的完整只是手动习惯恰好覆盖。

tqcenter 接口覆盖文档确认 TDX 存在可编程触发点：**`refresh_kline`**（ctx.stock.md
官方方法，现分类 `admin-only` 未暴露）——本 change 即完成其 admin 设计（仅限采集
管线内部使用，不新增公共端点）。TDX 侧已生产实测闭环（2026-09-09：refresh 后
000688 9/8 的 1m 240 根可读，此前任何来源均取不到）。

## What Changes

- **QMT 桥侧**（`qmt/builtin_bridge/mist_qmt_realtime_bridge.py`，Python 3.6 + GBK）：
  新增同步下载命令，一次顺序调用原生 `download_history_data` 下载该标的全部基础
  周期（1m/5m/1d，30m 由 5m 合成）。**同步阻塞桥主循环为已接受的代价**（用户决策
  2026-09-09：异步视为不可用），边界与恢复路径显式化（见 design D1）。
- **QMT datasource 侧**（`QmtMarketOperations.get_bars`）：读 K 前发下载命令、限时
  等待（默认 600s），随后照常 `get_market_data_ex` 读本地；进程内 memo 去重。
- **盘中硬门禁**（用户决策）：A 股活动时段（复用 `ActivityWindow`，默认
  `09:15-11:30,13:00-15:00` UTC+8）内**禁止触发下载/刷新**（counter `in_session`），
  读取照常——盘中手动 collect 天然安全，不 stall 实时。
- **owner 租约按在途命令放行**（用户决策）：datasource 维护 per-source
  `busy_until`，下载在途期间 owner 新鲜度按 `max(last_poll+15s, busy_until)` 评估；
  **无下载在途时 15s 死亡检测不变**，`owner_stale_after_seconds` 不动。
- **TDX datasource 侧**（`TdxMarketOperations.get_bars`）：读 K 前经终端 HTTP 顺序
  调 `refresh_kline` 三次（1m/5m/1d，限时、best-effort），随后照常 `get_market_data`。
  无桥脚本改动（TDX 桥只管实时）。
- **两侧统一降级矩阵**（六态：ok/timeout/failed/unsupported/in_session/disabled）：
  一切异常 → **优雅降级**为现状行为（直接读），附有界 reason 的 warn 与结果计数器。
- **不做**：不做 shadow 观察（确定性逻辑变更，设计与单测保证）；不做任何 k 表数据
  规范化（用户已拍板，接缝由消费方处理）。

## Capabilities

### 新增 capability：`qmt-market-history`

- K 线读取前同步下载全部基础周期（限时、优雅降级、memo 去重）
- 盘中硬门禁；主循环阻塞有界、恢复路径自动（owner 重注册 + journal 对账）
- owner 租约按在途命令放行，死亡检测平时不变
- 下载结果可观测（计数器 + 有界 reason warn）

### 新增 capability：`tdx-market-history`

- K 线读取前经终端 HTTP 顺序 `refresh_kline` 三基础周期（限时、best-effort、优雅
  降级、盘中门禁）
- 刷新结果可观测；不新增公共端点（仅采集管线内部）

## Impact

- `src/datasource/qmt/operations/market.py`（下载前置编排 + memo + 降级）
- `src/datasource/qmt/realtime/gateway.py`（owner 新鲜度评估接入 `busy_until`）
- `src/datasource/tdx/operations/market.py`（refresh_kline 前置）
- `qmt/builtin_bridge/mist_qmt_realtime_bridge.py`（同步下载命令 handler）
- 新增配置：`QMT_HISTORY_DOWNLOAD_ENABLED` / `TDX_HISTORY_REFRESH_ENABLED`
  （各自默认 on）+ `QMT_HISTORY_DOWNLOAD_TIMEOUT_MS` /
  `TDX_HISTORY_REFRESH_TIMEOUT_MS`（默认 600000，上限 1800000）
- QMT 桥 `bridgeBuildId` v3.0 → v3.1；**QMT 桥部署需用户手动 copy（GBK，禁 scp）+
  重启终端；TDX 无桥改动，仅 datasource 容器部署**
- backend（mist 仓）零改动；补录 000688 的 14 条为部署后运维动作
