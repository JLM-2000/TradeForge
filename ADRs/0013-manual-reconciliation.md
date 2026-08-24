# ADR 0013: Manual Operation Reconciliation

- Status: Accepted
- Decision: Broker reconciliation detects external trades/deposits/withdrawals,
  records their origin, and pauses on ambiguity.
- Reason: Owner retains manual control and history must not misattribute actions.
