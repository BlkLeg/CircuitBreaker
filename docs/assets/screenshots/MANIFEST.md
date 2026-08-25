# Screenshot Manifest

> ## ⚠ GOV-02 IS NOT MET
>
> GOV-02's acceptance criterion is **"no environment secrets or personal data
> remain"** in the published assets. This review was performed and recorded; the
> redaction it called for **was not performed**. Fifteen of the sixteen assets
> are marked `no` or `partial` under **Anonymised** in the table below, and they
> are the files this repository publishes on its documentation site and in its
> README.
>
> **This document is a record of an unmet requirement, not evidence of a met
> one.** Do not mark GOV-02 as passed on the strength of this file.
>
> ### What is still legible in the published images
>
> | # | Data | Where |
> |---|---|---|
> | 1 | Maintainer identity — "Welcome, Shawn P" / "Welcome, Shawnji" | `01-concentric-rings`, `01-heart-diagram`, `01-hud-2`, `01-hud-maintenance`, `01-secure-logging`, `01-subnet`, `radial-bundled` — and "Shawnji" as the actor on all 61 audit rows in `01-secure-logging.webp` |
> | 2 | Approximate geolocation — `PHOENIX`, `PHOENIX, AZ` | Weather widget in seven captures; `New Map.webp` |
> | 3 | A real hostname — `circuitbreaker.local/map` in the browser URL bar | `01-hud-maintenance.webp` |
> | 4 | Real inventory and personal device names | Most captures — see the full list under *What the review found* |
> | 5 | Physical rack locations — `Office - Bottom Rack`, `Office - Rack #1`, `Office - Rack #2` | `01-hardware-page.webp` |
> | 6 | One real network's RFC1918 layout | Throughout |
>
> No credential of any kind is legible in any asset — no email address, API
> token, session cookie, setup token or password. Items 1–3 identify a person or
> a host; items 4–6 describe one homelab's topology.
>
> ### This is the repository owner's decision, not an agent's
>
> These images are the owner's own personal and homelab data in the owner's own
> public repository. **No agent should blur, recapture or delete them.** Exactly
> one of the following must be chosen and recorded before GOV-02 can move off
> "unmet":
>
> 1. **Blur in place.** Redact items 1–3 in the existing files. Cheapest, leaves
>    items 4–6 published, and the captures stay stale against the RC UI.
> 2. **Recapture against the RC UI with seeded demo data.** Removes all six items
>    at once and also closes the "Matches RC UI — not verified" column and part of
>    the GOV-03 backlog below. Most work, best outcome.
> 3. **Accept and record an exception.** The owner decides this data is fine to
>    publish. Requires a row in
>    `specs/1.0.0/release-control/exception-register.csv` with owner, reviewer,
>    rationale, compensating control and expiry, and the GOV-02 row in
>    `specs/1.0.0/release-control/requirement-ledger.csv` set to `excepted` —
>    **not** to `passed`.
>
> Until one of those is done and recorded, GOV-02 stays unmet.

---

GOV-02: every asset in this directory records its source version, capture date
and reviewer, and carries an explicit statement of what was found when it was
reviewed for environment and personal data. GOV-03: journeys that have no
current capture are listed here rather than left implicit.

**Reviewed by:** shawnji · **Review date:** 2026-08-19 · **Method:** each file
was opened and read visually at full resolution; the notes below record what was
legible, not what was assumed.

## Provenance

All sixteen assets were originally committed to a top-level `screenshots/`
directory between 2026-03-03 and 2026-03-11, removed, and restored into
`docs/assets/screenshots/` on 2026-08-10 by commit `f8bf4e7d`. Every restored
blob is byte-identical to its original, so the capture dates below are the
original commit dates, not the restore date. "Source version" is the value of
`VERSION` at the commit that first added the file.

`Matches RC UI` is **not verified** for every asset. Verifying it requires
rendering the 1.0.0-rc.4 UI and comparing it against a capture taken against
0.1.4–0.2.2, which was not done as part of this review. Treat every row as
"unknown, presumed stale" until someone re-captures.

| Asset | Source version | Captured | Anonymised | Matches RC UI |
|---|---|---|---|---|
| `01-Login.webp` | 0.2.2 | 2026-03-11 | yes | not verified |
| `01-cluster.webp` | 0.2.2 | 2026-03-11 | no — real inventory names, RFC1918 addresses | not verified |
| `01-concentric-rings.webp` | 0.2.2 | 2026-03-11 | no — maintainer name, city, real inventory names | not verified |
| `01-hardware-page.webp` | 0.2.2 | 2026-03-11 | no — real inventory names, addresses, rack locations | not verified |
| `01-heart-diagram.webp` | 0.2.2 | 2026-03-11 | no — maintainer name, city, real inventory names | not verified |
| `01-hud-2.webp` | 0.2.2 | 2026-03-11 | no — maintainer name, city, real inventory names | not verified |
| `01-hud-maintenance.webp` | 0.2.2 | 2026-03-11 | no — LAN hostname in the URL bar, maintainer name, city | not verified |
| `01-secure-logging.webp` | 0.2.2 | 2026-03-11 | partial — actor IPs are masked by the product; maintainer name and city are not | not verified |
| `01-subnet.webp` | 0.2.2 | 2026-03-11 | no — maintainer name, city, real inventory and network-zone names | not verified |
| `01-top-down.webp` | 0.2.2 | 2026-03-11 | no — real inventory names, RFC1918 addresses | not verified |
| `02-mobile.jpg` | 0.2.0 | 2026-03-08 | no — real inventory names, RFC1918 addresses | not verified |
| `New Map.webp` | 0.2.2 | 2026-03-11 | no — city and state, personal device names, RFC1918 addresses | not verified |
| `cb_night-full.webp` | 0.2.2 | 2026-03-11 | n/a — project logo artwork, not a UI capture | n/a |
| `new_mobile_layout.jpg` | 0.1.4 | 2026-03-03 | no — personal device names, RFC1918 addresses | not verified |
| `radial-bundled.webp` | 0.2.2 | 2026-03-11 | no — maintainer name, city, real inventory names | not verified |
| `speed-connection.webp` | 0.2.2 | 2026-03-11 | no — real inventory and personal device names | not verified |

## What the review found

Nothing in these assets is a credential. No email address, API token, session
cookie, setup token or password is legible in any of the sixteen, and the audit
log capture (`01-secure-logging.webp`) shows the product's own IP-masking doing
its job — the `IP` column is redacted in the image because the UI redacted it.

What *is* legible, and what GOV-02 requires be blurred or re-captured before
1.0.0 ships:

1. **Maintainer identity.** The header greets "Welcome, Shawn P" or "Welcome,
   Shawnji" in `01-concentric-rings`, `01-heart-diagram`, `01-hud-2`,
   `01-hud-maintenance`, `01-secure-logging`, `01-subnet` and `radial-bundled`.
   `01-secure-logging` additionally names "Shawnji" as the actor on all 61
   audit rows.
2. **Approximate geolocation.** The weather widget reads `PHOENIX` in seven
   captures and `PHOENIX, AZ` in `New Map.webp`. Combined with (1) this is
   personal data, not decoration.
3. **A real hostname.** `01-hud-maintenance.webp` includes the browser chrome
   with `circuitbreaker.local/map` in the URL bar. The name is mDNS-local and
   not routable, but it is a real host in a real network.
4. **Real inventory names.** `SunnyLabX`, `pve1`/`pve2`/`pve3`, `PBS-01`,
   `plex-main`, `GitLab`, `forgejo`, `cloudflared`, `Authentik-SSO`,
   `Authentik LXC`, `goingMerry`, `CT5555`, `TES-VM`, `TEST-VM2`, `testing-CT`,
   `ubuntu-golden-img2404`, `circuitbreaker-client`, `fedora-laptop`,
   `Opnsense Firewall`, `OptiPlex G8`, `OptiPlex 7080 SFF`, `Ubuntu Dev-VM`,
   `VMware Workstation`, and the zone labels `Main Lab Network`,
   `Monitoring Net` and `OppSec`.
5. **Physical locations.** `01-hardware-page.webp` lists
   `Office - Bottom Rack`, `Office - Rack #1` and `Office - Rack #2`.
6. **RFC1918 addressing.** `10.10.10.0/24`, `10.10.30.10`, `10.10.40.10` and
   `10.0.0.0/24` hosts throughout. Non-routable and the lowest-risk item here,
   but it is still one real network's real layout.

Items 1–3 are the ones that identify a person or a host and should be blurred or
re-captured. Items 4–6 describe one homelab's topology; re-capturing against a
seeded demo dataset removes all six at once and is the cheaper fix.

One accuracy note that is not a privacy issue: `cb_night-full.webp` is the
project's logo artwork, not a UI screenshot. `docs/screenshots.md` captions it
"Full UI — Night Mode" and `README.md` uses it as the banner. The banner use is
right; the caption is wrong.

## Required media not yet captured (GOV-03)

These journeys have no current capture. Each blocks GOV-03 until added:

- [ ] Install and OOBE (first-admin creation, setup token)
- [ ] Agent enrollment and fleet view
- [ ] Discovery and import review
- [ ] Agent-vantage monitor creation
- [ ] Backup and restore
- [ ] Mobile layout (current — the two existing mobile captures are 0.1.4/0.2.0)
- [ ] Empty and error states
- [ ] Accessibility states (focus, keyboard navigation)

Once Plan 3's Playwright harness is in place, most of these can be captured by
automation rather than by hand — `apps/frontend/e2e/visual.spec.ts` already renders several of
these surfaces deterministically, and a harness capture starts from seeded data,
which is the same change that fixes items 1–6 above.
