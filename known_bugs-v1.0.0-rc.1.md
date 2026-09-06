# Known Bugs — v1.0.0-rc.1

Found while installing rc.1 on Ubuntu Server 26.04 LTS (native one-line install).
Last updated 2026-09-06.

Every item is fixed. Item 1 — the sticky-navigation wedge that was open from rc.1 —
was localised and fixed on 2026-09-06; the record below keeps the ruled-out
hypotheses, because two of them had been the leading explanation for eight months
and both were wrong.


---

## 1. Sticky navigation — selecting a page in the dash does nothing until a manual reload — FIXED

**Severity:** high — the app looks broken on first use.
**Status (2026-09-06): FIXED.** Root cause found, one-line fix, guarded by a static
check and a throttled e2e test that both fail without it.

### The cause

**react-router v7 wraps every location update in `React.startTransition`.**
`BrowserRouter` does this by default (`useTransitions` is opt-out, see
`react-router/dist/.../BrowserRouter`), while `history.pushState` has already
changed the URL synchronously. A transition is interruptible and non-urgent, so
React is free to render it late, discard the render, or never commit it at all.
When that happens the address bar and the rendered route diverge permanently:
no Suspense fallback, no ErrorBoundary, no console error, and no recovery,
because a transition lane that never commits is never retried. A reload is the
only way out — it re-seeds both from the address bar, which is exactly the
workaround the original report describes.

The trigger is an expensive outgoing tree. **Every wedge in every run recorded
here was a navigation away from `/map`**, whose topology canvas is the heaviest
render in the app. That is also why the 2026-08-18 attempt could not reproduce
it: `/map` was sitting on "Loading maps…", so nothing expensive was ever being
navigated away from.

### The fix

`apps/frontend/src/App.jsx`:

```jsx
<BrowserRouter useTransitions={false}>
```

The location then commits immediately, and a route whose chunk is still loading
shows the `LoadingScreen` fallback instead of silently holding the previous
page. A visible loading state is the behaviour this app wants; a stale page that
lies about where you are is not.

### Measurements

Dock-click navigations, Chromium, 6x CPU throttle, API stubbed
(`e2e/fixtures/api.ts`), one variable changed at a time:

| variant | wedges |
|---|---|
| as shipped | 16/40 |
| `AnimatePresence mode="sync"` | 15/40 |
| **no `AnimatePresence` at all** | 16/40 |
| **journey routes imported eagerly, no `React.lazy`** | 16/40 |
| **`useTransitions={false}`** | **0/80** |

Against a real backend (native `make dev`, real SSE/WebSocket traffic, logged in
as a real user), same journey: **15/40 wedges before, 0/40 after.** On the real
backend it wedged on the *first* navigation away from `/map`, every time —
this was never rare in the conditions users actually hit, only in the stubbed
harness that answers instantly.

### Ruled out, with numbers — read this before touching either

- **The animation wrapper is not involved.** Removing `AnimatePresence`
  outright leaves the rate at 16/40. `mode="wait"` vs `"sync"` is 16/40 vs
  15/40. `8bb0ee25` added this wrapper *as* the fix for this symptom and it was
  never load bearing for it; the symptom went away then for some other reason
  and came back. The wrapper is a page transition and may be changed on visual
  grounds.
- **Lazy chunks are not involved.** Importing the journey's routes eagerly
  instead of through `React.lazy` leaves the rate at 16/40, and no wedge in any
  run had a pending chunk fetch (`wedges_with_pending_chunk: 0` across 60
  navigations of `nav-wedge.spec.ts`). H1's "stalled chunk" branch is dead.
- **It is not a blocked main thread.** While wedged, a rAF loop ran 301 frames
  in 5 seconds — a completely idle thread at 60fps — and sync-priority updates
  still committed normally (the command palette opens on Ctrl-K while the page
  behind it is stale). Only the transition lane is stuck.
- **jsdom cannot reproduce it**, and that is not fixable. It needs a contended
  CPU to interrupt the transition. This is why 1236 passing unit tests said
  nothing for eight months.

### Why the old diagnostic misread it

`nav-wedge.spec.ts` classified these wedges as `router-location-never-updated`
on the basis that no nav entry existed for the target path. Two separate faults
fed that:

- `useNavigationMountSignal` closed a navigation from a `[location.pathname]`
  effect dependency rather than from a mount. With `mode="wait"` the outgoing
  subtree stays mounted through the exit animation, so the *outgoing* instance
  re-fired that effect when the location changed and stamped `pending: false`
  on a route that had not rendered — a wedge reading back as a completed
  navigation. Fixed: the effect is now mount-only and reads a path captured at
  mount. `src/__tests__/navigation-timing.test.jsx` has the case that fails
  without it, and its harness now mirrors App.jsx's keyed subtree, whose absence
  is what let the fault hide.
- The branch names themselves assume the wedge is downstream of the router.
  It is not; it is the router's own update.

### Safeguards

- `tests/build/test_router_transitions_contract.py` — fails the build if any
  router in `apps/frontend/src` is rendered without `useTransitions={false}`.
  The prop is one token, invisible in review, and exactly what a router upgrade
  or a copy-pasted `<BrowserRouter>` drops.
- `apps/frontend/e2e/navigation.spec.ts`, "navigating away from the topology
  does not wedge under CPU load" — 12 dock-click navigations alternating off a
  rendered `/map` under 6x CPU throttle. Verified 5/5 pass with the fix and 5/5
  fail without it. At a ~40% per-navigation rate it misses a full regression
  with probability ~0.2%.
- `nav-wedge.spec.ts` stays as the opt-in rate-measuring diagnostic.

The three conditions the old suite never combined, and which any future
navigation test needs: navigate **away from a rendered `/map`**, through a real
`<NavLink>` (not `history.pushState` + synthetic `popstate`, which bypasses the
`startTransition` path entirely), under **CPU contention**.


## 2. Remove every suggestion to visit `IP:8088` — 443 is the port — FIXED

**Status:** fixed. The two `http://…:8088/ (Limited - no account creation)` lines are
gone from `stage10_final_output`, along with the now-redundant `(PRIMARY …)` label on
the HTTPS URL — with no competing URL beside it there is nothing to be primary over.
The `--no-tls` branch still prints its `CB_PORT` URL, because that mode really does
serve the app there, and every Proxmox 8088 reference is untouched.

**Severity:** medium — misleads the operator during onboarding, which is the worst
possible moment.

On a native install, port 8088 does nothing but `return 301 https://$host$request_uri`
(`deploy/nginx/circuitbreaker-tls.conf:18`). Presenting it as an access URL implies it
is a usable entry point. It is not. SSH to the install machine and visit the IP over
HTTPS on 443 — that is enough to complete onboarding.

**The offender is the installer's own closing screen**, `stage10_final_output` in
`deploy/setup.sh:1256` and `:1258`:

```
⚠  http://<fqdn>:8088/   (Limited - no account creation)
⚠  http://<ip>:8088/     (Limited - no account creation)
```

Those two lines should go. The HTTPS URL directly above them is the whole answer.

**Two things to preserve while removing it:**

- `--no-tls` installs genuinely serve the app on `CB_PORT` over plain HTTP, with no
  443 listener at all. The `NO_TLS == true` branch of the same function is correct and
  must keep printing its `http://…:8088/` URL.
- **Proxmox LXC serves HTTPS on 8088**, not 443 — that deployment patches nginx
  specifically to do so. Every 8088 reference in `docs/installation/proxmox-lxc.md`
  and the Proxmox rows of `docs/installation/index.md` is accurate and must stay.

The prose docs are already correct — `docs/installation/quick-install.md:23` and
`docs/installation/index.md:28` both describe 8088 as redirect-only. This is an
installer-output fix, not a docs sweep.

---

## 3. Point the user at the setup token during OOBE — FIXED

**Status:** fixed, by pointing rather than autoloading — the token itself still never
leaves the server, so SEC-09 stands and its evidence is not invalidated. The bootstrap
status response now carries `setup_token_path` (the resolved path, never the token),
and the wizard renders a copy-pasteable `sudo cat <path>` in place of "find this in
your server data directory". The path has to come from the server because it differs
per deployment — `/var/lib/circuitbreaker` natively, `/data` in the container — so a
hardcoded string would be wrong for half of all installs. It is returned only while
bootstrap is actually pending, and when the operator set `CB_SETUP_TOKEN` the wizard
says so instead, since no file exists in that case.

Original request and the constraint that shaped it, kept for the record:

**Severity:** medium (usability) — **but it collides with an evidenced security
control, so it needs a design decision before anyone implements it.**

**The ask:** the user should not have to leave the app to finish setup. Today OOBE
stops and demands a token that only exists in a `0600` file on the server
(`$CB_DATA_DIR/bootstrap-setup-token`, written by `ensure_bootstrap_token` in
`apps/backend/src/app/services/auth_service.py:129-173`), so onboarding means
switching to a terminal mid-wizard.

**The collision:** that token *is* the control that stops the first-run window from
being an open admin session. `auth_service.py:132` states it plainly — "Public APIs
never return the plaintext token" — and requiring host access to read it is what
proves the person completing OOBE owns the box. Serving it to any pre-auth browser
reopens exactly the race it was built to close.

This is not a loose convention. It is **SEC-09** — "Initial setup cannot expose an
admin-equivalent race window" — the one security row in
`specs/1.0.0/release-control/requirement-ledger.csv` currently at `status: passed`
with `invalidation_state: current`, evidenced at immutable commit `49b20ed1`. Handing
the plaintext token to an unauthenticated browser invalidates that row and forces a
re-evidence cycle before release.

**Options that reduce the friction without touching the trust boundary** (each keeps
the token behind host access, which the operator already has — they just SSH'd in):

- Print the token on the installer's closing screen, next to the access URL. Same
  trust boundary: the operator is already at a root shell on the host at that moment.
- Add `cb setup-token` to the CLI, so retrieval is one command instead of knowing the
  file path. Already root-gated like the rest of `cb`.
- Have OOBE show the exact command to run (`sudo cat /var/lib/circuitbreaker/bootstrap-setup-token`)
  rather than a bare "enter your setup token" prompt, so the trip to the terminal is
  one copy-paste instead of a docs hunt.

True in-browser autofill only works if the token stops being a secret from the
browser, which is the thing SEC-09 forbids. If that trade is acceptable, it is a
deliberate posture change that needs the ledger row reopened — not a UI tweak.

---

## 4. Add Agent returned a 500 — the backend could not read its own TLS cert — FIXED

**Status:** fixed. `GET /api/v1/agents/install-command` raised
`ValueError: Cannot obtain TLS pin for self-signed certificate: neither live nginx
cert nor database cert available` on every native install, so the agent — the whole
distributed half of the product — could not be installed at all.

Nothing was missing. `_live_nginx_cert_pem()` reads
`$CB_DATA_DIR/tls/fullchain.pem`, which is exactly where `deploy/setup.sh` writes the
self-signed cert. The problem was that it could not open it: the installer left that
tree `root:$nginx_group` with the directory at `750` and the file at `640`, and
`circuitbreaker-backend.service` runs as `breaker`, which is in neither. The
resulting `PermissionError` was caught by a blanket `except OSError: return None`,
so an unreadable certificate was indistinguishable from an absent one and the error
message named the wrong problem.

It only ever worked in the container because `entrypoint-mono.sh:160` chowns both TLS
files to `breaker:breaker` — the same user the backend runs as. Every unit test
mocked `_live_nginx_cert_pem`, so nothing exercised the real read against a real
file on the real layout.

Four parts to the fix:

- **The permissions.** `fullchain.pem` is now `644` and the directory `751`. That
  file is the server's *public* certificate — every TLS client is handed a copy
  during the handshake — so there was never a reason to restrict it. `privkey.pem`
  stays `640 root:$nginx_group`, and `o+x` without `o+r` on the directory lets the
  backend open a known path without being able to enumerate the directory. The
  block runs on upgrades too, so existing installs self-heal.
- **Unreadable is no longer confused with absent.** `FileNotFoundError` still falls
  back to the database row; `PermissionError` now raises and names the path, the
  reason and the `chmod` that fixes it. Falling back on a permission error would
  have been worse than failing: a `Certificate` row need not be what nginx serves,
  and pinning it would hand agents a pin that fails their TLS handshake, surfacing
  far from here as an unexplained enrollment failure.
- **The endpoint answers 503, not 500.** A missing or unreadable certificate is an
  operator-fixable deployment problem, not a bug in the request.
- **The UI shows it.** `handleShowInstallCommand` swallowed the response entirely
  and toasted "Could not generate an install command", which is why the only real
  explanation was in `journalctl`. It now prefers the server's detail and keeps the
  generic message as the fallback.

`cb doctor` gained a matching check — the backend reading the cert as its own service
user — because this failure mode leaves every other check green.

---

## Fixed in rc.2

Both were install-blocking on a clean native install and are already committed.

- **Backend refused to parse its own generated config.** pydantic-settings JSON-decodes
  list-typed fields in the env source before any validator runs, so the
  `CB_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128` line written by `deploy/setup.sh`
  raised `SettingsError` at import and killed the process. `cors_origins` carried the
  same latent crash. Fixed with `NoDecode` on both fields (`9a6aed79`).
- **No egress configuration could start the backend.** `validate_egress_proxy()`
  returned the validated proxy URL on success, which the caller read as a truthy error
  — so a correctly configured `CB_EGRESS_PROXY_URL` failed startup with the URL itself
  as the message, while an empty one failed the strict-production gate. Every
  deployment template shipped the empty case. Fixed, plus `CB_ALLOW_DIRECT_EGRESS` to
  let a proxy-less host satisfy the gate without waiving the Redis, NATS, rate-limit
  and secret gates (`d8af67d5`).

Also landed alongside them: the installer and `cb doctor` now run their diagnostics
automatically on failure instead of printing a list of commands to go run (`0e32938d`).
