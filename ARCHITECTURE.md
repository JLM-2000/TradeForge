# TradeForge Architecture

## Scope and invariants

TradeForge is personal-use-only proprietary trading software. `PERSONAL_USE_ONLY`
is a permanent architectural flag. If the scope expands to third-party money,
customers, recommendations as a service, or managed accounts,
`REGULATORY_REVIEW_REQUIRED` becomes true and those features remain disabled
until professional review.

The initial implementation is paper-only. The execution boundary rejects live
orders because no official live adapter, readiness approval, or owner approval
exists.

## Complete target architecture

```text
                   +-------------------------------+
                   | Owner Web UI / Control Center  |
                   +---------------+---------------+
                                   |
                         Authenticated API / WS
                                   |
+------------------+    +---------v---------+    +---------------------+
| Official market  |--->| Market Data Service|--->| Feature/Signal Engine|
| data adapters    |    +---------+---------+    +----------+----------+
+------------------+              |                         |
                                  v                         v
                         +----------------+       +----------------+
                         | Quality/health |       | TradeIntent    |
                         +----------------+       +-------+--------+
                                                          |
                                                  +-------v--------+
                                                  | Deterministic  |
                                                  | Risk Engine    |
                                                  +-------+--------+
                                                          |
                                                  ApprovedOrder
                                                          |
                                                  +-------v--------+
                                                  | Execution      |
                                                  | Service/Gate   |
                                                  +-------+--------+
                                                          |
                            +-----------------------------+----------------+
                            |                                              |
                    +-------v-------+                              +-------v-------+
                    | Paper/Sim     |                              | Future official|
                    | Broker        |                              | Broker adapter |
                    +-------+-------+                              +-------+-------+
                            |                                              |
                            +------------------+---------------------------+
                                               v
                                      +--------+---------+
                                      | Events/Fills     |
                                      +--------+---------+
                                               v
                  +----------------------------+-----------------------------+
                  | Append-only ledger + audit + reconciliation evidence     |
                  +-----------+------------------+---------------------------+
                              |                  |
                    +---------v--------+ +-------v-------+
                    | Portfolio/risk   | | Tax lots/FIFO |
                    | analytics        | | and reserve   |
                    +---------+--------+ +-------+-------+
                              |                  |
                              +--------+---------+
                                       v
                                  Dashboard/read models
```

## Data flow

```text
Quote -> freshness/spread checks -> feature snapshot -> versioned strategy
-> TradeIntent -> account/instrument/control/risk checks -> RiskDecision
-> OrderRequest with idempotency key -> execution gate -> BrokerOrder
-> Fill/Execution events -> ledger hash chain -> portfolio/tax projections
-> notifications, reconciliation, audit, and dashboard read models
```

AI and strategy code can produce intents and research artifacts only. They do
not receive secrets, call brokers, modify owner limits, reset controls, or
choose accounts.

## Security boundaries

```text
UNTRUSTED INPUTS: market data, broker responses, UI requests, imports
        |
        v
Validation and normalization boundary
        |
        +--> Research/AI sandbox (no credentials, no order capability)
        +--> Read-only dashboard/API projections
        +--> Deterministic Risk Engine
                         |
                 Execution Service boundary
                 exact BOT_ACCOUNT allowlist
                 persisted kill switch re-check
                         |
                 Paper broker only at M1
                 future official adapter in isolated process
```

The personal investment denylist is defense in depth. The positive BOT account
allowlist is the primary control. An account mismatch is a hard rejection and
security event with no retry.

## Runtime modes

`DEMO` uses synthetic data. `PAPER` simulates execution. `SHADOW` observes
signals and compares hypothetical execution without placing orders. `LIVE` is
not enabled by this checkpoint and must pass every independent readiness gate.

## Persistence

The M1 persistence abstraction is SQLite-backed for local development. The
production target is PostgreSQL with NUMERIC columns, migrations, row-level
access controls, encrypted backups, and separate execution credentials. The
domain uses `Decimal` and UTC-aware timestamps regardless of storage engine.

## Read/write separation

Commands pass through authenticated control and execution services. Dashboard
queries consume projections. Financial history is never edited in place;
corrections are new ledger events that reference the original event.

## Low-latency execution path

Execution is event-driven and does not put an LLM, notebook, browser, or
dashboard request in the order path:

```text
precomputed features -> versioned signal -> bounded intent
-> in-memory risk snapshot -> persisted control check
-> idempotency check -> official broker request
```

The path is designed for sub-second application decisions, not a promise of
sub-second fills. Retail broker APIs, venue routing, spread, throttling, and
network distance dominate end-to-end time. A future benchmark must report
intent-to-risk, risk-to-submit, broker acknowledgement, and fill latency
separately. A slower safe rejection is always preferable to an unsafe order.

Python research and accounting code is not loaded into the hot path. The M1
Python implementation is the executable reference for correctness. If
profiling shows that Python validation is the bottleneck, the deterministic
risk/execution gateway will be moved to a small Rust service with property and
cross-language conformance tests. Rust will not remove any safety gate or
create a second policy implementation.

## Planned production stack

Python 3.12 for research, accounting, tax, and orchestration; FastAPI,
Pydantic v2, SQLAlchemy/Alembic, PostgreSQL, Redis or a durable queue for
workers, React/TypeScript/Vite, and Apache ECharts or TradingView Lightweight
Charts after licensing review. A Rust execution/risk gateway is a profiled
optimization, not a premature second implementation. The standard-library M1
core is intentional: it keeps safety behavior independently executable before
infrastructure complexity is introduced.
