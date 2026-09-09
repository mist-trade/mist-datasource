# Specification: tdx-market-history

## ADDED Requirements

### Requirement: TDX bar reads trigger a bounded synchronous refresh of all base periods first

The TDX market operations SHALL, before every `get_market_data` bar read and
when `TDX_HISTORY_REFRESH_ENABLED=on`, issue sequential `refresh_kline` calls
covering ALL base periods (`1m`, `5m`, `1d` — one call per period, per the
official doc only these three are supported and other periods are generated
from them) for the requested symbols, and SHALL bound each call's wait. The
refresh blocks the terminal until completion (loading UI) and, during trading
hours, minute downloads only reach the previous trading day. The read MUST
proceed regardless of the refresh outcome. The refresh MUST only be invoked
from the collection pipeline internals — no new public endpoint SHALL be added.

#### Scenario: Refresh completes before the read

- **WHEN** `get_bars` is invoked with `TDX_HISTORY_REFRESH_ENABLED=on`
- **AND** all `refresh_kline` calls report success (`ErrorId == 0`) within
  `TDX_HISTORY_REFRESH_TIMEOUT_MS`
- **THEN** the datasource MUST issue the `get_market_data` read afterwards
- **AND** `mist_datasource_tdx_history_refresh_total{result="ok"}` MUST be incremented

#### Scenario: All base periods are refreshed in one trigger

- **WHEN** a refresh trigger is issued for symbols and a date range
- **THEN** `refresh_kline` MUST be called sequentially for base periods
  `1m`, `5m`, and `1d` (synthetic periods such as `30m` are covered by `5m`)

#### Scenario: Success response shape is normalized by ErrorId

- **WHEN** the terminal responds with
  `{"ErrorId": "0", "Msg": "refresh kline cache success.", "run_id": ...}`
  (production-verified 2026-09-09; the official doc sample names the message
  field `Error` but the runtime field is `Msg`)
- **THEN** the datasource MUST classify it as success by `ErrorId == 0` and MUST
  NOT depend on the message field name
- **AND** it MUST NOT be counted as a failure

#### Scenario: Production evidence — refresh populates previously missing data

- **WHEN** `refresh_kline` is invoked for a symbol/period/date whose data was
  previously absent from all collection sources
  (verified 2026-09-09: `refresh_kline(["000688.SH"], "1m")` → 92ms,
  ErrorId=0; subsequent raw `get_market_data` for 2026-09-08 returned 240
  complete 1m bars, 09:31:00–15:00:00)
- **THEN** the terminal local cache MUST serve the previously missing bars to
  subsequent reads

#### Scenario: Refresh times out and the read degrades gracefully

- **WHEN** a `refresh_kline` call does not complete within the timeout
- **THEN** the datasource MUST abandon that call, skip remaining refresh calls,
  and still issue the `get_market_data` read
- **AND** `mist_datasource_tdx_history_refresh_total{result="timeout"}` MUST be incremented
- **AND** a warn log line MUST be emitted with the bounded reason `refresh_timeout`

#### Scenario: Refresh fails natively

- **WHEN** the terminal returns a native error for `refresh_kline`
- **THEN** the datasource MUST still issue the `get_market_data` read
- **AND** `mist_datasource_tdx_history_refresh_total{result="failed"}` MUST be incremented
- **AND** a warn log line MUST be emitted with bounded reason `refresh_failed`;
  the native error text MUST only appear in the structured `error=` field

#### Scenario: Terminal does not support the method

- **WHEN** the terminal rejects `refresh_kline` as unknown/unsupported
- **THEN** the datasource MUST skip the refresh and issue the read directly
- **AND** `mist_datasource_tdx_history_refresh_total{result="unsupported"}` MUST be incremented
- **AND** the first occurrence MUST emit a warn log with bounded reason
  `terminal_unsupported` (subsequent occurrences MUST NOT re-warn per request)

#### Scenario: In-session reads are gated from refreshing

- **WHEN** a bar read occurs inside the A-share activity window
  (`ActivityWindow`, default `09:15-11:30,13:00-15:00` UTC+8)
- **THEN** no `refresh_kline` call MUST be made
- **AND** `mist_datasource_tdx_history_refresh_total{result="in_session"}` MUST be incremented
- **AND** the read MUST proceed immediately

#### Scenario: Feature switch is off

- **WHEN** `TDX_HISTORY_REFRESH_ENABLED=off`
- **THEN** no refresh call MUST be made
- **AND** `mist_datasource_tdx_history_refresh_total{result="disabled"}` MUST be incremented
- **AND** the bar read MUST behave exactly as before this change

### Requirement: TDX refresh stays internal to the collection pipeline

The `refresh_kline` integration MUST NOT create a new public `/v1` endpoint and
MUST NOT be callable from backend or operator surfaces other than the existing
operator raw-call escape hatch.

#### Scenario: No public endpoint added

- **WHEN** the change is implemented
- **THEN** the only callers of `refresh_kline` MUST be
  `TdxMarketOperations.get_bars` and the pre-existing operator raw-call route
- **AND** the OpenAPI surface MUST be unchanged by this capability
