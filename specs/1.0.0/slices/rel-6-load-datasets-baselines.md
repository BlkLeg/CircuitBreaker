# REL-6 — Load Datasets and Performance Baselines

**Requirements:** REL-21, REL-22, REL-23, REL-24
**Depends on:** RC workload profiles

## Build sequence

1. Create deterministic generators for 1k, 10k, and target-max inventory/edges with realistic graph
   degree, tags, attachments, monitoring history, discovery, and tenant distribution if supported.
2. Create 10, 100, and target-max agent simulators using the production protocol with configurable
   telemetry, readiness, reconnect, spool replay, discovery, and probe results. Validate simulator
   behavior against real agents before using it for claims.
3. Define mixed steady, burst, reconnect, scan, notification, integration, retention, and backup phases.
4. Instrument API p50/p95/p99/error, WebSocket fan-out, queue lag/depth, DB pools/locks/query plans,
   CPU/RAM/disk/WAL, worker fairness, agent catch-up, frontend load/bundle/table/topology FPS and memory.
5. Run on named controlled hardware with warmup, repetitions, confidence/variance, raw output, commit,
   config, tool version, and no hidden background load.
6. Establish baselines without yet declaring unsupported optimistic maxima.

## Verification and done

An independent runner reproduces results within the approved variance. Dataset invariants and agent
simulator conformance pass. Done means raw data and generators are versioned and every reported metric
has a defined collection method.
