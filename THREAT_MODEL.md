# TradeForge Threat Model

## Assets

- BOT account cash and positions.
- Long-term investments and their account identifiers.
- Broker credentials and access tokens.
- Append-only trading, tax, and audit history.
- Owner hard limits and kill-switch state.
- Tax exports and personally identifying financial data.

## Trust boundaries

1. Owner UI/API to command services.
2. Market data and broker responses to normalized domain objects.
3. Research/AI to deterministic risk engine.
4. Risk engine to execution service.
5. Execution service to broker adapter.
6. Application database to backups/exports.

## Threats and mitigations

| Threat | Mitigation | Detection/response |
| --- | --- | --- |
| Wrong account order | Exact positive BOT allowlist and denylist | Hard reject, security event, no retry |
| AI bypasses risk | AI only emits `TradeIntent`; execution re-checks gate | Risk rejection and audit |
| Duplicate order after timeout | Persistent idempotency key; unknown state is terminal | Pause and reconcile |
| Restart resumes trading | Persisted control state and kill switch | Startup gate denies until checks pass |
| Stale/manipulated quote | Timestamp, bid/ask, spread, source validation | Risk rejection/circuit breaker |
| Broker state mismatch | Periodic cash/position/order/execution reconciliation | Pause and alert |
| Personal investment access | No adapter/capability; account allowlist | Security event and denied request |
| Unauthorized limit increase | Owner authentication and immutable audit event | Security review |
| Secret leakage | Execution-only secret boundary, redaction, secret manager target | Scan, rotate, incident response |
| Ledger tampering | Append-only triggers and hash chain | Integrity verification and recovery |
| Tax misclassification | Separate cash/trade/tax event types and review flags | Annual reconciliation |
| Operator presses wrong control | Separate pause, stop, and liquidation semantics | Confirmation and state timeline |

## Abuse cases

- A strategy sends a `LIVE` intent: denied because live readiness is false.
- A UI request names a personal account: denied before broker invocation.
- A broker call times out: no retry; order becomes unknown and controls pause.
- A manual withdrawal reduces cash: classified as external cash movement, not
  trading loss.
- A model suggests increasing size after losses: bounded sizing and hard limits
  reject the proposal.

## Residual risks

Hardware compromise, compromised owner credentials, broker-side errors, bad
market data, and tax-law interpretation cannot be eliminated by application
architecture. They require operational controls, broker safeguards, backups,
and professional review.
