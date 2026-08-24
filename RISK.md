# TradeForge Risk Policy

## Authority hierarchy

```text
Owner hard limits > persisted controls/kill switch > RiskEngine
> execution service gate > strategy/AI > model confidence
```

AI proposes. The RiskEngine decides. Execution enforces independently.

## Initial policy

- `RISK_MODE=MANUAL` unless explicitly configured.
- `LONG_ONLY=true`.
- Leverage is exactly `1`.
- Margin, CFDs, futures, options, short selling, crypto, speculative FX,
  leveraged products, and structured products are not in the V1 allowlist.
- No martingale, all-in, revenge, or unbounded loss-recovery sizing.
- Estimated tax reserve is excluded from risk-available cash by default.

## Checks

Account, mode, kill switch, pause state, reconciliation, data freshness,
instrument allowlist, cash, position/exposure ceilings, open-position count,
daily/weekly/monthly P&L, drawdown, order rate, duplicate intent, spread,
market hours, broker health, and market-data health are checked before order
creation. Any unknown or unhealthy prerequisite rejects the order.

## P&L limits

Loss budgets are stored as positive EUR magnitudes and compare against negative
P&L thresholds. Profit targets are independent policies. A reached limit stops
new entries and may cancel pending entries if configured. It never liquidates
positions unless a future, separately designed emergency-liquidation workflow
is explicitly enabled.

## Manual and auto risk

Manual mode uses owner-selected notional within hard ceilings. Auto mode may
select a bounded target only inside owner-defined minimum and maximum values.
The AI cannot modify the envelope. A broker minimum above the approved amount
is rejected rather than silently increasing size.

## Circuit breakers

Daily/weekly loss, drawdown, rejected-order bursts, broker/data outages, stale
prices, unexpected fills, latency, database integrity issues, and reconciliation
mismatches pause automated entries and create auditable events.
