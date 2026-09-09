# Specification: qmt-market-history

## ADDED Requirements

### Requirement: Bar reads trigger a bounded synchronous download of all base periods first

The QMT market operations SHALL, before every `get_market_data_ex` bar read and
when `QMT_HISTORY_DOWNLOAD_ENABLED=on`, issue a synchronous bridge download
command that downloads ALL base periods (`1m`, `5m`, `1d`) for the requested
symbol and date range. Per the official synthesis model (`30m` is generated
from `5m`; day-family from `1d`), the three base periods cover every supported
read period. The datasource SHALL wait for the command result within
`QMT_HISTORY_DOWNLOAD_TIMEOUT_MS`. The read MUST proceed regardless of the
download outcome.

#### Scenario: Download completes before the read

- **WHEN** `get_bars` is invoked with `QMT_HISTORY_DOWNLOAD_ENABLED=on`
- **AND** the bridge completes the download command (all base periods) within
  `QMT_HISTORY_DOWNLOAD_TIMEOUT_MS`
- **THEN** the datasource MUST issue the `get_market_data_ex` read afterwards
- **AND** `mist_datasource_qmt_history_download_total{result="ok"}` MUST be incremented

#### Scenario: Download covers all base periods in one trigger

- **WHEN** a download command is issued for a symbol and date range
- **THEN** the bridge MUST download base periods `1m`, `5m`, and `1d`
  (synthetic periods such as `30m` are covered by `5m`)
- **AND** the command result MUST report per-period completion

#### Scenario: Download times out and the read degrades gracefully

- **WHEN** the download command result is not observed within the timeout
- **THEN** the datasource MUST still issue the `get_market_data_ex` read
- **AND** `mist_datasource_qmt_history_download_total{result="timeout"}` MUST be incremented
- **AND** a warn log line MUST be emitted with the bounded reason
  `download_timeout` and the symbol in bounded fields
- **AND** the read MAY still benefit from locally cached data written by the
  terminal before the datasource abandoned the wait

#### Scenario: Download command fails natively

- **WHEN** the bridge reports the download command as failed
- **THEN** the datasource MUST still issue the `get_market_data_ex` read
- **AND** `mist_datasource_qmt_history_download_total{result="failed"}` MUST be incremented
- **AND** a warn log line MUST be emitted with bounded reason `download_failed`;
  the native error text MUST only appear in the structured `error=` field

#### Scenario: Bridge predates the download command

- **WHEN** the bridge rejects the download command with `QMT_COMMAND_UNSUPPORTED`
- **THEN** the datasource MUST skip the download and issue the read directly
- **AND** `mist_datasource_qmt_history_download_total{result="unsupported"}` MUST be incremented
- **AND** the first occurrence MUST emit a warn log with bounded reason
  `bridge_unsupported` (subsequent occurrences MUST NOT re-warn per request)

#### Scenario: In-session reads are gated from downloading

- **WHEN** a bar read occurs inside the A-share activity window
  (`ActivityWindow`, default `09:15-11:30,13:00-15:00` UTC+8)
- **THEN** no download command MUST be sent
- **AND** `mist_datasource_qmt_history_download_total{result="in_session"}` MUST be incremented
- **AND** the read MUST proceed immediately (realtime must never be stalled by a
  download during the session)

#### Scenario: Feature switch is off

- **WHEN** `QMT_HISTORY_DOWNLOAD_ENABLED=off`
- **THEN** no download command MUST be sent
- **AND** `mist_datasource_qmt_history_download_total{result="disabled"}` MUST be incremented
- **AND** the bar read MUST behave exactly as before this change

#### Scenario: Repeated triggers within one collection round are deduplicated

- **WHEN** multiple bar reads for the same symbol and overlapping range occur
  within the memo TTL
- **THEN** the datasource MUST issue the download command at most once per
  (symbol, base period, range) per memo window

### Requirement: Bridge main-loop stall is bounded and recovery is automatic

The synchronous download executes inside the bridge main loop and therefore
stalls heartbeat/command polling for its duration. This stall MUST be bounded
by the datasource timeout, MUST occur only via the collection pipeline
(off-hours scheduled syncs; in-session manual collects are a documented risk),
and the existing recovery path (owner stale → re-registration → journal
reconciliation) MUST restore realtime operation afterwards.

#### Scenario: Owner lease goes stale during a long download

- **WHEN** the download duration exceeds `owner_stale_after_seconds`
- **THEN** the datasource MAY mark the owner stale and reject concurrent reads
  with `QMT_BRIDGE_OWNER_STALE` (existing behavior)
- **AND** after the download completes the bridge MUST re-register and journal
  reconciliation MUST restore the subscription state without manual intervention

#### Scenario: In-flight download extends the lease deadline for that source only

- **WHEN** a download command has been issued and its result is not yet observed
- **THEN** the owner lease deadline for this source MUST be evaluated as
  `max(last_poll + 15s, command issue time + command timeout + 60s)`
- **AND** if no poll arrives by that extended deadline, the owner MUST be
  handled as stale (lease release → re-registration → journal reconciliation)
- **AND** other sources' staleness behaviour MUST be unchanged

#### Scenario: Without an in-flight download, death detection is unchanged

- **WHEN** no download command is in flight
- **THEN** owner staleness MUST be evaluated with the unchanged
  `owner_stale_after_seconds` (15s) threshold
- **AND** the snapshot `StallDetector` behaviour MUST NOT be altered