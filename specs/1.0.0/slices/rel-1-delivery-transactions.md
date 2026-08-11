# REL-1 — Delivery and Transaction Contracts

**Requirements:** REL-01, REL-02, REL-03, REL-04, REL-06
**Depends on:** SRV-2 worker inventory

## Primary touchpoints

- `apps/backend/src/app/workers/`, `core/nats_client.py`, agent link/dispatch services
- `apps/agent/internal/frame/`, `link/`, `spool/`, `seqguard.go`
- Migration coordination and `apps/backend/src/app/core/audit_chain.py`

## Build sequence

1. Inventory every job/message with producer, durable store/subject, consumer, transaction, ack point,
   retry, timeout, ordering, idempotency key, dead-letter, and operator visibility.
2. Move acknowledgements after durable logical commit; make redelivery safe with database uniqueness or
   atomic state transitions. Do not claim transport-level exactly-once.
3. Define agent sequence/replay window across reconnect, spool replay, server restore, and re-key.
4. Test duplicate, reordered, delayed, replayed, malformed, and oversized frames plus worker messages.
5. Define Redis/NATS loss per feature as reject/queue/degrade/retry and instrument every disposition.
6. Serialize migrations/advisory locks and audit-chain append under real PostgreSQL concurrency.

## Verification and done

Run Go frame/link/spool race tests and backend worker/agent/audit tests, then multi-process PostgreSQL,
NATS, and Redis fault integration. Reconcile producer count, durable input, logical effects, ack/dead
letter, and audit. Done means no silent loss and every duplicate has one logical outcome.
