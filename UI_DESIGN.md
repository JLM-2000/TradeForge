# TradeForge UI Design

## Information architecture

```text
Overview
  Dashboard | Markets | Portfolio | Positions | Orders
Research
  Strategies | Backtests | Analytics
Controls
  Risk | Control Center | Withdrawals
Records
  Tax | Audit
Operations
  System Health | Settings
```

## Persistent header

Every screen shows `TradeForge`, the current mode, BOT status, broker status, market
status, and risk status. Paper mode reads `PAPER - SIMULATED CAPITAL`; any
future live mode has a persistent high-contrast `LIVE - REAL MONEY` badge.

## Dashboard wireframe

```text
+--------------------------------------------------------------------------+
| TradeForge | PAPER - SIMULATED CAPITAL | BOT HEALTHY | DATA HEALTHY | RISK OK  |
+-------------+------------------------------------------------------------+
| navigation   | Equity / Cash / Invested / Withdrawable / P&L cards           |
|              +------------------------------------------------------------+
|              | Equity curve, realized/unrealized split, drawdown chart     |
|              +-----------------------------+------------------------------+
|              | Owner hard ceiling            | Current risk budget          |
|              | Max position / loss / DD     | target / allowed range       |
|              +------------------------------------------------------------+
|              | Positions, orders, circuit breakers, notifications          |
|              +------------------------------------------------------------+
|              | [PAUSE TRADING]       [RESUME]        [STOP EVERYTHING]      |
+-------------+------------------------------------------------------------+
```

The red stop control is separated from pause/resume. Stop freezes automation,
never liquidates positions, shows activation evidence, and has no casual reset
button. Stale data displays its last update and cannot look live.

## Design system

Dark and light themes use a restrained navy/slate canvas, high-contrast text,
blue for neutral actions, amber for warnings, and red only for dangerous
controls or critical state. Use tabular numerals, dense but breathable data
tables, keyboard focus rings, semantic labels, accessible charts, and reduced
motion. Do not use casino imagery, flashing P&L, confetti, or pressure-oriented
deposit prompts.

## Charts

The target chart layer supports equity, realized/unrealized P&L, drawdown,
exposure, cash versus invested, fees, reserve, benchmark, and candlesticks with
execution markers. Every chart shows timezone, source, and last update.

## Implemented terminal checkpoint

The current React/Vite terminal implements the paper operations shell, mode
banner, metric cards, equity chart, risk budget, positions, orders, strategy
registry, research sections, tax/withdrawal views, audit, health, responsive
navigation, WebSocket refresh, stateful failure injection, and the typed
confirmation flow for `STOP EVERYTHING`. It is deliberately not presented as
live trading.
