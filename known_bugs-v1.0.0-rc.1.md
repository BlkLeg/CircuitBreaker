# Known Bugs — v1.0.0-rc.1

Found while installing rc.1 on Ubuntu Server 26.04 LTS (native one-line install).
Last updated 2026-08-19.

Item 1 is open. It now reproduces under browser automation (see below), but the cause is
not yet localised. Items 2, 3 and 4
are fixed. The two install-blocking defects at the bottom are fixed and carried in
rc.2.

---

## 1. Sticky navigation — selecting a page in the dash does nothing until a manual reload

**Severity:** high — the app looks broken on first use.
**Status (2026-08-19): REPRODUCED under browser automation, cause not yet localised. Still open.**

### Reproduction, 2026-08-19

The 2026-08-18 attempt below could not reproduce this. It can now, because the earlier attempt
was navigating away from a page that was never actually rendering: the API stub returned `[]`
for `/api/v1/maps`, which sends `useMapTabs` down a create-then-read-`.id` path that leaves
`/map` sitting on "Loading maps…" forever. Every navigation was therefore leaving a near-empty
page. With `maps` stubbed to a real row, `/map` renders its React Flow canvas, and navigating
away from *that* is what wedges.

**Recipe.** Firefox, production build under `vite preview`, CPU contention (Playwright at 8–10
workers on an 8-core host). Load `/`, wait for the topology to render, click the dock's
Hardware link.

**Observed, 3 times in roughly 180 attempts:** the URL advances to `/hardware`
(`expect(page).toHaveURL(/\/hardware$/)` passes), and `.page-content` still contains the
topology markup 10–15 seconds later. One route wrapper, `opacity: 1`, holding the *old* page.
Not "never mounted" and not "stuck at opacity 0" — the two branches the diagnostic below was
written for. It is the third shape: the outgoing route stays mounted and visible while the
incoming one never takes over.

**Ruled out with numbers: `AnimatePresence mode` is not the cause.** The leading hypothesis was
that `mode="wait"` holds the incoming route behind an exit animation that never resolves. Under
identical load, 48 runs each:

| mode | wedges / 48 |
|---|---|
| `wait` (current) | 2 |
| `sync` | 1 |

That is no difference, so `App.jsx` was left on `wait` — the value `8bb0ee25` shipped. Switching
it would have looked like a fix while changing nothing.

**Not localised.** Adding request/response/console listeners to the probe changed the timing
enough that 96 further attempts produced no wedge at all, so there is no network trace of one.
The remaining hypothesis, and where to look next, is the `React.lazy` + `Suspense` pair: during
a transition React keeps the previous UI on screen while the incoming route suspends, so a
chunk request that stalls produces exactly this symptom — old content, new URL, no error
boundary, fixed by a reload because the reload re-requests the chunk. Confirming that needs a
wedge captured with the network log attached.

**Why the suite does not assert on it.** At roughly 1-in-60 under artificial load, encoding this
as a test would add a flaky failure to every PR without adding information. `e2e/navigation.spec.ts`
keeps its deterministic assertions; this recipe is how to go looking for it deliberately.

### Earlier reproduction attempt, 2026-08-18 (superseded)

The Playwright harness this bug motivated now exists (`apps/frontend/e2e/`), and
`e2e/navigation.spec.ts` encodes exactly the diagnostic this report asked for: it
distinguishes "route never mounted" (fix is in AnimatePresence/Suspense) from "route mounted
but stuck at opacity 0" (fix is in the animation layer), so a recurrence names its own cause
instead of needing a live instance again.

**The bug did not reproduce** — for the reason given above: `/map` was stuck on its loading
placeholder, so nothing heavy was ever being navigated away from. What was tried:

- Chromium, Firefox and mobile-Chrome, against a real production build served by `vite preview`
  — not the dev server, since its on-demand transform hides lazy-chunk failures. (WebKit needs
  `libgtk-4-1`, unavailable on the authoring host; it runs in the CI container.)
- Six routes: `/hardware`, `/services`, `/ipam`, `/storage`, `/agents`, `/monitors`.
- Both navigation paths: `history.pushState` + `popstate`, and clicking the dock `NavLink`.
- Lazy-chunk latency injected at 300 ms, 1200 ms and 3000 ms, to mimic the first-visit chunk
  timing this report points at. `AnimatePresence mode="wait"` held nothing; the incoming route
  mounted, reached opacity 1, and the content changed every time.

In every case the route mounted, became visible, and rendered its own content.

**What is still untested, and is where I would look next.** The harness stubs the API at the
network layer and answers instantly. The three conditions it therefore does *not* recreate are
a real backend's response latency, the auth/redirect flow on a genuinely first visit, and a
cold browser cache on a slow link. If this is still seen on a running instance, capture the two
data points below — the harness assertions are written against exactly them.


Clicking a nav entry changes the URL but the page content does not respond. Only a
manual browser reload completes the navigation.

**This is a regression, not a new bug.** The same symptom was fixed once already in
`8bb0ee25` ("Fixed sticky loading issue requiring a hard reload to complete
navigation"). That commit's fix was to wrap the router in framer-motion:

```
apps/frontend/src/App.jsx:135-144
  <React.Suspense fallback={<LoadingScreen />}>
    <AnimatePresence mode="wait">
      <motion.div key={location.pathname} ... >
        <Routes location={location}>
```

That wrapper is still in place, so whatever is wedging navigation now is either a new
cause with the same symptom or something the wrapper stopped covering. Worth examining
first:

- `AnimatePresence mode="wait"` holds the incoming route until the outgoing exit
  animation completes. An exit that never resolves — interrupted transition, a page
  that suspends during exit, `prefers-reduced-motion` short-circuiting the transition —
  leaves the new route unmounted while the URL has already changed. That matches the
  symptom exactly.
- `<Routes location={location}>` renders against an explicitly passed location rather
  than the ambient one. If that `location` ever goes stale relative to the router, the
  URL and the rendered route diverge until a reload re-seeds both.
- The routes are `React.lazy` behind `Suspense`; a chunk that fails to load leaves the
  boundary pending rather than throwing to `ErrorBoundary`.

### Investigated and ruled out

- **The routing structure is not the regression.** `App.jsx`'s Suspense →
  AnimatePresence → motion.div → Routes block is byte-identical to what `8bb0ee25`
  shipped as the fix. Whatever changed, it was not this file.
- **Navigation is client-side and does fire.** The dock uses `NavLink`
  (`components/MacOSDOCK.jsx:173`), and the URL updates — which is why a reload lands
  on the right page. So the router state advances and the render does not follow.
- **Not reproducible in jsdom.** Two attempts, both pass: the pattern with instantly
  resolved lazy pages, and again with chunks deliberately resolved *after* the click,
  the way a real first visit behaves. framer-motion does not run real animation timing
  under jsdom, so `mode="wait"` never actually holds anything there. A jsdom test
  cannot catch this class of bug, which is a large part of why it regressed unnoticed.
- **No global reduced-motion kill switch.** The only `animation: none` rules are
  scoped inside `styles/monitors.css`; nothing globally disables transitions in a way
  that would stall an exit animation.

### What is needed to close it

Deliberately not fixed on a guess — a speculative change to the router is how this
comes back a third time. From a browser on a running instance, at the moment of a
click that does nothing:

1. Does the new page's markup exist in the DOM but render invisible? Inspect the
   `motion.div` under `.page-content` and read its computed `opacity`. Stuck at `0`
   means the enter animation never ran and the fix is in the animation layer. Absent
   entirely means the route never mounted and the fix is in AnimatePresence/Suspense.
2. Any console error, unresolved chunk request in the Network tab, or framer-motion
   warning at click time.

Those two answers separate "wedged animation" from "wedged route", which are different
fixes in different places.

**Do not** simply delete the animation wrapper without checking `8bb0ee25` — it was
added *as* the fix for this symptom, so removing it may reopen the original cause.

---

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
