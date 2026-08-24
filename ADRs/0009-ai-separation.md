# ADR 0009: AI Separation

- Status: Accepted
- Decision: AI can version research artifacts and emit TradeIntent only. It
  cannot call brokers, receive secrets, or change safety configuration.
- Reason: Production models must not self-promote or self-expand authority.
