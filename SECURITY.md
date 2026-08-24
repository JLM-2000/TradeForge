# TradeForge Security

## Security objectives

1. Prevent unintended orders.
2. Prevent access to personal investment accounts.
3. Prevent unauthorized capital movement.
4. Preserve financial and audit history.
5. Fail closed on uncertainty or stale state.

## Non-negotiable controls

- `PERSONAL_USE_ONLY=true`.
- `MODE=PAPER` by default.
- No MyInvestor automation, browser automation, private endpoints, cookies,
  reverse engineering, or undocumented APIs.
- Only official documented broker APIs may ever be connected for live execution.
- No withdrawal, bank-account, deposit, transfer, or bank-login capability.
- Broker credentials belong only to an isolated execution service.
- Strategy and AI processes receive no secrets.
- Exact `BOT_ACCOUNT_ID` allowlist plus permanent personal-account denylist.
- Persisted kill switch is checked independently by the execution boundary.
- Unknown broker submission state pauses automated trading and requires
  reconciliation; it is never retried blindly.
- Secrets are excluded from logs, source control, exports, and backups.

## Owner authentication

Sensitive actions require authenticated owner context and an audit event:
changing hard limits, switching modes, changing the BOT account, resetting the
kill switch, disabling a safety check, or approving any future live readiness.

## Data handling

Money, prices, quantities, and FX rates use decimal arithmetic. Timestamps are
timezone-aware UTC. Ledger events use a hash chain and database append-only
triggers. Tax exports are deliberate owner actions and are marked estimates or
records as appropriate.

## Security event policy

Account mismatch, attempted live execution, denied capability, credential
errors, unexpected execution, reconciliation mismatch, and control bypass
attempts generate `SECURITY` or `RISK` events. Security events are not silently
swallowed and are not automatically retried.

## Known M1 limitations

The local SQLite database is not a production secret store, the API/UI does
not yet exist, and owner authentication is represented by an explicit command
context rather than an identity provider. Live readiness therefore remains
unapproved.
