# TradeForge Broker Integration

## Allowed integrations

Live execution may use only an official documented API, official SDK, or
officially supported FIX connection whose terms permit this use. The adapter
must expose capabilities and enforce the BOT account boundary.

## Explicitly disabled

`MyInvestorAdapterPlaceholder` may exist only as a non-executable design
placeholder with `execution_supported=false`. No browser automation, Selenium,
Playwright, private endpoints, intercepted requests, reverse engineering,
session cookies, or stored website credentials are allowed. `XtbAdapterPlaceholder`
is also non-executable until separately reviewed.

## Capabilities

The target interface discovers `supports_fractional`, `supports_market_orders`,
`supports_limit_orders`, `supports_streaming`, `supports_paper`, `supports_fx`,
`supports_tax_reports`, `supports_official_api`, and `supports_withdrawals`.
Even if a broker reports withdrawal support, `TRADEFORGE_WITHDRAWALS_ENABLED=false`.

## Adapter rules

Adapters never receive strategies or model objects. They receive validated
`OrderRequest` values from the execution service. Unknown submission outcomes
are terminal until reconciliation. Account mismatch is a non-retryable security
failure.
