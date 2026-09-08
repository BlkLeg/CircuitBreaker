# 07 · Inventory lists, selection, pickers, and form correction

Status: approved. Depends on plan 00; provides reusable behavior for transfer, Docker, alerts, and navigator entity activation.

## Outcome and location

Upgrade existing inventory pages rather than adding another Inventory application. Start with Hardware as a complete vertical slice; adopt the same list contract on Compute, Services, Storage, External Nodes, IPAM, and Other Assets where appropriate, preserving their domain-specific actions.

Existing integration points: frontend `pages/HardwarePage.jsx`, sibling inventory pages, common table/form components, `api/client.jsx` (`buildUserMessage`, field-error extraction); backend `services/hardware_service.py`, `services/entity_tags.py`, attachment/document helpers, and corresponding entity list services.

Proposed boundaries: a small list-query/selection hook, shared pagination controls, reusable async entity selector, and an extension to the current error normalizer. Do not force every entity form/table into one large configurable framework.

## List and selection contract

- Server-side query parameters define search, filters, stable sort with unique tie-breaker, and pagination. A response exposes items and honest page/total information.
- Migrate unbounded-list callers explicitly. Keep a compatible old shape or use an explicit paginated path/parameter during transition; never silently return only the first page to an old caller.
- Map/topology, export, relationship-building, and other complete-dataset consumers need an intentional full-data contract. Audit them before changing shared clients.
- “Select page” selects only visible page IDs. Explicit “Select all matching” captures the filter/sort-independent matching scope, count, and exclusions—not merely the loaded IDs.
- Paging preserves explicit selections. Changing the filter/search clears or explicitly reconfirms selection scope; do not silently retarget an all-matching action. Show a visible selected count and clear action.
- For all-matching bulk mutation, the server revalidates permissions and the intended matching set/count before confirmation/application; dataset changes must not silently enlarge destructive scope.
- Global entity pickers query all eligible entities independently of the current page, with bounded search, stable IDs, role filtering, and retained selected labels.
- Detail panels and navigator results need a canonical selected-entity link/state contract that survives refresh/Back/Forward where supported.

## Structured error contract

Extend the existing axios normalizer; retain safe readable message, status/code, field errors, structured conflict identity, and request ID. Handle strings, validation arrays, structured objects, network failures, and server failures. Do not display serialized arbitrary objects or raw backend diagnostics.

An IP conflict identifies the authorized conflicting asset, attaches feedback to the relevant field, offers correction/inspection, and preserves form values. Correcting the field and resubmitting follows normal save semantics. Do not add a generic “override conflict” action unless the domain contract explicitly permits it.

## Work packages

- [ ] **W1:** Audit list/selector consumers and existing pagination helpers. Specify compatibility, stable sorting, total-count meaning, all-matching scope, and selected-entity navigation before changing API shapes.
- [ ] **W2:** Add regression tests for per-record query growth; extend tag/document/relationship bulk loaders and serialization in current services.
- [ ] **W3:** Implement bounded server pagination and selector queries; apply filters before pagination and permissions before counts/results.
- [ ] **W4:** Build Hardware's approved list controls, page/all-matching selection, detail panel, and async parent/entity picker against contract fixtures.
- [ ] **W5:** Extend error normalization and implement inline structured conflict correction. Keep existing validation-array handling and saved-form behavior intact.
- [ ] **W6:** Wire real data with stale-request protection, explicit loading/empty/error states, and post-mutation refresh that keeps context.
- [ ] **W7:** Migrate sibling entity pages in small tested batches. Preserve different domain columns/actions and all complete-dataset callers.
- [ ] **W8:** Measure database query counts and response characteristics with the existing load harness; record before/after figures and remaining bottlenecks.

## Acceptance and tests

- List query counts no longer grow by a fixed extra pair of tag/document queries per entity.
- Search/filter/sort operate on the intended full dataset; pages have deterministic boundaries and correct totals.
- Explicit selections survive paging; all-matching differs from current-page selection and handles exclusions and dataset/filter changes safely.
- Pickers find valid objects outside the visible page; removed/inaccessible targets produce actionable validation.
- Structured IP conflicts never display “[object Object]” and never discard the user's form.
- Empty inventory, zero filtered results, loading, server failure, concurrent deletion/update, and unauthorized actions are distinguishable.
- Existing map/export consumers retain complete data. Entity navigation lands on the chosen object.
- Real-browser theme, mobile/local table scrolling, keyboard selection, enlarged text, and E2E paging/correction tests pass.

Do not claim infinite scale or add virtualization until measured row/render behavior requires it.
