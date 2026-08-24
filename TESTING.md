# TradeForge Testing Strategy

## Layers

- Unit tests for Decimal arithmetic, validation, state transitions, FIFO, and
  risk checks.
- Integration tests for SQLite migrations, append-only triggers, controls,
  idempotency, and paper fills.
- Property tests for FIFO conservation, order-state graph validity, and risk
  ceilings. Hypothesis is a planned optional dependency; deterministic examples
  run in the standard-library suite now.
- End-to-end tests for future API/UI commands and WebSocket stale-state UX.
- FastAPI tests for paper-only API behavior, production owner authentication,
  every failure-injection scenario, restart-safe kill switch behavior, and the
  no-liquidation invariant.
- Vitest/Testing Library coverage for the visible `STOP EVERYTHING` dialog,
  typed confirmation, disabled state before confirmation, and API submission.
- Failure-injection tests for timeout, stale data, duplicate order, disconnect,
  mismatch, and database integrity problems.

## Critical invariants

STOP EVERYTHING blocks execution and survives restart. It does not sell.
Pause blocks entries. Resume requires reconciliation and health. Account and
instrument allowlists cannot be bypassed. AUTO never exceeds owner ceilings.
Unknown broker state is never retried. Deposits/withdrawals are not P&L.
Tax reserve is not a tax payment.

## Quality commands

```bash
make lint
make typecheck
make security-check
make migrate-check
make test
make safety-test
make ci
```

The initial commands use standard-library AST and compilation checks so they do
not create a false dependency on uninstalled tools. Ruff, mypy, dependency
scanning, browser tests, and database services are required gates when those
production dependencies are introduced.
