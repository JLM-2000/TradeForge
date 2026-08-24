# ADR 0010: Tax Ledger

- Status: Accepted
- Decision: Maintain a separate Spanish-oriented tax-lot projection using
  Decimal, FIFO, EUR conversion, and explicit professional-review flags.
- Reason: Broker average cost and trading P&L do not necessarily equal fiscal
  basis or taxable result.
- Fee policy: directly related acquisition expenses increase lot basis and
  directly related disposal expenses reduce transmission value; tax payments,
  withdrawals, and trading P&L remain separate event types.
