# Specification: qmt-market-history

## ADDED Requirements

### Requirement: Download jobs are submitted and tracked separately from bar reads

The QMT datasource SHALL expose a governed download job surface, separate from
`/v1/bars/query` (which MUST remain a pure read with no download side
effects):

- `POST /v1/qmt/download` — submit a download job `{stock_list,
  base_periods ⊆ {1m,5m,1d}, start_time, end_time}`; the datasource SHALL
  validate the request (symbol format, base-period allowlist, list bounds,
  date format), create an in-memory job, and enqueue serial download commands
  to the bridge; it MUST return `{job_id, tasks}` immediately without waiting
  for downloads to complete.
- `GET /v1/qmt/download/{jobId}` — per-task status
  (pending/running/done/failed) and aggregate status; completed jobs SHALL
  remain queryable for a bounded TTL.

#### Scenario: Job submission returns immediately

- **WHEN** a valid download job is submitted
- **THEN** the response MUST return `{job_id, tasks}` before any download
  completes
- **AND** the bridge MUST download the base periods serially via the
  `download_history_data` command

#### Scenario: Job status reports per-task and aggregate state

- **WHEN** the job status route is queried for an existing job
- **THEN** the response MUST report each task's state and the aggregate
  (all_done / any_failed / in_progress)

#### Scenario: Invalid submissions are rejected before terminal I/O

- **WHEN** a submission violates validation (bad symbol format, base period
  outside {1m,5m,1d}, more than 64 symbols, malformed dates)
- **THEN** the request MUST be rejected with a bounded error before any
  bridge command is enqueued

### Requirement: In-session gate blocks download submissions during trading hours

A-share activity hours (reuse `ActivityWindow`, default
`09:15-11:30,13:00-15:00` UTC+8) MUST gate the download submission: inside
the window, submissions MUST be refused (counter `result=in_session`) and
reads MUST proceed unaffected — realtime must never be stalled by a download
during the session.

#### Scenario: Submission refused during the session

- **WHEN** a download job is submitted inside the activity window
- **THEN** the datasource MUST refuse to create the job
- **AND** `mist_datasource_qmt_history_download_total{result="in_session"}` MUST
  be incremented
- **AND** the response MUST carry the bounded reason `in_session`

### Requirement: Bridge download handler resolves the bare-global API and aggregates base periods

The QMT bridge (v3.2) SHALL support a `download_history_data` command that
resolves the native callable as `globals().get("download_history_data")`
(framework-injected global; the production probe verified it is NOT a
`ContextInfo` attribute) with a `ContextInfo` getattr fallback, then downloads
each requested base period (`1m`, `5m`, `1d`) sequentially with explicit
start/end times, reporting per-period status. `bridgeBuildId` MUST be bumped
to `mist-qmt-realtime-bridge-v3.2`.

#### Scenario: Download handler aggregates three base periods

- **WHEN** the download command is invoked for one stockcode with periods
  `1m`, `5m`, `1d`
- **THEN** the handler MUST call the native download API once per period in
  order and return per-period status

#### Scenario: Native API is missing from the runtime

- **WHEN** neither the script globals nor `ContextInfo` expose
  `download_history_data`
- **THEN** the handler MUST return a bounded error
  (`QMT_DOWNLOAD_API_UNAVAILABLE`) and MUST NOT block the main loop

#### Scenario: Guardrails continue to apply

- **WHEN** the bridge gains the two new handlers (`introspect_methods`,
  `download_history_data`) and loses `call_native`
- **THEN** `test_bigqmt_bridge_guardrails.py` MUST pass (Python 3.6 syntax,
  GBK, no threading) and health MUST report `bridgeBuildId=v3.2`

### Requirement: introspection reports both injection surfaces

The QMT bridge `introspect_methods` command SHALL report candidate method
surface metadata (available/type/bounded doc) from BOTH injection surfaces —
`ContextInfo` attributes AND the script globals — via `getattr`/`globals()
.get` lookups only, never calling candidates. Candidates MUST be bounded
(≤ 32) and name-validated (`^[A-Za-z_][A-Za-z0-9_]{0,63}$`).

#### Scenario: Both surfaces are reported

- **WHEN** introspection is invoked with candidates such as
  `download_history_data` and `get_market_data_ex`
- **THEN** each candidate MUST report availability on BOTH surfaces
  (contextinfo / globals) without executing anything

#### Scenario: Bounded and validated candidates

- **WHEN** an introspection request exceeds 32 candidates or contains a name
  violating the identifier pattern
- **THEN** the request MUST be rejected with a bounded validation error
  before any lookup

### Requirement: Bar reads remain pure reads

`/v1/bars/query` MUST NOT trigger downloads: the read path SHALL only serve
whatever the terminal local cache contains (current behavior). The download
job surface (above) is the only download trigger.

#### Scenario: Read behaves identically without downloads

- **WHEN** `/v1/bars/query` is invoked at any time
- **THEN** its behavior, latency profile (except terminal cache state), and
  response shape MUST be unchanged from before this change
