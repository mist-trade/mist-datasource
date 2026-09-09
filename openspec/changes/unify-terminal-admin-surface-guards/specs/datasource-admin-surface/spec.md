# Specification: datasource-admin-surface

## ADDED Requirements

### Requirement: Both terminal admin surfaces are governed by per-source classification maps

Each terminal source (QMT ContextInfo, TDX tqcenter) SHALL have a checked-in
classification map (`method → {family}`) derived from its governance
documentation (thinktrader API dictionary; tdxquant-interface-coverage.md).
Both maps SHALL share one structure and one update flow (governance doc first,
then map). A shared guard component SHALL evaluate admin calls with a
three-stage fail-closed policy: unclassified methods MUST be rejected; methods
belonging to denied families (QMT: trading/account; TDX: trading/account/
execution) MUST be rejected; classified methods outside denied families are
allowed.

#### Scenario: Classified method is allowed on both sources

- **WHEN** an admin call requests a method classified outside the denied
  families on either source
- **THEN** the call MUST be forwarded over that source's native transport and
  its result returned

#### Scenario: Unclassified method is denied on both sources

- **WHEN** an admin call requests a method absent from the source's
  classification map
- **THEN** the call MUST be rejected with a bounded error
  (`*_METHOD_UNCLASSIFIED`) before any terminal I/O

#### Scenario: Denied-family method is denied on both sources

- **WHEN** an admin call requests a method whose family is denied
  (QMT: trading/account — e.g. `passorder`; TDX: trading/account/execution)
- **THEN** the call MUST be rejected with a bounded error
  (`*_METHOD_FAMILY_FORBIDDEN`) regardless of any configuration
- **AND** guard tests MUST cover every method of each denied family in the maps

#### Scenario: TDX legacy blacklist is replaced

- **WHEN** the change is implemented
- **THEN** `FORBIDDEN_RAW_METHODS` and `FORBIDDEN_RAW_PREFIXES` MUST no longer
  govern `/v1/raw/tdx/call`
- **AND** previously callable unclassified methods MUST now be rejected

### Requirement: QMT call_native enforces the classification guard with a trading hard-deny

The QMT bridge SHALL support a `call_native` command that executes a
datasource-classified method against `ContextInfo`. Enforcement SHALL be
single-layer at the datasource (classification guard per above), plus an
in-bridge static hard-deny for trading/account patterns (e.g. `passorder`)
as a terminal-state-independent invariant. Execution blocks the bridge main
loop for its duration; therefore the command MUST participate in the
`busy_until` lease extension and MUST be bounded by the datasource timeout.

#### Scenario: Classified execution succeeds

- **WHEN** `call_native` is invoked for a method classified and allowed by the
  datasource map
- **THEN** the bridge MUST execute it via `getattr(ContextInfo, method)` and
  return the result in the same polling cycle

#### Scenario: Trading patterns are hard-denied in-bridge

- **WHEN** a `call_native` command carries a method matching the in-bridge
  trading/account hard-deny patterns (e.g. `passorder`)
- **THEN** the bridge MUST reject it locally without executing — regardless of
  the datasource guard or any configuration

#### Scenario: Trading permission is a documented tripwire

- **WHEN** the admin execution surface is relied upon
- **THEN** the design MUST document that its safety depends on the terminal
  not having trading permissions enabled (operator-confirmed 2026-09-09)
- **AND** enabling trading permissions on any terminal MUST be gated on first
  adding an in-bridge trading deny list/allowlist to this capability

#### Scenario: Long execution does not falsely kill the owner

- **WHEN** a `call_native` execution exceeds `owner_stale_after_seconds`
- **THEN** the owner MUST NOT be declared stale before
  `busy_until` (issue time + command timeout + 60s) has passed
- **AND** after the deadline without polls the owner MUST be handled as stale
  (lease release → re-registration → journal reconciliation)

#### Scenario: Timeout abandons the wait but the side effect may persist

- **WHEN** the datasource abandons the wait at the command timeout
- **THEN** the admin call MUST be reported as `result=timeout` with a warn log
- **AND** the read-only or execution side effect on the terminal MAY have
  completed and MUST be reported honestly in the log

### Requirement: TDX enforcement is datasource-only by terminal constraint

The TdxW terminal HTTP channel is a closed service: no guard can be added
terminal-side. Therefore TDX admin-call enforcement MUST live entirely at the
datasource route (classification guard per above), and this limitation MUST be
documented as a terminal constraint rather than a design choice.

#### Scenario: TDX datasource is the only enforcement point

- **WHEN** a TDX admin call is evaluated
- **THEN** enforcement MUST happen at the datasource route before terminal I/O
- **AND** the design MUST document that TdxW's HTTP channel cannot host a
  terminal-side guard (closed service)

### Requirement: Admin calls are observable and network-private

Every admin-surface call SHALL be counted
(`mist_datasource_admin_call_total{source,method,result}` with bounded method
cardinality — unclassified calls logged as `method="unclassified"`) and logged
(info on success with bounded result size; warn on denials with bounded
reason). The QMT admin route SHALL remain compose-network internal with no
host/external exposure changes.

#### Scenario: Every admin call is counted and logged

- **WHEN** an admin route is invoked (allowed or denied)
- **THEN** `mist_datasource_admin_call_total{source,method,result}` MUST be incremented
- **AND** a structured log line MUST be emitted with method, latency, and
  bounded result size

#### Scenario: No public exposure added

- **WHEN** the change is implemented
- **THEN** the external exposure surface (host ports, OpenAPI public routes)
  MUST be unchanged
