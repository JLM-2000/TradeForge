# TradeForge Live Readiness

## Current status

`LIVE READINESS: NOT APPROVED`

There is no live adapter, no live credential flow, no live account, and no
automatic promotion. This is intentional.

## Required gates

- Official broker API and permitted terms.
- Dedicated isolated BOT account.
- Personal investments inaccessible and denied.
- Least-privilege execution credentials.
- Sufficient PAPER and SHADOW history.
- Passing safety suite and validated RiskEngine.
- Kill switch and restart behavior validated.
- Reconciliation and backup/restore tested.
- Market data quality and broker fees understood.
- Tax workflow reviewed by the owner and a professional where appropriate.
- Explicit authenticated owner approval.

All conditions are independent. One failure denies live execution. A normal
code commit never deploys live trading. Initial live, if ever approved, is
micro-sized and separately reviewed.
