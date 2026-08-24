# TradeForge

TradeForge is a personal, proprietary, paper-first quantitative trading platform.
It is designed to protect capital and preserve an auditable history before it
optimizes a strategy.

## Safety status

- `MODE=PAPER` is the default.
- No live broker adapter exists in this repository.
- `LIVE_TRADING_ENABLED=false` is hard-coded in the initial safety profile.
- MyInvestor execution is permanently disabled and has no automation path.
- Withdrawals, deposits, bank access, and account transfers are not broker
  capabilities of TradeForge.
- `STOP EVERYTHING` is persisted below the strategy layer and blocks the
  execution service after restart.
- This software is for the owner's own money only. It is not investment advice,
  a customer-account service, or a guarantee of legal or tax compliance.

## Current checkpoint

This repository contains the M0 architecture and M1 safety/domain foundation,
plus a deterministic paper broker, risk engine, controls, reconciliation,
tax-lot, tax-reserve, and withdrawal-planning designs implemented as a small
Python core. The professional web terminal is intentionally a later milestone.

## Requirements

- Python 3.12+

The core uses the standard library at this checkpoint so the safety suite can
run in a clean environment. PostgreSQL, FastAPI, React, and production market
data integrations are planned, not silently substituted by demo code.

The execution design targets sub-second local decisions. It does not claim
sub-second fills: official broker routing and network latency are measured
separately. AI never sits synchronously in the order path.

## Run

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m tradeforge.safety_suite
PYTHONPATH=src python3 -m tradeforge
```

The package is source-layout based, so set `PYTHONPATH=src` when invoking
modules directly from a checkout:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m tradeforge.safety_suite
```

`make safety-test` produces both `artifacts/safety-report.json` and a human
readable console report.

## Dashboard

The dashboard is a React/TypeScript/Vite terminal backed by the PAPER-only
FastAPI runtime. It is deliberately labelled `PAPER - SIMULATED OPERATIONS`;
the hosted demo must not be described as live trading. It supports stateful
paper orders, positions, order lifecycle, health, tax/withdrawal views, audit
events, failure scenarios, and the backend-enforced `STOP EVERYTHING` control.

Run the API and dashboard locally in two terminals:

```bash
PYTHONPATH=src .venv/bin/uvicorn tradeforge.api:app --reload --port 8001
npm --prefix web run dev
```

Open `http://localhost:5173`. The production bundle is served by the API after
`npm --prefix web run build`.

For a non-demo deployment, set `TRADEFORGE_ENV=production` and configure
`TRADEFORGE_DASHBOARD_TOKEN`. The API fails closed without owner authentication.
No credentials, real broker adapters, bank integration, or live order route are
provided by this dashboard.

## Planned progression

```text
DEMO -> BACKTEST -> PAPER -> SHADOW -> READINESS REVIEW -> OWNER APPROVAL -> MICRO LIVE
```

There is deliberately no automatic promotion path.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Requirements analysis](REQUIREMENTS_ANALYSIS.md)
- [Security](SECURITY.md)
- [Threat model](THREAT_MODEL.md)
- [Risk policy](RISK.md)
- [Tax ledger](TAX_LEDGER.md)
- [Broker integration](BROKER_INTEGRATION.md)
- [Broker onboarding](BROKER_ONBOARDING.md)
- [Testing](TESTING.md)
- [Live readiness](LIVE_READINESS.md)
- [Runbook](RUNBOOK.md)
- [Disaster recovery](DISASTER_RECOVERY.md)
- [Performance plan](PERFORMANCE.md)
- [ADR index](ADRs/README.md)
