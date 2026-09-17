# Changelog

All notable changes to Circuit Breaker are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
while pre-1.0 (a `0.MINOR.PATCH` bump can still carry a breaking change).

**Policy:** starting with 0.4.2, entries here are generated from each
release's notes going forward, cut by cut. Some earlier releases have
narrative write-ups under [`docs/updates/`](docs/updates/) — the newest one
there is v0.3.3. Releases after that (v0.3.4, v1.0.0-rc.1 through rc.4, and
v0.4.0) have neither a write-up there nor an entry here. The most recent heading holds whatever has landed since the last
cut and is *not yet* released — when it actually ships, that heading takes
the release date and a fresh `[Unreleased]` section opens above it for the
next round.

## [0.4.2] — unreleased

`v0.4.0` (tagged 2026-08-31) is still the newest tag and the last version
actually cut on `main` — `git show origin/main:VERSION` reads `0.4.0`, and
`main` has no commits since that tag. `VERSION` in this tree was moved to
0.4.2 by `ef729552`, ahead of an actual release; nothing below has shipped
yet, and this heading records what will ship in the next cut, not a past one.
A large agent/production-readiness effort has also been landing on `dev`
since v0.4.0, but the project's own tracking
(`docs/evidence/2026-08-30-production-readiness-route.md`) carries much of it
as "fixed in working tree, release evidence pending" or "gated, not fixed",
and aims its own next milestone at 0.5.0 — so it is not listed here to avoid
claiming a shipped state that isn't backed by release evidence yet. This entry
covers only the commits below, which are complete, self-contained, and
directly verifiable in this tree.

### Changed

- The vulnerability panel on hardware, compute and service detail views no
  longer renders an empty result as **No known vulnerabilities**. It consumes
  the assessment contract the server already shipped: readiness first (feed
  missing/incomplete/stale, identity missing, version scheme unsupported),
  then the matched identity with its provenance and revision, then findings
  with the CPE evidence and version bounds that produced them. A completed
  assessment with no matches reads **No matches in this assessment**, with an
  explicit caveat that it is not a safety guarantee; a stale feed keeps its
  findings visibly stale. Editors can correct the identity in place — the
  save is revision-checked, keeps entered values on failure, and re-assesses
  immediately (plans 04; see `docs/business_intelligence.md`).
- The **Impact** panel now explains itself instead of showing bare counts.
  Every listed asset can show the typed, provenance-tagged path that connects
  it; a small focused graph (theme-aware, bounded) sketches the same shape;
  inferred relationships are opt-in and labelled when any exist; physical
  links and network memberships are listed separately as connectivity and are
  never counted as impact; and a traversal that stopped at a node/depth/edge
  limit says so — "no dependents found before the traversal limit" is not
  rendered as "nothing depends on this" (plan 06).

- An agent that removed itself with `cb-agent uninstall` now reads as
  **Uninstalled** rather than *Revoked* across the fleet table and the agent
  page, and no longer tells you to go and clean up a host that has already
  cleaned itself up. `AgentSummary` carries `revoked_at`, `revoke_reason` and a
  derived `revoked_by` to distinguish the two (`9f855ad6`).
- Saved map layouts are now versioned behind a `layoutCodec`
  (`schemaVersion: 2`). It reads both older on-disk shapes and writes view
  options nested and flat, so a self-hoster running a rebuilt frontend against
  an unrestarted server, or rolling back a release, keeps reading a layout it
  understands (`454f70c6`).
- `scripts/check_version_parity.py` gained `--write`, and `make version-sync`
  now propagates a `VERSION` bump to every registered file mechanically
  instead of by hand (`ef729552`).

### Fixed

- The navigator's search field no longer draws a permanent outline. `main.css`
  sets `*:focus-visible { outline: ... !important }` as an app-wide baseline,
  and the field is focused the moment the overlay opens — a text input matches
  `:focus-visible` whenever it is focused — so the ring was always on and read
  as a border around the box rather than as a focus cue. The caret does that job
  for a text field, and it is the only element in the panel that has one; every
  other control keeps its ring.

- Secondary text is legible in every theme. `applyTheme` wrote each preset's
  `text` and `textMuted` straight through, so legibility was whatever the
  palette author's eye had settled on: across the shipped presets, 20 of 28
  preset/mode pairs put muted text below WCAG AA's 4.5:1 against the surface it
  sits on, 8 were below 3:1, monokai's dark muted was 1.74:1, and
  `solarized-dark` managed 3.19:1 with its primary text. Both tokens are now
  floored to AA against every surface they can land on, blending toward black or
  white only as far as the threshold requires — a colour that already passes is
  written through untouched, so palettes keep their hue wherever the hue was
  readable. The navigator showed this worst, being almost entirely group labels,
  row descriptions, category filters and footer hints, but nothing about it was
  navigator-specific. The axe suite now opens the navigator and scans it under
  the three worst presets; it had never scanned that surface at all, because
  every page scan runs with the overlay shut.

- `tests/build/test_install_docker_staging.py` no longer hangs forever. The
  harness runs the shipped `stage_docker_deploy` with `curl`, `docker` and `ip`
  stubbed, but not the `install … || sudo install …` pair that writes
  `/usr/local/bin/cb` — so the test reached a real `sudo` and blocked on a
  password prompt on any host that asks for one, taking `make verify-full` with
  it. Both are stubbed now, the sandbox's working directory is pinned so the
  shipped code's `$(pwd)` lookups do not depend on where pytest was invoked
  from, and a test asserts the escalation never happens. The file runs in under
  a second.
- `apps/backend/src/app/security/endpoint_inventory.json` records
  `GET /api/v1/admin/diagnostics`, which shipped in `67dbefb8` without being
  added to the inventory. `test_full_endpoint_inventory_matches_runtime_routes`
  had been failing at "recorded 472 vs runtime 473" ever since. The endpoint is
  gated by `require_role` and `require_auth_always`; recording it changes no
  policy.
- `test_cb_admin_surface.py`'s native-CLI cases work against the current `cb`.
  `67dbefb8` replaced `deploy/cli/cb` with the unified, identity-gated CLI, and
  the test still supplied the old `CB_BIN` variable and no install identity, so
  all four admin groups failed on the identity gate before reaching the binary.
  The test now provisions a `package`-mode identity through `CB_IDENTITY_PATH`
  — which also stops a host's own `/etc` identity leaking into the test — and a
  new case covers the gate refusing a host that has none.
- Playwright no longer runs the whole browser suite against a stranger. The
  preview port (4173) is reused outside CI without checking what answers on it,
  so an unrelated server holding that port silently became the system under
  test: every spec failed in `waitForRouteSettled`, which looks precisely like
  an application regression. A `globalSetup` now refuses that case up front and
  names what actually answered, and `CB_E2E_PORT` moves the suite to a free
  port.

- The global navigator's highlight now follows the pointer. It was driven by the
  arrow keys alone and rows had no hover treatment at all, so hovering gave no
  feedback and Enter opened whichever row the keyboard had last selected rather
  than the one under the cursor. Rows select on pointer movement — deliberately
  on `mousemove` rather than `mouseenter`, so a list scrolling under a
  stationary pointer cannot take the selection away from the keyboard.
- The navigator no longer discards your selection when asset results arrive.
  Entity search is debounced ~200ms, and its results re-ran the effect that
  snaps the highlight to the best local match, so arrowing down during a search
  was silently undone a moment later. The snap now happens once per question;
  the same question with more results keeps the selection. Switching between
  All pages and Recent also starts from the top rather than keeping an index
  that pointed into the previous list.
- The navigator's active row is now exposed to assistive technology. Rows
  carried `id="navigator-option-N"` attributes generated for an
  `aria-activedescendant` that was never wired up, so a screen-reader user was
  never told which row was highlighted. The search field now names the
  highlighted row, whether the keyboard or the pointer moved it. It stays a
  `searchbox` rather than becoming a `combobox` with a `listbox` popup: a
  listbox may not contain the per-row pin buttons, and axe rejects that
  structure outright.
- Arrow keys and Enter no longer disagree in the navigator. Arrows moved the
  highlight from anywhere in the panel while Enter only opened the highlighted
  row when the search field had focus, so after tabbing to a row the two
  diverged. Arrowing now returns focus to the search field.
- The navigator's selected row is no longer distinguished by colour alone; it
  carries an inset edge bar as well.

- The Docker sources panel no longer reports a source as **Synced** when it has
  no idea how the last sync went. `GET /discovery/docker/sources` returned only
  attempt/success timestamps, so a run's outcome was knowable exclusively to the
  browser session that had clicked Sync itself; every other page load fell
  through to "The daemon was reachable and reported 0 container(s)" — including
  for a daemon whose last enumeration failed, which is precisely the
  empty-versus-failed conflation the source-oriented surface was built to end.
  A source now carries its `last_run`, so first load tells the two apart, and an
  attempted source with no run available is reported as **Outcome unknown**
  rather than as success.
- A queued Docker sync no longer sticks at **Sync queued** forever. The panel
  fetched the run once at queue time and never refreshed it, so a completed run
  kept rendering as in-flight and its Sync button stayed disabled until a full
  page reload. Run state now comes from the server on every reload, and the
  locally queued run is dropped as soon as the server speaks for that source.
- A Docker source's container list that could not be *loaded* is no longer
  rendered as a source that reported *no containers*. The failed request is
  reported as unreadable, and the rest of the panel still renders.
- `POST /discovery/docker/sync` now accepts an optional `source_id`, and the
  per-source Sync button sends the source it belongs to. It previously accepted
  the source id from the card and discarded it, always syncing whichever daemon
  was configured at that moment. Posting no body still syncs the configured
  daemon, so the settings entry point and older clients are unaffected.
- Correcting a vulnerability assessment identity for the first time no longer
  fails with a spurious "The identity changed while you were editing." An
  identity read from inventory reported revision 1 while the server compares a
  correction against the operator-override row's revision, which is 0 until one
  exists — so every first correction conflicted with itself. An uncorrected
  identity now reports revision 0, and the panel shows no revision for one that
  has never been corrected, since the number counts corrections.
- The **Set identity** button in the vulnerability panel now opens a form. It
  rendered whenever an entity had no identity at all, but the form behind it was
  gated on an identity already existing, so the button did nothing.
- A notification delivery result now names the destination it belongs to. The
  Notifications page renders one shared result panel above the table and titled
  it by provider alone, which cannot distinguish one of several Slack
  destinations.
- `credential_unavailable`, `delivery_error`, and `request_failed` delivery
  outcomes now carry a next action. All three are emitted in practice and had no
  entry in the guidance table, so they reached the operator with a reason and
  nothing to do about it.
- The Notifications page read a tested sink's provider from a `type` field the
  API does not return (it is `provider_type`), so a failed test request was
  attributed to "The destination" rather than to the provider.

- An agent no longer tears down its own link while applying a self-update.
  The update used to run inline on the `/link` event-loop goroutine, so a
  download occupied the connection's only worker for up to two minutes:
  heartbeats stopped, inbound frames stopped being read, and the backend's
  60-second dead-link deadline routinely closed an otherwise usable
  connection mid-update. Updates now execute on a dedicated serialized worker
  — one at a time, a second instruction refused with an explicit
  `update already in progress` failure — and every `update.status` report
  crosses back to the event loop through a channel, so the one-writer rule
  and sequence ownership stay where they were. The `succeeded` report is
  also durable now: it used to be written to the socket immediately before
  `syscall.Exec`, where a connection drop discarded it with no process left
  to retry it, so the server could miss the outcome of an update that
  actually landed. The outcome is persisted before the live send and
  replayed by the re-exec'd process after its first accepted `hello.ack`;
  the backend accepts the replay idempotently, without a duplicate timeline
  event, and a genuinely new attempt at the same version still records
  normally. A `SIGTERM` mid-download now cancels the HTTP request instead of
  waiting out the two-minute timeout (see
  `docs/design/2026-09-16-agent-deployment-connection-plan.md`).
- The Sigma map renderer requested a `format: 'sigma'` payload the backend has
  never supported, so it silently rendered nothing (`45a49a66`).
- Map node deletion was restored: the delete-target lookup indexed a `Map`
  with bracket syntax, which always read `undefined` and silently disabled
  delete for every node (`abd59cc6`).
- Map tag and hardware-role filters are now composed as a single predicate;
  previously the hardware-role filter's effect ran after the tag filter's and
  overwrote its result for hardware nodes (`c60d2698`).
- `useMapDataLoad` now rejects a topology response superseded by a newer
  request instead of letting a slower, older response overwrite the canvas
  with stale nodes and edges (`97570315`).
- The Cloud View toggle no longer races the map's own topology re-fetch,
  which could apply the toggle's node transform twice with no ordering
  guarantee (`3a8c9213`).
- The Sigma map renderer is now scoped to the active map and its include
  tokens; it previously fetched an unscoped graph and built its type filter
  from the wrong keys, so it could show entities from other maps (`ab575787`).
- The UI no longer loads its web fonts from Google Fonts — all seven families
  are now self-hosted, so a `CB_AIRGAP=true` install no longer makes an
  outbound font request (`e0223e8b`).
- `cb-agent uninstall` reported "Notified the server (agent record marked
  revoked)" on every run while the server never revoked anything. The agent
  closed the WebSocket immediately after writing its uninstall frame, and the
  server's close handshake completed before it had read that frame, so the
  notification was discarded — an uninstalled agent stayed `active` forever.
  The command now waits for the server's delivery acknowledgement, says so
  truthfully when it does not arrive (naming the agent you have to revoke by
  hand), and exits non-zero in that case (`cae1df31`).
- The `/link` stream now flushes a pending delivery acknowledgement before a
  status change ends the connection. The uninstall frame's own handling revokes
  the agent, so the connection was dropped before the acknowledgement for the
  frame it had just committed went out — reporting a completed uninstall as
  unconfirmed (`0290dc87`).
- An agent-initiated revoke now cancels the agent's in-flight discovery
  dispatches and pushes the status change to open fleet views, both of which the
  operator-initiated revoke already did (`2fa11b71`).
- A `/link` peer that disconnects during the hello exchange is now an ordinary
  disconnect rather than an unhandled ASGI exception with a full traceback per
  occurrence (`4f25e7cf`).
