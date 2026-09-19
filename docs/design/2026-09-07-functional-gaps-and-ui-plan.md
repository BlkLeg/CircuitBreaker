# Functional gaps and UI-first completion plan

Date: 2026-09-07  
Analysis baseline: `tech-cleanup` around commit `702101ac`  
Status: Assessment retained as historical evidence. The seven workflow designs and unified navigator were approved on 2026-09-07; implementation plans are recorded separately.

## Approved implementation plans

Continue from the [approved UI plan index](approved-ui/README.md). It records all eight approved designs, sequencing, contracts, and acceptance gates. The navigator will replace both the top-right Routes menu and the command palette, while preserving the dock. Every surface must follow the active theme; Gruvbox is the canvas reference theme only. Metric alert rules are now selected scope, with advanced alert policies still deferred.

The findings below describe the original inspection baseline and are not a fresh assertion that every defect remains unfixed. Recheck current code before implementing each slice. Earlier future-tense design sequencing and conditional scope below are superseded by the approved plan index.

## Purpose and working order

Complete the workflows Circuit Breaker already promises, improve features whose current behavior is unreliable, and identify a small number of useful extensions. Add helpers where they enable a concrete behavior or remove repeated work. Avoid introducing frameworks or placeholder features without a working use case.

The map refactor is proceeding separately. This assessment excludes its structural changes, but includes backend behavior that affects topology accuracy.

The agreed next phase is to design the missing or incomplete user interfaces first, then implement the backend contracts needed to fulfill those designs. The contracts below are proposals, not claims about current functionality. Existing backend correctness defects remain required work even when they need little or no new UI.

## Findings

### 1. Webhook notifications can treat failed delivery as success

Slack, Discord, and Teams delivery functions discard the HTTP response. Their retry wrapper retries exceptions, but the underlying request helper returns error responses without raising. The Settings Test path checks response status separately, so testing and production delivery behave differently.

An isolated, in-memory reproduction supplied HTTP 500 responses to all three providers. Each dispatch returned normally after one attempt.

**Minimum implementation:** share a delivery-response validator between testing and production delivery. Define accepted responses, retryable failures, and sanitized error messages. Preserve the existing outbound-request protections.

**UI design:** improve the existing notification configuration and Test results. Show whether delivery was accepted or failed and give an actionable, sanitized reason. Do not imply that a successful test proves future deliveries will succeed. Review whether existing failure audit entries can provide a useful link to diagnostics before adding a new delivery-history store.

**Acceptance:** successful delivery, HTTP 429, HTTP 500, invalid credentials, missing configuration, and retry exhaustion produce defined outcomes. A rejected response cannot be reported as success.

Evidence: [notification_worker.py](../../apps/backend/src/app/workers/notification_worker.py), `notify_slack`, `notify_discord`, `notify_teams`, and `_dispatch_notification`; [url_validation.py](../../apps/backend/src/app/core/url_validation.py), `safe_async_request`; [notifications.py](../../apps/backend/src/app/api/notifications.py), `_ok_from_resp`.

### 2. Blast radius confuses connectivity with operational dependency

The dependency builder turns every pair of hardware devices sharing a network into a bidirectional dependency. Two independent machines on one subnet therefore appear to depend on each other. An isolated reproduction confirmed those adjacency edges.

The traversal also omits explicit service-to-storage relationships. It can overstate an endpoint outage while missing services affected by storage failure. Expanding every shared network into device pairs also creates quadratic work.

**Minimum implementation:** introduce a dependency-edge builder that distinguishes hosting, dependency, and connectivity. Preserve dependency direction and include storage consumers. Resolve names and status in bulk where traversal currently performs individual lookups.

**UI design:** refine the existing impact panel to explain why an asset is listed as affected. Distinguish confirmed dependencies from inferred relationships and connectivity. Do not present ordinary subnet membership as proof of service failure.

**Acceptance:** an independent subnet peer is not treated as dependent; a host includes its guests and services; a storage failure includes its explicit consumers; cycles terminate; each impact has a traceable relationship path.

Single-point-of-failure scoring should follow this correction. Scoring the current graph would amplify incorrect assumptions.

Evidence: [dependency_graph.py](../../apps/backend/src/app/services/intelligence/dependency_graph.py), `_build_adjacency`, `_resolve`, and `calculate_blast_radius`.

### 3. Docker discovery needs a reliable reconciliation contract

Newly discovered containers are created without `hardware_id` or `compute_id`, leaving their host relationship unresolved. Discovery returns the same empty list for failure and a successful empty inventory. The sync layer can consequently report success after discovery fails. Its `if seen_container_ids` guard also prevents stopping stale records when the last container disappears.

**Minimum implementation:** return a structured discovery result containing outcome, source identity, and observed objects. Reconcile disappearance only after successful enumeration, scope reconciliation to its source, and resolve the container's parent explicitly. Partial enumeration must not be interpreted as authoritative absence.

**UI design:** extend the existing Docker integration surface with source/host association, last successful sync, current outcome, and an actionable failure state. Allow an unresolved parent to be corrected without requiring users to understand internal database IDs. Show how rediscovery treats an existing manual assignment.

**Acceptance:** daemon failure preserves existing observations; a successful empty scan stops disappeared containers; recreation avoids duplicates; source changes do not reconcile unrelated inventory; user-assigned parentage is preserved according to an explicit policy.

Evidence: [discovery_safe.py](../../apps/backend/src/app/services/discovery_safe.py), `docker_discover`; [docker_discovery.py](../../apps/backend/src/app/services/docker_discovery.py), `sync_docker_topology`.

### 4. Inventory lists still perform repeated per-entity queries

Hardware listing calls its serializer for every record. That serializer independently fetches tags and attached documents. Those two operations alone add approximately two queries per hardware record, before relationship loading and other work. Similar patterns remain in other entity services. Core inventory list endpoints also return unbounded lists.

**Minimum implementation:** extend the existing attachment helpers with bulk reads keyed by entity ID, then use them in list serialization. Add consistent pagination and lightweight selector queries where appropriate. Keep the API and frontend migration compatible so existing callers do not silently receive truncated inventory.

**UI design:** decide pagination, filtering, search, sorting, and selection semantics together. Clearly distinguish selecting the current page from selecting all matching records. Entity pickers must still find objects outside the currently loaded page. Avoid adding a new page solely for this work.

**Acceptance:** list query counts do not grow by a fixed number for every entity; filters and sorting operate across the intended dataset; page boundaries do not lose selections unexpectedly; selectors can locate all eligible records.

The existing load harness should measure the improvement. Its largest tier contains 500 topology entities and 200 monitors, and it explicitly leaves synthetic agents, agent telemetry rate, and publish-to-WebSocket latency unmeasured. Extend coverage and collect results before making scale claims. No application latency benchmark was run during this assessment.

Evidence: [hardware_service.py](../../apps/backend/src/app/services/hardware_service.py), `_to_dict` and `list_hardware`; [entity_tags.py](../../apps/backend/src/app/services/entity_tags.py); [loadgen/config.py](../../scripts/loadgen/config.py).

### 5. Vulnerability results present more certainty than matching supports

Version ranges use string ordering: `1.10` sorts before `1.9`. Ingestion keeps only the first applicability match and collapses an exclusive upper bound into a value later compared inclusively. Entity identification is also limited; for example, services are matched using their display name without a version.

An empty result displays green “No known vulnerabilities” without establishing feed freshness or whether the entity could be identified adequately.

**Minimum implementation:** introduce explicit assessment states for unavailable data, stale data, insufficient identity, and completed assessment. Correct applicability matching, retain inclusive/exclusive boundary semantics, and return an unknown assessment when version interpretation is unsupported. A generic semantic-version comparator alone will not cover every vendor's version scheme.

**UI design:** revise the existing vulnerability panel and feed settings. Display feed age, identity used for matching, and assessment limitations. Distinguish “no matches in this assessment” from an assurance that an asset is safe. Provide a clear next action when identity or feed data is missing.

**Acceptance:** an empty or stale database cannot imply a clean assessment; unrecognized products remain unassessed; version ordering and exclusive bounds are tested; multiple applicability entries are retained and evaluated correctly.

Offline feed import, triage, and map badges are separate scope decisions. They should not block correcting the current panel's certainty.

Evidence: [cve_service.py](../../apps/backend/src/app/services/cve_service.py), `lookup_cves`, `_parse_nvd_cve`, and `_resolve_entity`; [VulnerabilityPanel.jsx](../../apps/frontend/src/components/details/VulnerabilityPanel.jsx).

### 6. Inventory portability lacks a complete, clearly named workflow

Settings labels the JSON export “Full Backup,” although it excludes operational state and layouts. Its exported relationship set also omits hardware connections. An import API and client function exist, but no frontend caller was found.

Adding an Import button alone is insufficient: import merges by database primary key, so another inventory can overwrite unrelated records with matching IDs.

**Minimum implementation:** distinguish inventory export from the existing full-state snapshot. Define a versioned portable format and validate it before applying changes. Explicitly separate restoring a known inventory from merging another inventory, including ID remapping when merge semantics require it.

**UI design:** create an inventory import workflow within Data Management: choose a file, validate it, preview affected entities and relationships, explain collisions and exclusions, select an explicitly supported operation, confirm, and display the result. Present inventory export and full-state backup as different actions with different recovery purposes. Preserve existing confirmation and backup requirements for destructive operations.

**Acceptance:** a supported inventory round trip preserves its declared fields and relationships; invalid input changes nothing; unrelated IDs cannot silently overwrite records; any destructive operation has an accurate preview; completion and failure explain what happened.

Full-state restore already exists and intentionally runs offline. The design should explain that recovery path; an online database-restore endpoint is unnecessary.

Evidence: [SystemSection.jsx](../../apps/frontend/src/pages/settings/SystemSection.jsx), Data Management; [admin.py](../../apps/backend/src/app/api/admin.py), `export_backup`, `_insert_rows`, `_restore_entities`, and `import_backup`; [backup and restore guide](../backup-restore.md).

### 7. Structured API errors need one additional normalization case

The API client already normalizes errors. However, object-valued `detail` payloads pass through to `new Error(message)`. Hardware IP conflicts use that shape, producing an unhelpful `[object Object]` message in the ordinary form error path.

**Minimum implementation:** extend the existing normalizer to extract a safe human-readable message while preserving structured conflict data. Reuse the existing field-error handling rather than introducing another error framework.

**UI design:** show the conflicting asset and the corrective action in the affected form, while preserving entered values. Reuse this error pattern in other forms that return structured validation results.

**Acceptance:** string, validation-array, structured-conflict, network, and server errors render useful messages; sensitive response content is not echoed; users can correct an error without re-entering the form.

Evidence: [client.jsx](../../apps/frontend/src/api/client.jsx), `buildUserMessage`; [hardware_service.py](../../apps/backend/src/app/services/hardware_service.py), `create_hardware`; [HardwarePage.jsx](../../apps/frontend/src/pages/HardwarePage.jsx), save error handling.

## Product decisions beyond the correctness work

### Metric-based alerts

Collected host metrics cannot currently drive configurable threshold/duration rules. A narrowly scoped evaluator feeding the existing notification pipeline could enable useful alerts on already collected data.

If selected, design a rule workflow around an available metric, target selection, unit, comparison, threshold, duration, recovery behavior, severity, and notification destination. Specify missing/stale data behavior and hysteresis so stale samples or boundary noise do not produce misleading alerts.

Maintenance windows and advanced alert policy are explicitly deferred in the [support contract](../release/1.0.0-support-contract.md). Treat this as a product expansion, not a broken 1.0 release promise. Keep acknowledgement, escalation, and correlation out of the initial slice unless explicitly selected. Correct webhook delivery before enabling new alert sources.

### Published feature claims

The [README](../../README.md) and [roadmap](../roadmap.md) advertise an interactive rack editor that was not found in the current routes and implementation. README also overstates TrueNAS/UniFi discovery integration: appliance fingerprinting is different from enumerating TrueNAS pools or syncing UniFi controller inventory.

Correct the claims or explicitly select those capabilities for development. A rack editor and new inventory providers are substantial product work, not missing utility functions. Do not create placeholder screens to make the claims appear fulfilled.

## UI design sequence

This sequence organizes the upcoming design work. It does not require backend-only correctness repairs to wait for an unrelated screen design.

| Order | Surface | Design outcome | Backend contract to settle |
| --- | --- | --- | --- |
| 1 | Data Management and inventory import | Clear export/backup distinction; validated import preview and result flow | Portable schema, supported operations, collision handling, ID remapping, atomic application |
| 2 | Docker integration and discovery results | Source/host assignment; successful, empty, partial, and failed sync states | Source identity, explicit outcomes, reconciliation authority, parent resolution |
| 3 | Vulnerability panel and feed settings | Honest assessment states, freshness, identity, and next actions | Assessment status, freshness metadata, applicability and version semantics |
| 4 | Notification configuration and Test results | Actionable delivery feedback using existing surfaces | Accepted response, retry policy, sanitized failure classification |
| 5 | Impact panel | Explain affected assets and relationship paths | Typed dependency edges, direction, confirmed versus inferred impact |
| 6 | Inventory lists, pickers, and form errors | Consistent paging, selection, search, and correction behavior | Pagination, bulk reads, selector queries, structured errors |
| 7, if selected | Metric alert rules | Narrow rule creation and recovery workflow | Metric availability, units, evaluation state, stale-data behavior, alert transitions |

For each design, capture the entry point, existing components to reuse, empty/loading/error states, role restrictions, primary actions, and acceptance scenarios. Mock data must identify proposed states clearly. Backend implementation follows the reviewed behavior and response contract, with end-to-end verification of the completed workflow.

## Implementation priority and limits

The original correctness priority is notification delivery, dependency accuracy, Docker reconciliation, bulk inventory reads, and truthful vulnerability states. Inventory portability and structured form errors are also required workflow improvements; the UI design sequence above starts with the most substantial missing workflow.

Build on the existing notification worker, dependency traversal, entity attachment helpers, backup builder, error normalizer, and load harness. This assessment does not justify a replacement architecture, new graph engine, second backup system, or second benchmarking framework.

This document complements the [2026-09-05 feature assessment](2026-09-05-missing-features.md), but current source and the support contract take precedence where recommendations differ. In particular, a load harness already exists, the public API is explicitly not a stable 1.0 contract, and advanced alert policy is deferred.

## Verification record

- Read-only inspection of frontend callers, backend services, tests, product claims, support boundaries, and existing performance tooling.
- Isolated execution of the existing notification functions with mocked HTTP 500 responses: Slack, Discord, and Teams returned normally after one request each.
- Isolated execution of the existing dependency adjacency builder: two independent hardware records sharing a network became mutual dependencies.
- No live delivery, discovery, import, database mutation, or load benchmark was performed. The reproductions validate the identified function behavior, not a deployed end-to-end workflow.
- No application files or data were changed by the analysis. This document is the only change made to record it. Concurrent map work belongs to its separate implementation effort.
