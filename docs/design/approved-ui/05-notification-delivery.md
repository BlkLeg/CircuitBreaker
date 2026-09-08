# 05 · Notification configuration and honest delivery feedback

Status: approved. Depends on plan 00; must complete before enabling metric-rule notification dispatch in 08.

## Outcome and location

Use the existing Notifications/configuration surfaces to manage destinations and existing severity routes, send a test, and understand accepted, rejected, retrying, or exhausted outcomes. Configuration saved, endpoint accepted, and message read by a person are different events.

Existing integration points: frontend `pages/NotificationsPage.jsx`, `components/settings/NotificationsManager.jsx`, settings forms/client; backend `api/notifications.py`, `workers/notification_worker.py`, `core/url_validation.py`, `services/notification_severity.py`, and existing secret/routing services.

Reuse the current notification worker, destinations, routing, and diagnostics. Add a small shared response-classification helper near existing delivery logic rather than another dispatch pipeline.

## Delivery contract

- Test and real dispatch share response acceptance and error classification. A rejected HTTP response is not success just because the request returned without throwing.
- Distinguish validation/configuration failure, authentication rejection, rate limit, transient upstream/network failure, timeout, and terminal failure.
- Retry only eligible failures with bounded attempts and backoff; respect valid bounded Retry-After where appropriate. Do not blindly retry invalid credentials/configuration.
- Outcomes include destination/provider, accepted/failed state, attempt count, safe reason, and existing correlation/request information. Expose live retry stages only when backend lifecycle data exists.
- A 2xx/accepted response means the provider accepted the request. Do not claim human receipt or guaranteed future delivery.
- Keep outbound-request protections, secret encryption/redaction, and provider-specific payload requirements intact.
- Reuse existing audit/diagnostic information for troubleshooting. Do not invent a durable delivery-history store to fill a visual table; show unavailable history honestly if necessary.

## Work packages

- [ ] **N1:** Expand existing notification worker/API tests to capture Test versus production parity for Slack, Discord, Teams, and other already supported delivery adapters as applicable.
- [ ] **N2:** Define a shared acceptance/retry classification and sanitized result contract. Identify existing diagnostic fields that can support the approved feedback panel.
- [ ] **N3:** Build destination editing, existing severity routing, Test progress/result, and contextual error states. Preserve masked secrets unless deliberately changed; never reveal stored credentials in forms or diagnostics.
- [ ] **N4:** Correct worker/provider result validation and bounded retry behavior. Ensure final outcome reaches the API/job/diagnostic surface accurately.
- [ ] **N5:** Wire configuration and Test independently. A failed test does not discard valid unsaved configuration or imply it was saved.
- [ ] **N6:** Cover destination removal/disable, missing routing, insufficient permissions, and repeated clicks. Make configuration and delivery actions separately auditable using existing mechanisms.
- [ ] **N7:** Update operational troubleshooting guidance and document exactly what Test success establishes.

## Acceptance and tests

- Provider HTTP 500 cannot be reported accepted; retries exhaust into a visible terminal failure.
- HTTP 429, invalid credentials, malformed destination, missing configuration, network timeout, successful acceptance, and retry exhaustion have defined outcomes.
- Test and real dispatch classify the same provider response consistently.
- Secret URLs/tokens/passwords and raw error bodies do not appear in user messages or logs; outbound policy tests remain intact.
- Existing severity selection/routing works, with disabled/deleted destinations handled honestly.
- Button progress, safe retry, permission restrictions, keyboard interactions, and all theme states pass.
- Existing notification dispatch/routing/email/API tests remain green. Use fake endpoints in tests; do not send real notifications during automated verification.

Advanced escalation, acknowledgement, correlation, and new provider integrations are not part of this delivery correction.
