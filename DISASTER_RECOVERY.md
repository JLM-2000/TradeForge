# TradeForge Disaster Recovery

## Recovery priorities

1. Freeze automated execution.
2. Preserve the original ledger and audit evidence.
3. Determine broker state from the official source.
4. Restore projections only after the ledger is verified.
5. Resume only after reconciliation and owner approval.

## Scenarios

- Application crash: persisted controls remain active; restart in stopped or
  paused state until checks pass.
- Database crash: restore a verified backup, validate ledger hash chain, then
  reconcile all broker state before any orders.
- Broker outage: circuit breaker pauses; no blind retries.
- Network outage/timeout: mark submission unknown and reconcile.
- Corrupt cache: discard derived cache, never discard ledger evidence.
- Reconciliation mismatch: pause, export evidence, investigate, and record a
  correction event rather than rewriting history.

## Backups

Back up database, ledger, configuration, strategy metadata, tax records, and
audit records. Exclude plaintext secrets. Production backups must be encrypted,
versioned, access-controlled, and periodically restore-tested.
