# TradeForge Requirements Analysis

## Purpose

TradeForge is a private system for the owner's own funds. The first engineering
objective is controlled, explainable paper execution. Profitability is a later
research outcome and is never allowed to outrank capital safety.

## Mandatory requirements

| Area | Requirement | M1 treatment |
| --- | --- | --- |
| Scope | `PERSONAL_USE_ONLY=true`; no customer or third-party funds | Enforced/documented |
| Isolation | exact BOT account allowlist and investment-account denylist | Enforced in risk/control gates |
| Broker | official APIs only; MyInvestor execution disabled | Paper broker plus placeholders |
| Capital flow | no withdrawals, deposits, transfers, or bank credentials | No capability; planner is read-only |
| Execution | intent -> risk -> approved order -> broker -> fill -> ledger | Implemented reference path |
| Money | Decimal and timezone-aware events | Enforced typed constructors |
| History | append-only ledger and correction events | SQLite triggers plus hash chain |
| Risk | owner hard ceilings outrank AUTO and AI | Implemented deterministic checks |
| Controls | pause, resume checks, persisted STOP EVERYTHING | Implemented |
| Reconciliation | cash/positions/orders/executions compare; mismatch pauses | Implemented reference service |
| Tax | realized/unrealized/cash separation, FIFO, review flags | Implemented reference engine |
| Tax reserve | transparent estimate, no money movement | Implemented |
| Performance | fast local decision path without synchronous AI | Architecture and measurement plan |
| UI | professional real-time terminal with clear mode/status | M6, design specified |
| Research | backtests, walk-forward, champion/challenger | Later milestones |

## Explicit non-requirements for the initial release

- No real-money broker connection.
- No MyInvestor automation of any kind.
- No bank login or bank integration.
- No derivatives, margin, leverage, shorting, crypto, speculative FX, CFDs,
  leveraged products, or structured products.
- No uncontrolled online learning or self-promotion.
- No automatic tax filing or claim of tax/legal compliance.
- No emergency liquidation coupled to the kill switch.

## Acceptance hierarchy

An implementation is rejected if it is fast but can place an unintended order,
touch a non-BOT account, lose ledger history, retry unknown broker state, or
override a human limit. Performance benchmarks are meaningful only after the
safety acceptance suite passes.

## Milestones

```text
M0 architecture/threat model/ADRs
M1 domain/persistence/ledger/safety controls
M2 market-data abstraction and demo data
M3 realistic PaperBroker
M4 RiskEngine and owner hard limits
M5 end-to-end PAPER execution
M6 web terminal
M7 charts/positions/orders/realtime
M8 pause/resume/stop/circuit breakers
M9 manual/auto risk UX
M10 backtesting and walk-forward
M11 strategy lab and version promotion
M12 analytics
M13 FIFO/tax review workflow
M14 tax reserve and annual pack
M15 withdrawal planning/reconciliation
M16 champion/challenger research pipeline
M17 official broker simulation integration
M18 long-running paper/shadow validation
M19 formal live readiness review
```

No milestone automatically promotes to LIVE.
