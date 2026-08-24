# TradeForge Performance Plan

## Target

These are measured engineering targets for paper and shadow environments:

| Segment | Target |
| --- | ---: |
| In-memory intent validation to decision | < 1 ms p99 after warm-up |
| Decision to broker request queued | < 2 ms p99 |
| Dashboard event propagation | < 100 ms p95 |
| End-to-end broker acknowledgement | broker-dependent; measure, never assume |

They are not trading or profitability guarantees.

## Design choices

- AI/ML inference and feature calculation are asynchronous and precomputed.
- The execution path uses immutable in-memory snapshots and fixed-point values
  at boundaries.
- Database writes and dashboard fan-out must not block a validated broker
  request, but every event remains durably recorded.
- Idempotency and kill-switch checks remain on the hot path.
- Stale quotes are rejected; stale speed is not useful speed.
- WebSocket clients receive sequence numbers and last-update timestamps.
- Python is the correctness reference. A Rust gateway is justified only by
  profiling and must pass cross-language conformance tests.

## Measurement

Each attempt records monotonic timestamps for signal, risk start/end, gate,
submit, acknowledgement, and fill. Reports distinguish local processing from
broker and market latency. Development benchmarks use synthetic data only.

## Explicit non-goal

TradeForge is not a colocated high-frequency trading system. A language choice
cannot overcome retail broker throttling, market microstructure, or internet
latency. Safety checks cannot be removed to chase a latency number.
