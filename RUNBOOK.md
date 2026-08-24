# TradeForge Runbook

## Normal paper operation

1. Start with `MODE=PAPER`.
2. Run the system check.
3. Verify broker, market data, risk, and reconciliation statuses.
4. Start paper only; observe dashboard and ledger.
5. Review rejected intents and fills without changing safety limits from AI.

## Pause

Pause blocks new executable entries, optionally cancels pending entries, and
leaves positions and monitoring untouched.

## Stop everything

Stop everything persists the global kill switch, blocks all new orders,
prevents executable strategy activity, attempts safe pending-entry cancellation,
and keeps monitoring, reconciliation, logging, and UI alive. It never
automatically sells existing positions.

Recovery is: system check -> reconciliation -> owner authentication -> reset
kill switch -> explicit resume. A failed check leaves the system stopped.

## Unknown execution

Do not retry. Preserve the idempotency key, query/reconcile the broker, compare
orders/fills/cash/positions, and keep automation paused until state is known.

## Manual broker activity

Reconciliation records external trades and cash movements. Ambiguity pauses
automated entries. Deposits and withdrawals are never silently converted to
trading P&L.
