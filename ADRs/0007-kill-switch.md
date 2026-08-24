# ADR 0007: Kill Switch Semantics

- Status: Accepted
- Decision: STOP EVERYTHING persists a global execution block below the AI
  layer, cancels safe pending entries, and never liquidates positions.
- Reason: Freezing automation is safer and semantically distinct from emergency
  liquidation.
