# ADR 0014: Frontend and Live Gating

- Status: Accepted
- Decision: React/TypeScript is the target terminal UI, but visual mode badges
  are backed by server-side gates. UI controls never authorize live execution by
  themselves.
- Reason: Professional UX must explain state without becoming a security
  boundary.
