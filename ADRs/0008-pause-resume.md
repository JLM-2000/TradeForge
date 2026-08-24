# ADR 0008: Pause and Resume

- Status: Accepted
- Decision: Pause blocks entries but preserves monitoring and positions. Resume
  requires health, authorization, and reconciliation checks.
- Reason: Normal control must not imply liquidation or conceal state.
