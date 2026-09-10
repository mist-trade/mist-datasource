# Specification: tdx-market-history

## ADDED Requirements

### Requirement: TDX bar reads are pure reads

The TDX bar read path (`get_market_data` via `/v1/bars/query`) MUST NOT
trigger downloads: it SHALL only serve whatever the terminal local cache
contains (current behavior). The explicit download endpoint (below) is the
only download trigger for TDX — mirroring the QMT pure-read requirement.

#### Scenario: Read behaves identically without downloads

- **WHEN** `/v1/bars/query` is invoked at any time
- **THEN** its behavior, latency profile, and response shape MUST be
  unchanged from before this change
- **AND** no `refresh_kline` call MUST be issued from the read path

### Requirement: TDX download jobs share the unified async job contract

The TDX datasource SHALL expose download endpoints with the SAME shape as the
QMT surface: `POST /v1/tdx/download` submits a job `{stock_list,
base_periods ⊆ {1m,5m,1d}, start_time?, end_time?}` and MUST return
`{jobId, tasks}` immediately; `GET /v1/tdx/download/{jobId}` reports per-task
and aggregate status. Execution runs `refresh_kline` once per requested base
period with the full stock list (terminal blocks until refresh completes —
production-measured ~100ms per incremental call). The date-range fields are
accepted for contract symmetry but the download scope is terminal-managed
(the official API has no range parameters; production probe verified
historical gaps become readable after refresh). Validation MUST run before
any terminal I/O.

#### Scenario: Job submission returns immediately

- **WHEN** `POST /v1/tdx/download` is invoked with a valid request
- **THEN** the response MUST return `{jobId, tasks}` before the refresh
  completes, and the refresh MUST run in the background
- **AND** `GET /v1/tdx/download/{jobId}` MUST report per-task status until
  all tasks reach a terminal state

#### Scenario: Invalid base period is rejected

- **WHEN** the request contains a period outside {1m,5m,1d} (e.g. `15m` —
  synthesized by the terminal, not a refresh_kline input)
- **THEN** the request MUST be rejected with a bounded validation error
  before any terminal I/O

#### Scenario: Success response shape is normalized by ErrorId

- **WHEN** the terminal responds with
  `{"ErrorId": "0", "Msg": "refresh kline cache success.", "run_id": ...}`
  (production-verified 2026-09-09; the official doc sample names the message
  field `Error` but the runtime field is `Msg`)
- **THEN** the datasource MUST classify it as success by `ErrorId == 0` and MUST
  NOT depend on the message field name
