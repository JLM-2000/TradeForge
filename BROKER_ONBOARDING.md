# Broker Account and API Onboarding

TradeForge does not currently connect to a real broker. The following is the
required future process; it is intentionally provider-neutral because the
official broker has not been selected and no credentials should be requested
in chat.

## 1. Choose the account boundary

1. Select a broker with an official documented API and a permitted personal
   proprietary-trading use case.
2. Open a completely independent BOT account for TradeForge.
3. Do not use MyInvestor or any account that contains long-term investments.
4. Record the broker account identifier as `TRADEFORGE_BOT_ACCOUNT_ID` only
   after independently verifying it in the official broker interface.
5. Add every personal-investment account to the permanent denylist.

## 2. Create the account manually

Complete identity, tax-residency, suitability, funding, and 2FA steps only on
the broker's official website or application. Fund it manually. TradeForge
must not log into a bank, create withdrawal destinations, transfer funds, or
move capital through an API.

Start with the broker's paper/sandbox account if available. The demo runtime
does not require a broker account at all.

## 3. Create API credentials manually

In the official broker security console:

- Create a dedicated API key for the BOT account only.
- Enable read balances, positions, orders, executions, and market data.
- Enable order placement/cancellation only if the broker provides a separate
  permission and the paper workflow is already validated.
- Disable withdrawals, bank-account changes, transfers, deposits, and account
  administration.
- Use IP allowlisting, expiry, rotation, and 2FA where supported.
- Never paste keys, secrets, refresh tokens, or 2FA material into TradeForge
  chat, Git, logs, screenshots, or issue trackers.

## 4. Store secrets outside the repository

Production uses a secret manager or protected environment injection. The
execution service alone receives the credentials. Strategy, AI, dashboard, and
research processes never receive them.

```text
TRADEFORGE_ENV=production
TRADEFORGE_BOT_ACCOUNT_ID=<verified-dedicated-account>
TRADEFORGE_DASHBOARD_TOKEN=<owner-only-dashboard-secret>
BROKER_API_KEY=<secret-manager-reference>
BROKER_API_SECRET=<secret-manager-reference>
```

The names above are placeholders. Do not populate them until an official
adapter is implemented and reviewed.

## 5. Validate before any live capability

The adapter must pass, in order:

1. Official API and terms review.
2. Capability discovery with withdrawals permanently disabled.
3. Account allowlist and personal-account denial tests.
4. Paper order lifecycle and idempotency tests.
5. Cash/position/order/execution reconciliation.
6. Restart and unknown-submission recovery tests.
7. Safety acceptance suite.
8. Long-running PAPER and SHADOW history.
9. Owner-authenticated readiness review.

If any prerequisite fails, the adapter remains unavailable and TradeForge stays
in PAPER/SHADOW. A normal code commit must never enable LIVE.

## Current state

`PaperBroker` is the only executable broker implementation. MyInvestor and
other future adapters are non-executable placeholders. No real account or API
credential is required to run the current automatic paper session.
