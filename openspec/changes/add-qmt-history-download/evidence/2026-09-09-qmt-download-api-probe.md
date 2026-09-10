# Evidence: QMT download_history_data API 形态 probe（task 2.4 前置）

- 时间：2026-09-09 晚（生产，/v1/raw/qmt/call → 桥 v3.1 call_native）
- 目的：验证 `download_history_data` 在 QMT 终端的可达形态

## 结果

`call_native {method: "download_history_data", kwargs: {stockcode: "000688.SH",
period: "1m"/"5m"/"1d", startTime/endTime}}` × 3 → 全部返回

```
QMT_ADMIN_METHOD_UNKNOWN: ContextInfo has no such method
```

（三次一致，nativeError 即 getattr(ContextInfo, "download_history_data") 失败）

## 结论

1. **终端 `ContextInfo` 上没有 `download_history_data`**（三周期一致，非偶发）。
2. 官方文档示例本身是**裸函数调用**（`def init(C): download_history_data(...)`，
   非 `C.download_history_data(...)`）——该 API 是 QMT 框架注入到**策略脚本全局
   命名空间**的函数，与 ContextInfo 方法分属两个注入面。
3. 触发 D1 决策门：`call_native` 的 `getattr(ContextInfo, method)` 契约**不可达**
   此 API。设计修订（已回写 design D1/D2）：v3.2 的 download handler 改为解析
   **裸全局**（`globals().get("download_history_data")`，ContextInfo getattr 作
   fallback）；introspect 探测面同步扩展（ContextInfo attrs + script globals）。
4. 可用性的终证 = v3.2 桥上实跑 download 命令（handler 自报 API 缺失与否）。

## 顺带发现

- `get_local_data` 经 call_native 可执行（ContextInfo 方法，kwargs 调用 ok）——
  call_native 机制本身工作正常，排除了通道问题。
