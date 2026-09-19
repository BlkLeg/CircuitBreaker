# 01 · Inventory queries, selectors, search, and conflict helpers

UI consumers: inventory workspace; navigator asset search; Docker parent pickers; transfer validation; alert target selection.

## Current behavior and intended split

hardware_service.list_hardware builds an unbounded query and calls _to_dict per entity; that serializer separately reads tags/documents and traverses relationships. A bulk IP-conflict map already exists and should be extended if necessary, not replaced. Search performs seven unbounded queries then slices to 20. Existing api/assets.py handles uploaded icons/branding; **do not put inventory selectors there because its name sounds appropriate**.

| File under app/ | Action and responsibility |
| --- | --- |
| schemas/inventory.py | New: PageRequest/PageResult, EntityRef, selector result and bounded filter/selection descriptions. |
| schemas/search.py | New: move inline SearchResult out of api/search.py; additive canonical entity identity and completeness fields. |
| services/inventory_queries.py | New: finite per-type query specifications, alias normalization, filter/sort construction, minimal bulk entity references. |
| services/search_service.py | New: cross-type bounded candidate retrieval, deterministic relevance merge, selection-ready result projection. |
| services/entity_tags.py | Modify: bulk attachment readers used by entity list serializers. |
| services/hardware_service.py and corresponding entity services | Modify: explicit paged queries, eager/bulk enrichment, pure serialization from preloaded data. Retain existing CRUD and compatibility list entry points. |
| services/ip_reservation.py | Modify only where needed: page-aware conflict checks against all potential conflicts, safe projection of ConflictResult. |
| api/hardware.py and sibling entity routers | Modify: new explicit paged read contract without changing legacy list return shape silently. |
| api/inventory.py | New: minimal selectors/shared selection validation under /inventory, not general CRUD replacement. |
| api/search.py | Modify: thin service adapter; preserve legacy response during migration. |

## Callable plan

| Proposed callable | Inputs → output | Caller / effects |
| --- | --- | --- |
| get_tags_for_many(db, attachment_type, ids) | Bounded IDs → ID-to-tag-name map, including empty entries | Entity services; read only, explicit join to Tag |
| get_documents_for_many(db, attachment_type, ids) | IDs → ID-to-summary map with deterministic ordering | Entity services; select metadata, never document bodies |
| build_entity_query(type, filters, access) | Validated query spec → SQL select and separate count plan | Entity services/search; no execution or commits |
| resolve_entity_refs(db, refs, access) | Grouped canonical refs → minimal authorized metadata map | Impact/selectors; bounded/chunked per type, no rich detail serializer |
| list_hardware_page(db, query, access) | Query → PageResult[HardwareSummary] | Router; eager load needed relationships and enrich in bulk |
| search_entities(db, query, access, limit) | Text/type filters → ranked SearchResult list | Search API; bound each SQL candidate set and final merge |
| list_entity_options(db, types, query, selected_refs, access) | Query plus existing selection → bounded choices and authorized selected labels | Selector API; distinguish deleted/unavailable selection |
| validate_selection(db, spec, action, access) | IDs or filter scope/exclusions → authorized exact action scope/count | Existing bulk-action boundary only; no new arbitrary bulk actions |

Serializer helpers must not fall back to per-row queries when a bulk map has an intentionally empty entry. Separate list summaries from detailed entity responses without dropping fields existing clients require.

## API/compatibility plan

- Preserve existing `GET /hardware` list response while introducing an explicit `GET /hardware/page` envelope (same pattern on migrated types); register static paths before `/{id}`. Alternatively use one explicit negotiated format, but settle it once before client work—never a silently truncated legacy list.
- Page response: `items, total, limit, offset, sort` with stable unique tie-breaker. Filters/counts must describe the same authorized scope. An offset page is not a frozen snapshot; concurrent changes are reflected honestly.
- New `GET /inventory/options` supplies minimal selectors; validate type/action eligibility on the server.
- Keep `GET /search` compatible, add canonical `entity_type/entity_id` alongside legacy `id/type/action_url`. Frontend owns the canonical route/detail mapping. Do not generate arbitrary URLs from stored input; keep legacy action_url values until coordinated migration fixes collection activation.
- Cross-type ranking needs deterministic exact/prefix/substring scoring and tie-breaking. Apply per-type query limits before materialization; avoid source-order starvation. If the server cannot establish exhaustive results, return an explicit has_more/truncation indicator in the new envelope.
- “Select all matching” is a filter snapshot plus exclusions. Before an existing destructive action runs, resolve and bind the exact intended ID set/count, then reject changed scope or request re-review. Do not apply a fresh unbounded predicate after confirmation. No generic selection persistence table until an actual action needs one.

## Error and security work

Extend ConflictError/standard responses with sanitized structured IP conflict metadata while retaining the existing ip_reservation rules. Preserve hardware's current conflict blocking and host-chain semantics. Frontend normalization remains necessary for older object-valued responses during migration.

Search currently gets mount-level authentication; review role/token resource scopes explicitly when extracting service queries. Do not infer row-level ACLs that do not exist, but prevent aggregate endpoints from becoming a bypass of existing gates. Include disabled/removed resources, malformed IDs, SQL sort injection, wildcard/query length limits, and authorization before counts.

## Tests and completion

New tests beside current suites: services/test_inventory_queries.py, services/test_entity_tags_bulk.py, services/test_search_service.py, api/test_inventory_queries.py, api/test_search.py. Extend current hardware/IP-conflict tests.

- [ ] Query counts are bounded by page/chunk/type, not by entity count; measure tags, docs, storage summaries, environment relationships, and conflict calculation.
- [ ] Filters precede paging; sort ties and null values are deterministic; empty pages and counts are consistent.
- [ ] Full-data consumers (map, export, selectors, reconciliation) are explicitly audited and never receive accidental first-page-only data.
- [ ] Search/options find off-page entities and preserve canonical identity; result limits are pushed to SQL.
- [ ] SQL errors, structured conflicts, stale/deleted selections, and narrowed API tokens have contract tests.
- [ ] Record existing load-harness before/after results; add indexes only after reviewing actual query plans.
