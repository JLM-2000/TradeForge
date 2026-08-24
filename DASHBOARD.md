# TradeForge Dashboard

## Runtime modes

The dashboard is a real operations surface over the PAPER runtime. It is not a
static demo: paper order requests flow through `TradeIntent`, `RiskEngine`,
`ExecutionService`, `PaperBroker`, ledger events, and dashboard projections.
The badge intentionally says `PAPER - SIMULATED OPERATIONS`; it must never be
described as live trading just because the simulated workflow resembles live
operations.

## Start locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/uvicorn tradeforge.api:app --reload --port 8001
npm --prefix web install
npm --prefix web run dev
```

Open `http://localhost:5173`.

For a single-process bundle:

```bash
npm --prefix web run build
PYTHONPATH=src .venv/bin/uvicorn tradeforge.api:app --host 127.0.0.1 --port 8001
```

The API serves `web/dist` when it exists.

## Controls

- `PAUSE` stops new entries and preserves monitoring/positions.
- `RESUME` checks broker, data, cash, positions, orders, reconciliation,
  limits, account, and kill-switch state.
- `STOP EVERYTHING` persists the kill switch, rejects new orders at both risk
  and execution layers, cancels safe pending entries, and does not liquidate.
- Kill-switch reset requires explicit owner confirmation, then leaves the
  system paused until a separate resume action.

The header and Control Center both expose the stop control. Both use the same
typed `STOP` confirmation dialog. The backend remains authoritative if a
client is stale or bypassed.

## Failure injection

The Control Center scenarios call stateful backend paths, not visual toggles:
profit target, daily loss, drawdown, broker disconnect, market-data failure,
stale price, partial fill, duplicate order, reconciliation failure, manual
trade, manual withdrawal, tax warning, and kill switch.

## Deployment boundary

For a private demo deployment, use PAPER mode and no broker credentials. For a
production deployment of the dashboard service, set:

```text
TRADEFORGE_ENV=production
TRADEFORGE_DASHBOARD_TOKEN=<owner-only-secret>
TRADEFORGE_CORS_ORIGINS=<exact-frontend-origin>
```

Requests fail closed without the owner token. The current token guard is a
local/private deployment boundary, not a substitute for a hardened identity
provider, TLS termination, secure session cookies, rate limiting, audit-backed
authentication, and operational secret management. Those remain required
before any internet-facing production deployment.

## Automatic paper session

`START AUTO` starts the deterministic PAPER worker. It advances synthetic
quotes, produces bounded Demo Trend v1 intents, applies RiskEngine checks, and
submits PaperBroker orders on a short interval. It is not a live strategy and
has no broker credentials. `PAUSE AUTO` stops the worker without selling.

`ENOUGH FOR TODAY` is a separate deliberate action. It pauses automatic paper
trading and submits bounded SELL orders for every open simulated position so
the session's simulated result is realized. It is not the emergency kill
switch. The UI requires a typed `CLOSE` confirmation.

## Known limitations

The dashboard is production-built and paper-safe, but the demo runtime still
uses the local SQLite development adapter and synthetic state. PostgreSQL,
durable worker supervision, external identity, encrypted production backups,
browser E2E coverage, and a real market-data service are not complete. No live
broker adapter or real-money order path exists.
