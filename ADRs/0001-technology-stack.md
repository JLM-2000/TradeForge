# ADR 0001: Technology Stack

- Status: Accepted
- Decision: Python 3.12 for research, accounting, tax, orchestration, and the
  executable reference core; SQLite for development and PostgreSQL for
  production; FastAPI for the target API; React/TypeScript for the target UI.
  Profile the hot path before introducing a Rust execution/risk gateway.
- Reason: Python supports quantitative and accounting correctness, while a
  separate Rust gateway can provide predictable low-latency execution if
  measurements justify it. Broker/network latency remains the end-to-end limit.
  Rust must conform to the reference safety behavior rather than weaken it.
