# Update Delivery and Install-Method Unity — Design

**Date:** 2026-08-25
**Status:** Proposed design, not yet implemented
**Branch context:** `dev` at `021780a0`; `VERSION` = `1.0.0-rc.4`
**Origin:** Field report — a fresh install reported `1.0.0-rc.2` and every Proxmox
connection failed with `No module named 'proxmoxer.backends'`. The immediate cause
(`install.sh` trusting the stale "Latest release" badge) is fixed separately. This design
addresses the reason the operator was never told to upgrade, and the reason they could not
have upgraded cleanly if they had been.

**Standing requirement, from product:** *no one is on an old build unless they deliberately
chose it or have not updated yet*, and *the experience is virtually identical regardless of
how the app was installed*.

## 1. Problem

### 1.1 The update check cannot detect an update

`app/core/update_check.py` has two independent defects, either fatal on its own.

```python
GITHUB_RELEASES_URL = ".../releases/latest"   # the stable-only badge

def _parse_version(v: str) -> tuple[int, ...]:
    clean = v.lstrip("v").split("-")[0]       # discards the prerelease entirely
```

`/releases/latest` resolves through GitHub's "Latest release" badge, which names the newest
**stable** release. Through the whole 1.0.0-rc window that is `v0.3.4`.

The parser is worse, because it fails even after the endpoint is corrected: `1.0.0-rc.2` and
`1.0.0-rc.4` both truncate to `(1, 0, 0)`, so `latest > current` is `False`. **An rc.2
instance can never be told that rc.4 exists.** This is the specific defect that stranded the
reporting operator.

### 1.2 Nothing would surface it anyway

The only consumer is `main.py:1387`:

```python
asyncio.create_task(log_update_notice(settings.app_version))
```

One `logger.info` line at boot. No endpoint, no UI, no CLI surface. Discovering an available
update requires grepping startup logs. The check also runs exactly once per process, so an
instance with six months of uptime reports what was true six months ago.

### 1.3 `cb update` is broken on both install types it claims to serve

- **binary** — `cb:462` refuses outright: `'cb update' is not supported for binary installs.`
- **docker** — `cb:57` pins `ghcr.io/blkleg/circuitbreaker:latest`, and `release_channel.py`
  never grants `latest` to a prerelease. GHCR's `:latest` was last written by **v0.3.4**, so
  `cb update` on an rc instance is a **downgrade**.

### 1.4 Seven install paths, four update mechanisms, no shared experience

| Install path | Mechanism | Identity source |
|---|---|---|
| `install.sh` native; Proxmox LXC | native bundle re-install | `install.conf` `CB_MODE=binary` |
| `install.sh --docker` | image pull + recreate | `CB_MODE=docker` |
| `docker-compose.yml` | `CB_TAG` + `compose up -d` | `CB_MODE=compose` |
| `.deb` / `.rpm` / `.apk` (nfpm) | system package manager | *(none today)* |
| Arch `PKGBUILD` | `pacman` / AUR | *(none today)* |
| `.AppImage` | replace file in place | `$APPIMAGE` |

Only three of the seven record how they were installed, so the app cannot tell an operator
what command to run.

### 1.5 Signatures are published and never verified

`release.yml:375-385` GPG-signs every artifact with `secrets.GPG_PRIVATE_KEY`, and each
release ships `circuit-breaker-release-key.asc`. `install.sh:532` verifies only:

```bash
sha256sum -c "${tarball_name}.sha256"
```

The digest is fetched from the same origin as the tarball, so it detects corruption, not a
malicious or compromised source. An update system that acts on unauthenticated metadata is
not shippable; this design will not add automated update actions on top of that gap.

## 2. Decisions

Product decided each of these explicitly.

| # | Decision |
|---|---|
| D1 | Fix all three vectors — detection, surface, and `cb update` — not detection alone. |
| D2 | **Channel follows what you run.** On a prerelease → offered the newest release of any kind. On a stable → offered only newer stables. Running an RC *is* the opt-in. No new channel setting. |
| D3 | Surface = admin-only dismissible banner + Settings About/Updates panel + API. |
| D4 | Re-check every 24h, cached, with an opt-out; never block a request on the network. |
| D5 | `cb update` resolves a concrete version and really upgrades, on every install type. `release_channel.py` also gains a `next` tag for prereleases. |
| D6 | `.deb`/`.rpm`/`.apk` are served by a **signed APT/YUM repository**, so updates arrive through `apt upgrade` and unattended-upgrades. |

Three corrections to an earlier draft of this design, adopted after review:

- **D7 — do not hand-roll version comparison.** `packaging==26.0` is already a declared
  dependency and orders this scheme correctly, including the case a naive implementation gets
  wrong: `1.0.0-rc.2 < 1.0.0-rc.4 < 1.0.0-rc.10 < 1.0.0`.
- **D8 — do not poll the GitHub API from every instance.** Publish a signed static manifest
  (the appcast model: Sparkle, Omaha, TUF). Unauthenticated GitHub API is 60 requests/hour per
  IP, the schema is not ours, and availability is not ours. A manifest we control can also
  **withdraw a bad release without cutting a new one**.
- **D9 — verify signatures before acting.** The manifest is signed with the existing release
  key; `install.sh` gains artifact signature verification.

## 3. The update manifest

### 3.1 Why it is the right primitive

Publishing an ordered, per-channel list moves the version-ordering decision to the one place
that can be tested properly — CI — and removes it from bash entirely. `cb` and `install.sh`
never parse a version; they ask *"is my version behind the head of my channel?"*, which is a
list-index comparison. The fragile part is deleted rather than tested into submission.

### 3.2 Location

Published by `pages.yml` to `https://circuitbreaker.shawnji.com/updates.json`, with
`updates.json.asc` beside it.

**Hard constraint, stated in `pages.yml` itself:** GitHub Pages publishes ONE artifact as the
ENTIRE site, so every path the site serves must be produced by that single workflow. The
manifest, the repositories in §7, and `gpg.key` are therefore all generated inside `pages.yml`,
never in `release.yml`. `pages.yml` already re-runs on `workflow_run` after Release completes,
so it can enumerate published releases and their assets via the API.

### 3.3 Schema

`schema` is versioned so a future client can refuse a shape it does not understand.

```json
{
  "schema": 1,
  "generated_at": "2026-08-25T22:00:00Z",
  "channels": {
    "stable":     ["0.3.4", "0.3.3", "0.3.1"],
    "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "1.0.0-rc.1", "0.3.4", "0.3.3"]
  },
  "releases": {
    "1.0.0-rc.4": {
      "tag": "v1.0.0-rc.4",
      "url": "https://github.com/BlkLeg/CircuitBreaker/releases/tag/v1.0.0-rc.4",
      "prerelease": true,
      "published_at": "2026-08-25T21:49:10Z",
      "artifacts": {
        "linux_amd64_tar": {
          "name": "circuit-breaker_1.0.0-rc.4_linux_amd64.tar.gz",
          "url": "...", "sha256": "...", "asc": "..."
        }
      }
    }
  },
  "withdrawn": []
}
```

Each channel list is **ordered newest-first** and already filtered by D2: `stable` holds only
stable releases; `prerelease` holds everything. A client's question is `index_of(current) > 0`.
`withdrawn` lets a known-bad release be suppressed without a new release.

**The channel lists are complete** — every published release appears, never a bounded window.
Only the package pools in §7 are bounded by size, because only they carry payloads. This is
what keeps `index_of` total for any released version, so the bash clients never need a
comparison fallback.

**A version absent from its channel list** — a local build, or a version predating the
manifest — is not comparable by index, and the client must not guess. It reports
`unknown_version` and offers nothing; explicit `cb update --version <v>` still works. The
backend reaches the same verdict independently through §4.1 ordering, which is why the two
implementations agree without sharing code.

### 3.4 Signing and verification

`pages.yml` clear-signs the manifest with `secrets.GPG_PRIVATE_KEY` (the key already used by
`release.yml`). Every consumer verifies against the pinned public key before trusting content:

- **backend** — ships the public key in the bundle; verifies with `python-gnupg` or by shelling
  to `gpg --verify`. Verification failure is treated as "no data", never as "no update".
- **`cb` / `install.sh`** — `gpg --verify updates.json.asc updates.json` against the keyring
  seeded from `circuit-breaker-release-key.asc`.

If `gpg` is unavailable the client degrades to *no update information* and says so. It never
silently proceeds on unverified data.

## 4. Backend

### 4.1 `app/core/version.py` — ordering

Thin wrapper over `packaging.version` (D7), so the project has one answer to "which is newer".

```python
from packaging.version import InvalidVersion, Version

def parse(raw: str) -> Version | None:
    """None for anything unparseable — an unknown version is never 'newer'."""
    try:
        return Version(str(raw).lstrip("vV"))
    except InvalidVersion:
        return None

def is_prerelease(raw: str) -> bool:
    """Unparseable counts as prerelease, matching release_channel.py's allowlist
    shape: a typo must never be treated as a stable release."""
    v = parse(raw)
    return True if v is None else v.is_prerelease
```

A parity test asserts this agrees with `scripts/release_channel.py:is_prerelease` across a
shared case list, so the build-time and run-time definitions cannot drift.

### 4.2 `app/core/install_method.py` — identity

Resolution order, first hit wins:

1. `CB_INSTALL_METHOD` env (explicit override; also how the container image declares itself)
2. `/etc/circuit-breaker/install.conf` → `CB_MODE` (`binary` / `docker` / `compose`)
3. `$APPIMAGE` set → `appimage`
4. dpkg/rpm/apk ownership of the running executable → `deb` / `rpm` / `apk` / `arch`
5. `/.dockerenv` present → `docker`
6. otherwise → `unknown`

Returns a method plus the `upgrade_command` an operator should run. `unknown` yields a
documentation link rather than a guessed command — never a command that might be wrong for
the host.

### 4.3 `app/core/update_check.py` — rewritten

Split so that the decision is pure and testable and only the fetch touches the network.

```python
def select_update(current: str, manifest: dict) -> str | None:
    """Newest release in the caller's channel, or None. No I/O."""
```

Channel selection implements D2: `prerelease` list if `is_prerelease(current)` else `stable`.
Entries in `withdrawn` are dropped. Returns the head only when it is strictly newer than
`current` under §4.1 ordering.

**Fetching** honors existing project conventions rather than inventing new ones:

- `settings.airgap` short-circuits before any socket is opened, mirroring
  `threat_feed.py:207`'s established precedent.
- A new `update_check: bool = True` setting (`CB_UPDATE_CHECK`) is the explicit opt-out (D4).
- Outbound requests route through `configured_egress_proxy_url()` from
  `core/url_validation.py`, as `backup/s3_client.py:78` does. An update check that bypassed
  the deployment's egress policy would be a hole.
- Conditional GET with `If-None-Match`/ETag, a `circuit-breaker/<version>` User-Agent, and a
  5s timeout. A 304 refreshes `checked_at` without re-parsing.

**Cache** is module-level and in-memory. Per hardening §8 the container runs `read_only: true`
with only `/data` writable, so a cache file is not an option and is not needed — the API
serves the cache and the scheduler refreshes it.

**Scheduler:** a task started at boot that checks, then sleeps `24h ± jitter`, and repeats.
Jitter avoids every instance in the world waking at the same moment. Registered for
cancellation at shutdown alongside the other worker tasks. Failures are logged at debug and
retained cache is kept; the check never affects startup or request latency.

### 4.4 API

`GET /api/v1/system/update`, admin-scoped via `require_role("admin")` (hardening §1 — no
unauthenticated path, no synthetic admin). Serves cache only; never awaits the network.

```json
{
  "current": "1.0.0-rc.2",
  "available": "1.0.0-rc.4",
  "update_available": true,
  "channel": "prerelease",
  "install_method": "binary",
  "upgrade_command": "sudo cb update",
  "release_url": "https://github.com/BlkLeg/CircuitBreaker/releases/tag/v1.0.0-rc.4",
  "enabled": true,
  "checked_at": "2026-08-25T21:00:00Z",
  "status": "ok"
}
```

`status` distinguishes states the UI must not conflate: `ok`, `disabled` (opt-out), `airgap`,
`unverified` (signature check failed), `unreachable`, `never_checked`, and `unknown_version`
(§3.3 — running a build the manifest does not list). **`upgrade_command` is
what delivers unity** — the server computes it from install method, so no client guesses.

## 5. Frontend

- `hooks/useUpdateStatus.js` — fetches the endpoint, refreshes hourly, admin only.
- `components/UpdateBanner.jsx` — mounted app-level in `App.jsx` beside `MasqueradeBanner`,
  following the existing `ServerLifecycleBanner` / `MasqueradeBanner` idiom. Shows installed
  vs available and the `upgrade_command`. Dismissal is stored per-version
  (`cb.updateDismissed.<version>`) so it returns when a *newer* release lands.
- `components/settings/UpdateSettings.jsx` — About/Updates section registered in
  `SettingsNav`, using `SettingSection` / `SettingField`. Permanent home for installed
  version, available version, install method, last-checked time, and the upgrade command.

The UI is identical on every install method; only `upgrade_command` differs. `status` values
render honestly — an airgapped install says checking is disabled, not "you are up to date".

## 6. `cb` — the single update entry point

`cb update` becomes the one command an operator learns, regardless of install path.

```
cb update
  ├─ fetch + gpg --verify updates.json          (fails closed)
  ├─ resolve target = head of my channel        (list index, no version parsing)
  ├─ already current? report and exit 0
  └─ dispatch by install method:
       binary   → download bundle, verify .asc + sha256,
                  install.sh --upgrade --version <target>
       docker   → docker pull …:<target>, recreate container
       compose  → set CB_TAG=<target> in env file, compose pull && up -d
       deb/rpm/ → apt-get / dnf / apk / pacman upgrade  (see §7)
         apk
       appimage → download + verify, replace file in place, prompt restart
       unknown  → print the documented manual procedure, exit non-zero
```

**Package-managed installs must never be updated by overwriting files.** Doing so corrupts the
package database. On those paths `cb update` delegates to the system package manager, which
after §7 is a plain `apt-get install --only-upgrade circuit-breaker`.

`docker-compose.yml:18` already reads `${CB_TAG:-latest}`, so the compose path needs no
compose-file rewrite — only an env value.

## 7. Signed APT and YUM repositories

This is what makes package installs *one and done*: after a one-time repo setup, updates
arrive through the operating system's own channel, including unattended-upgrades. It is the
model Docker, Grafana, Tailscale and Elastic use.

Generated in `pages.yml` (§3.2's single-artifact constraint), from assets of published
releases:

```
_site/
  gpg.key                     # ASCII-armored public release key
  updates.json{,.asc}
  apt/
    dists/{stable,next}/Release{,.gpg}  InRelease
    dists/{stable,next}/main/binary-{amd64,arm64}/Packages{,.gz}
    pool/main/c/circuit-breaker/*.deb
  yum/
    {stable,next}/{x86_64,aarch64}/repodata/…   # repomd.xml detached-signed
    {stable,next}/{x86_64,aarch64}/*.rpm
```

- Two suites, `stable` and `next`, are the packaging expression of D2: a prerelease user
  tracks `next`, a stable user tracks `stable`, and neither is silently moved.
- `apt-ftparchive` builds `Packages`/`Release`; `gpg --clearsign` produces `InRelease`.
  `createrepo_c` builds `repodata`; `repomd.xml` gets a detached signature.
- The job is **stateless**: it rebuilds both repos from release assets every run, because Pages
  replaces the whole site each publish. Bounded to the most recent N releases per channel to
  keep the artifact small; N is a constant in the workflow.
- If `GPG_PRIVATE_KEY` is absent the repo jobs are skipped with a warning, mirroring how
  `release.yml:380` already degrades. An unsigned repository is never published.

`install.sh` and the packages register the repo and key at install time so the path is live
without the operator reading documentation.

## 8. `install.sh`

- **Verify signatures** (D9): after the existing `sha256sum -c`, verify `<artifact>.asc`
  against the shipped public key. `--skip-checksum` continues to bypass both, and is the only
  way to bypass either.
- **Channel-aware `--upgrade`**: `cb_pick_release` currently returns the newest non-draft
  release, which is correct for a *fresh* install but wrong for an upgrade — it would move a
  `0.3.4` stable box onto an RC, contradicting D2. When an existing install is detected, the
  installed version selects the channel.

## 9. Release plumbing

- `scripts/release_channel.py` — `channel_tags()` returns `[version, "next"]` for a
  prerelease, `[version, "latest"]` for a stable. GOV-20 holds: an RC still never moves
  `latest`. `tests/build/test_release_channel.py` is updated for the new contract; its
  existing `"latest" not in channel_tags("1.0.0-rc.2")` assertion still passes.
- `pages.yml` — new jobs for the manifest, `gpg.key`, and the repositories; needs read access
  to release assets.
- Packaging — `nfpm.yaml`, `PKGBUILD`, and the AppImage build write the install-method marker
  §4.2 reads.

## 10. Cross-language parity

The channel rule exists in Python (backend) and bash+jq (`cb`, `install.sh`). It cannot be one
implementation, so it is one **specification**:

`tests/fixtures/update-channel-cases.json` holds `{current, manifest, expected}` cases —
including the rc.2 → rc.4 regression, the `0.3.4`-stable-stays-put case, `rc.10 > rc.4`, a
withdrawn release, and an unparseable current version. Both the Python suite and a bash suite
execute every case. Divergence fails CI instead of stranding a user.

## 11. Testing

| Area | Test |
|---|---|
| Ordering | `rc.2 < rc.4 < rc.10 < 1.0.0`; unparseable is never "newer" |
| Unlisted | A version absent from the manifest yields `unknown_version`, not an offer |
| Parity | `version.is_prerelease` ≡ `release_channel.is_prerelease` |
| Selection | Shared fixture, run by both Python and bash (§10) |
| Regression | An rc.2 instance is offered rc.4 — the reported bug, asserted directly |
| Channel | A `0.3.4` stable instance is offered nothing while only RCs are newer |
| Withdrawn | A withdrawn release is never offered |
| Signature | A tampered manifest yields `unverified`, never an update offer |
| Airgap | `settings.airgap` opens no socket; endpoint reports `airgap` |
| Opt-out | `CB_UPDATE_CHECK=false` opens no socket; endpoint reports `disabled` |
| Endpoint | 403 for non-admin; never blocks on network; serves cache |
| Frontend | Banner renders per status; dismissal is per-version; reappears on a newer release |
| `cb` | Dispatch per install method (mocked); package paths never touch files directly |
| Repos | `Packages`/`repomd.xml` generated and signed; verify against the published key |

## 12. Files touched

**New:** `app/core/version.py`, `app/core/install_method.py`, `api/system.py`,
`hooks/useUpdateStatus.js`, `components/UpdateBanner.jsx`,
`components/settings/UpdateSettings.jsx`, `tests/fixtures/update-channel-cases.json`, plus
test modules.

**Modified:** `app/core/update_check.py` (rewritten), `app/core/config.py`, `main.py`,
`App.jsx`, `SettingsNav.jsx`, `cb`, `install.sh`, `scripts/release_channel.py`,
`.github/workflows/pages.yml`, `nfpm.yaml`, `PKGBUILD`, `scripts/build_native_release.py`,
`tests/build/test_release_channel.py`, `docs/installation/configuration.md`.

## 13. Order of work

Each stage is independently shippable and leaves the product better than it found it.

1. **Detection correctness** — `version.py`, `select_update`, parity fixture. Closes §1.1.
2. **Surface** — cache, scheduler, airgap/egress/opt-out, endpoint, banner, Settings panel.
   Closes §1.2; after this no one is silently stranded.
3. **Manifest** — `pages.yml` publishes signed `updates.json`; backend prefers it.
4. **`cb update` unity** — install-method identity, markers, dispatch. Closes §1.3/§1.4.
5. **Repositories + signature verification** — apt/yum on Pages, `install.sh` `.asc` checks.
   Closes §1.5 and delivers D6.

## 14. Out of scope, and what cannot be verified here

- **Automatic self-update.** Notify-and-one-command is the norm for server software; silent
  self-mutation of a running server is not proposed.
- **Delta updates.** AppImage `zsync` is the standard there and is deliberately deferred;
  full-file replacement is correct, only larger.
- **Phased rollout / TUF key rotation.** Real practice at larger scale, unjustified here.
- **`backup/verify.py:_version_tuple`** deliberately sorts `1.0.0-rc.3` as `1.0.0` for
  snapshot compatibility. That is documented intent for a different question and is left alone.
- **Verification honesty:** package-manager and AppImage paths can be unit-tested for dispatch
  logic here, but confirming a real `apt upgrade` against the published repository requires a
  container test or a pass on a target host. The plan must state which rows of §11 were
  actually executed and which were not. No row may be reported as passing on the strength of
  its unit test alone.
