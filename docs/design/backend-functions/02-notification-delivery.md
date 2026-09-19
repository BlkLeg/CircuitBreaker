# 02 · Notification delivery and acknowledgement correctness

UI consumer: notification destinations/routes/Test feedback. Downstream dependency: metric alert firing/recovery.

## Current behavior to preserve and repair

Existing worker supports Slack, Discord, Teams, and email; severity-floor matching and sink deduplication across routes already exist. Email Test/production now share SMTP send_alert behavior. Preserve these fixes and notification_secrets encryption/redaction.

Webhook senders ignore response status and return normally if the URL is missing. Unknown providers also return. process_alert gathers delivery exceptions and writes audit entries without returning a failure to the outer consumer, which then acknowledges the message. Its Redis dedup key is set before any send, so a retry can be suppressed even when delivery failed. The durable consumer listens to `alert.>` on `CB_EVENTS`; do not publish new metric events only to the unrelated `notifications.alert` constant.

## File plan

| File under app/ | Action / ownership |
| --- | --- |
| schemas/notifications.py | New: relocate existing sink/route DTOs from API; add DeliveryOutcome, TestResult, validated alert envelope. |
| services/notification_delivery.py | New: provider payload construction, response/error classification, bounded attempt orchestration. Keep four small adapters together initially. |
| services/notification_routing.py | New: select enabled eligible sinks, deduplicate destinations, aggregate outcome, stable event identity. |
| services/notification_secrets.py, notification_severity.py, smtp_service.py | Reuse; do not duplicate encryption, severity-floor, or SMTP setup. |
| db/models/notifications.py | Extend with minimal NotificationDelivery receipt/claim records when enabling retry-safe per-sink dispatch. |
| workers/notification_worker.py | Retain NATS lifecycle and ack/nak/dead-letter ownership; delegate delivery/routing. |
| api/notifications.py | Retain authorized CRUD routes; delegate Test to the same delivery service. |
| core/subjects.py, core/nats_client.py | Reuse subject/stream owner; only additive event identity/publish acknowledgement support as required. |

No generic notification plugin system or delivery-history product is needed. The receipt table is reliability bookkeeping, not a new unapproved history UI.

## Function and result plan

| Callable | Responsibility |
| --- | --- |
| classify_http_response(status, headers, provider) -> DeliveryDecision | Pure allowlisted acceptance, terminal/retryable rejection, bounded Retry-After; never inspect/echo arbitrary response bodies |
| classify_delivery_error(exc) -> DeliveryDecision | Separate missing config, credential failure, timeout, network, and policy rejection with safe text |
| build_provider_payload(provider, event) -> mapping | Existing provider payload formats and severity; no database or network |
| send_once(provider, config, event) -> DeliveryOutcome | Bounded outbound request/SMTP call; raises or returns explicit failure, never implicit success |
| deliver_with_policy(provider, config, event, policy) -> DeliveryOutcome | Bounded attempt count/total deadline; injected sleeper/clock for tests; no DB lock during network I/O |
| select_delivery_targets(db, event, access_context) -> target snapshots | Both route and sink enabled; severity floor; optional validated rule routing restriction; decrypt only at send boundary |
| claim_delivery(db, event_id, sink_id, now) -> claim/status | Short transaction, unique identity, lease/deadline, accepted/terminal records reusable across redelivery |
| record_delivery_outcome(db, claim, outcome) | Conditional update owned by claim/revision; track safe reason, attempts, acceptance or terminal disposition |
| dispatch_event(event) -> DispatchSummary | Send eligible uncompleted targets, aggregate accepted/terminal/retryable outcomes |
| test_sink_delivery(db, sink_id, actor) -> TestResult | Reuse acceptance/payload/SMTP code; bounded request-time budget; no broadcast through all routes |

DeliveryOutcome contains `state, reason_code, safe_message, provider, sink_id, attempt_count, http_status?, retry_after?, accepted_at?`. Include a delivery/event reference when available. Configuration saved, request accepted, and human receipt remain distinct.

## Retry, deduplication, and consumer contract

1. Resolve stable event ID from a validated new envelope. For legacy messages, prefer stable stream/message identity over title hashing. Never confuse two distinct alerts with the same title.
2. Materialize authorized routing intent without secrets in the event/receipt. Enforce both route and sink enabled at delivery. For metric rules, require the event's requested destination to match persisted rule configuration; producers cannot arbitrarily select sinks.
3. Claim each `(event_id, sink_id)` receipt with a uniqueness constraint and bounded lease. Record accepted/terminal outcomes; retain failed retryable state across redelivery.
4. Re-delivery skips accepted destinations and retries only eligible outstanding ones. Redis may remain a best-effort debounce for legacy duplicate noise, but not the sole record of successful dispatch.
5. Acknowledge only after every target has an accepted or explicitly terminal persisted disposition. Retryable aggregate failures propagate to the existing consumer retry/dead-letter mechanism instead of being merely logged.
6. Missing/deleted/no eligible destinations gets an explicit no_route/configuration disposition and diagnostic—not a success claim. Invalid payloads get safe terminal treatment consistent with existing dead-letter rules.
7. Calculate total retry budget across HTTP attempts and JetStream redeliveries. Avoid multiplying generous retry loops. Cancellation/shutdown must release or expire claims predictably.
8. Exactly-once delivery to arbitrary webhook providers is impossible across a crash after acceptance but before recording. Use provider idempotency keys where supported; expose/document ambiguous outcomes and bounded at-least-once behavior rather than claiming a perfect guarantee.

## Storage and migration

NotificationDelivery lives in db/models/notifications.py with an event/sink unique key, state, attempts, claim owner/lease, next retry, accepted/updated timestamps, and safe reason. No raw credential/config/payload persistence solely for diagnostics. Design sink deletion behavior explicitly: keep an identifier snapshot or use SET NULL/tombstoning without deleting required replay receipts.

Retention must exceed the stream replay/redelivery window and configured retry horizon; the existing CB_EVENTS default is 24 hours but configurable. Purge only terminal records old enough to be safe. Register bounded cleanup in startup/jobs.py, with a stable job ID.

## Verification

Extend services/test_notification_dispatch.py, test_notification_routing.py, test_notification_email.py and API notification tests; add delivery outcome/receipt/concurrent-redelivery tests.

- [ ] HTTP 2xx accepted; 3xx not silently accepted as final delivery; 401/403/configuration errors terminal; 429/transient 5xx/network failures follow bounded policy.
- [ ] Test and production classify identical responses consistently; SMTP configuration remains shared.
- [ ] One sink failing does not resend to an already accepted sink after retry.
- [ ] Redis outage/restart, competing consumers, crash-before-send, crash-after-accept, NATS reconnect, and retry exhaustion have defined outcomes.
- [ ] No secret URL, password, provider body, raw validation input, or decryption detail leaks.
- [ ] Persisted outcome and ack/dead-letter behavior agree; Test never claims future delivery is guaranteed.
