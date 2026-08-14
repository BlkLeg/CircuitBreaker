# Known Bugs — v1.0.0-rc.1

Found while installing rc.1 on Ubuntu Server 26.04 LTS (native one-line install).
Last updated 2026-08-14.

Items 1–3 are open. The two install-blocking defects at the bottom are fixed and
carried in rc.2.

---

## 1. Sticky navigation — selecting a page in the dash does nothing until a manual reload

**Severity:** high — the app looks broken on first use.

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

**To reproduce:** load the dashboard, click any nav entry, observe the URL change with
no content change. Check the browser console for an unresolved chunk request or a
framer-motion warning at the moment of the click.

**Do not** simply delete the animation wrapper without checking `8bb0ee25` — it was
added *as* the fix for this symptom, so removing it may reopen the original cause.

---

## 2. Remove every suggestion to visit `IP:8088` — 443 is the port

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

## 3. Autoload the setup token during OOBE

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
