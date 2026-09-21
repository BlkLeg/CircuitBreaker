# Making a release stop being the first execution of the install path

**Date:** 2026-09-21 · **Branch:** `dev` · **Sandbox:** Fedora 44 host, glibc 2.43,
rootless podman 5.8.4, Go 1.26.8.

Three failures were handed over for root-causing. Two of them turned out to be already
fixed on `dev` and unexecuted; the third is real and is fixed here. Chasing why the first
two could be simultaneously "fixed" and "failing" is what produced the rest of this
change, because the answer in both cases is the same: **the gate that would have caught
the defect ran for the first time during the release it was supposed to gate.**

Everything below was executed. Where something was not executed, it says so and why.

---

## 1. Release v0.4.3, run 35561309242 — service-container credentials

**Root cause, confirmed.** `artifact-smoke.yml`'s `deb-boot` job declared

```yaml
services:
  postgres:
    env:
      POSTGRES_PASSWORD: ${{ env.CB_DB_PASSWORD }}
```

and minted `CB_DB_PASSWORD` in its first step. GitHub creates service containers during
job setup, before any step runs, so the expression expanded to the empty string. From the
run's own log:

```
/usr/bin/docker create ... -e "POSTGRES_PASSWORD" ... postgres:15
 Error: Database is uninitialized and superuser password is not specified.
##[error]Failed to initialize container postgres:15
```

Both architectures failed identically, in ~20s, in `Initialize containers`.

**State on arrival.** Already fixed on `dev` by `f9aaf90d`, which moved Postgres out of
`services:` into a step that runs after minting, and added
`tests/build/test_service_containers_resolve_at_job_setup.py` as a static guard. Neither
had ever run against this workflow, because `artifact-smoke.yml` was reachable only from
`release.yml`, which triggers only on `v*` tags.

**What was actually wrong, therefore, was the graph.** A gate whose only caller is a tag
push cannot be wrong in a way anyone finds out about before a release. That is now a
build failure: `tests/build/test_release_paths_run_before_the_tag.py` fails if any
reusable workflow `release.yml` depends on has no caller triggered by a push or a pull
request, unless it carries an owned, dated row in
`specs/1.0.0/release-control/tag-only-gates.csv`.

`artifact-smoke.yml` is now called from four places, with one definition:

| Caller | Trigger | Architectures | Artifact |
|---|---|---|---|
| `dev-ci.yml` | push / PR to `dev` | amd64 | `dev-packages-amd64` |
| `ci.yml` | push / PR to `main` | amd64 + arm64 | `packages-<arch>` |
| `release.yml` | `v*` tag | amd64 + arm64 | `packages-<arch>` |
| `release-dry-run.yml` | manual, any ref | amd64 + arm64 | `packages-<arch>` |

## 2. Installer Journey, run 35545148847 — Rocky Linux and Redis

**Root cause, confirmed by reading the failing commit rather than the branch head.** That
run was `1b82e2fe`, and at that commit `deploy/scripts/wait-for-services.sh` read:

```bash
while ! redis-cli -h 127.0.0.1 -p 6379 -a "${CB_REDIS_PASSWORD}" ... PING ...
```

Rocky Linux 10 ships **Valkey**, not Redis, and provides only `valkey-cli`. The loop
therefore spun on a command that does not exist for the full 60s budget and killed the
backend with `FATAL: Redis did not accept authenticated connections within 60s` — while
Redis was healthy, the password was correct, and `cb doctor` reported the unit OK.

Already fixed on `dev` by `5f007f84` (runtime client resolution) and `d302be09` (the
`valkey` service account). Verified by executing the journey on Rocky Linux 10 locally
against a bundle built from this tree: it reaches "Journey complete".

**What the fix did not include, and now does.** The loop discarded the client's stderr
(`2>/dev/null`), so *every* failure — wrong password, connection refused, a client binary
that does not exist — produced the same sentence. That is what made this cost two
speculative fixes. `wait-for-services.sh` now keeps the client's last error and reports
it, refuses an empty `CB_REDIS_PASSWORD` outright instead of waiting sixty seconds to
discover it cannot work, and does the same for the pgbouncer probe.

**The regression test the brief asked for.** `scripts/ci/installer-journey.sh` now
asserts, on every distro:

1. `/etc/redis/redis.conf`'s rendered `requirepass` is byte-identical to
   `/etc/circuitbreaker/.env`'s `CB_REDIS_PASSWORD` — a render that dropped the
   substitution fails here;
2. a readiness client exists on this distro, and which one is recorded in the evidence;
3. the shipped `wait-for-services.sh`, at its installed path, run as `breaker` (the
   account the unit runs it as), exits 0.

That is the rendered config and the real readiness command, not a grep.

## 3. Composed Agent E2E, run 35561309099

Two failures, and they are different in kind.

### `test_agent_black_hole_partition_is_detected_and_spools` — product defect

```
AssertionError: the link went down during the partition, but no silence detector
(read deadline / stopped acknowledging data frames) was ever the reason. Errors
observed, oldest first: ['link: dial: dial tcp: lookup circuitbreaker on
127.0.0.11:53: server misbehaving']
```

Not a DNS problem and not compose networking: the DNS failure is a *consequence* of the
partition the test deliberately creates. The defect is that the agent throws away the
answer. `status.json` had one `last_error` slot, written both when an established
connection ends and when a dial fails — and a drop is immediately followed by a redial,
so within milliseconds `last_error` had stopped describing why the link went down.

The test had tried to work around this by sampling every 0.5s and keeping each distinct
value, with a comment claiming it "removes the race instead of narrowing it". It narrows
it, to whether a poll lands between the drop and the redial. On this run it did not.

**Fixed in the product, not the test.** `internal/status` gains
`last_link_failure`/`last_link_failure_at`, stamped only by
`Writer.SetLinkFailure` — which `cmd/cb-agent/daemon.go` calls only when the disconnect
follows an accepted session, consuming the `linked` flag so the following dial failures
cannot re-stamp it. Cleared by the next accepted `hello.ack`, like `last_error`.

This is an operator-facing improvement as much as a test fix: `cb-agent status` on a
disconnected agent used to say "dial tcp: lookup circuitbreaker … server misbehaving" no
matter what had actually happened.

Covered by `TestLinkFailureSurvivesTheReconnectThatFollowsIt` and
`TestADialFailureIsNotRecordedAsALinkFailure` in `internal/status`, both executed.

And observed end to end. Read out of the live agent's `status.json` from inside the
partition the composed E2E creates, while the test was running:

```
link_state:        disconnected
last_link_failure: link: server stopped acknowledging data frames
                   (5 frame(s) unacknowledged for 45s)
last_error:        link: dial: dial tcp: lookup circuitbreaker on 127.0.0.11:53:
                   no such host
```

Both slots, populated at the same instant, holding different things. `last_error` has
already been overwritten by the redial — it is the exact sentence the v0.4.3 run failed
on — while `last_link_failure` still carries the reason the link actually went down. That
is the whole fix, in one snapshot.

### `test_agent_full_lifecycle_enroll_through_revoke_and_reconnect` — not root-caused

```
TimeoutError: condition not met within 10s (last error: None)
```

**It passes here.** Executed on this host against a stack built from this tree, the test
reaches PASSED — which is evidence that the failure is environment- or timing-dependent,
and is *not* evidence that it is gone. A test that passes locally and failed on a tag is
exactly the situation where "probably flaky" gets written down, and this document is not
going to write it down.

The agent's socket was closed on time — the compose log shows `close 1008 (policy
violation)` 0.1s after the revoke — so the server acted. What did not arrive is the
`revoked` push on the admin `/agents/stream` viewer.

**This one is not fixed, and saying otherwise would be guessing.** Three candidates were
eliminated by reading the code: the nginx WebSocket locations carry
`proxy_read_timeout 3600s` (so nginx did not idle-close it); the presence stream pings
every 30s; the publisher and the subscriber use the same Redis channel
(`cb:agents:events`). What remains — the event was never published, the listener had
already died, or it arrived after 10s — cannot be told apart from the evidence the run
produced, because the harness destroys it: `_AgentStreamListener._run` ended on
`except Exception: return`, so a dead listener and a quiet server are the same silence.

What is fixed is that silence. The listener now records why its reader ended, how many
frames it saw, and every event it did receive; `assert_alive()` fails naming the stream
when the reader is gone, and the call site distinguishes "the viewer stopped listening"
from "the server revoked the agent and pushed nothing". The next occurrence says which.

No retry was added and the 10s budget is unchanged. It is not quarantined, because it is
not being dismissed — it is instrumented, and the next run is the evidence.

---

## Defects found by *running* the new gates

Every one of these was discovered by executing the extended installer journey. None was
reachable by reading, and none had a test.

### `uninstall.sh` did nothing on an `install.sh` host

Its native-cleanup section is guarded by
`[ -f /usr/local/bin/circuit-breaker ] || [ -f /etc/systemd/system/circuit-breaker.service ]`
— the **packaged** layout. `install.sh` creates `/opt/circuitbreaker`,
`/etc/circuitbreaker`, `/var/lib/circuitbreaker` and seven `circuitbreaker-*` units.
The two layouts differ by one hyphen, so the guard was false and the whole section was
skipped. Confirmed on a live install:

```
$ ls -d /usr/local/bin/circuit-breaker /etc/circuit-breaker /var/lib/circuit-breaker
ls: cannot access ...: No such file or directory   (all three)
```

`bash uninstall.sh` exited 0 with every service still running. It also refused to start
at all on such a host, because its first check is `command -v docker` — and a native
install does not need Docker.

Fixed: a native-layout cleanup section (units, slice, nginx site, `/opt`, the `cb` CLI,
`/run/circuitbreaker`, and — behind the existing consent prompt — config, data and the
`breaker` account); Docker demoted from a hard requirement to a per-layout one; and a
`sudo` shim for hosts that are already root and have no `sudo` (debian:12 and fedora
images both lack it, and `sudo rm -rf /opt/circuitbreaker` was an unguarded call).

`--purge` and `--keep-data` were added so the journey can run it: consent expressed on
the command line rather than at a prompt. There is deliberately no bare `--unattended`,
because the only questions this script asks are "may I delete your data?".

### `cb uninstall` dead-ended on every native install

It looks for `/usr/local/bin/uninstall-circuit-breaker`, then a sibling `uninstall.sh`,
then tells the operator to "run it from a checkout" — on a host installed from a tarball.
The bundle did not ship the uninstaller. It now does, `install.sh` installs it to the
path `cb uninstall` looks for first, and the journey asserts it is there and runs *that*
copy rather than one from the source tree.

### `install.sh --upgrade` was broken on every platform

Re-running the installer — the documented upgrade path — failed in three different ways
in sequence, each hidden behind the previous one:

1. **`cb_deps_present` required `redis-server`.** On Valkey hosts it could never pass, so
   every upgrade re-ran the entire dependency stage, including a fresh NATS download.
   Now accepts either binary, like every other resolution site in the file.
2. **`cp` over a running executable.** That dependency stage copies the NATS binary to
   `/usr/local/bin/nats-server` while `circuitbreaker-nats.service` is executing it;
   Linux answers `ETXTBSY` and `set -e` aborts the upgrade — after the pre-upgrade backup,
   after the new bundle is on disk. Now staged in the destination directory and renamed
   into place, which is both `ETXTBSY`-proof and atomic.
3. **The unit templates could not render at all.** `CB_PGBOUNCER_BIN`, `CB_DOCKER_BIN`,
   `CB_REDIS_SERVER_BIN`, `CB_REDIS_CLI_BIN` and `CB_REDIS_USER` were resolved only in
   `stage1_bootstrap`, which the upgrade path does not run; `stage2_dependencies`
   re-resolves them *below* its "dependencies already present — skipping" early return.
   So an upgrade worked only on a host where the dependency check had already failed:

   ```
   ✗ ERROR: Template .../circuitbreaker-pgbouncer.service needs variables the
     installer never set: CB_PGBOUNCER_BIN
   ```

   Resolution moved into `cb_resolve_service_binaries()`, called from `stage0_preflight`,
   which both paths run.

This is the most consequential finding in the change. Every self-hoster upgrades by
re-running `install.sh`, and nothing had ever done so.

### `.pkg.tar.zst` was claimed and never produced

ADR 0005's Tier 3 row read "`make build` produces all four and `build.yml` gates them".
It produces three. `create_arch_package()` never copied the `circuit-breaker.install`
hook that PKGBUILD's `install=` names into the work directory, so `makepkg` refused every
invocation — and the refusal was a `WARNING` that left the build exiting 0. No published
release carries one; v0.4.2's asset list is the record. Hook now copied; a failure after
a *usable* toolchain is found is fatal; a missing `makepkg` or `fakeroot` is an explicit
skip. The ADR row is corrected rather than the claim restored, because CI has no
`makepkg` — Arch users install through `install.sh`, which the journey's `archlinux` leg
exercises.

The same silent-success shape applied to the AppImage, which **is** a published asset.
Now fatal when `appimagetool` runs and fails.

### `--version` and the shipped `VERSION` could disagree

`dev-ci.yml` built `--version dev-<sha>` while the bundle copies the repo's `VERSION`
into `share/VERSION` and the binary answers from it. Nothing reconciled them, which is
why the artifact-smoke contract could not be pointed at a dev candidate: its parity
assertions compare exactly those two values. `sanitize_version()` now refuses the
mismatch outright, and both `dev-ci.yml` and `build.yml`'s dispatch default read
`VERSION`.

---

## Corrected claims

* **ADR 0005, Tier 3** — `.pkg.tar.zst` removed from the "in force" list, with the reason.
* **ADR 0005, Tier 2** — the row said `deb-boot` "asserts only that the binary prints a
  version", which stopped being true when the job was rewritten and was still not true in
  the other direction: the job had never completed a single run. Now recorded as
  **built, not yet passed**, with what it does and where it runs.
* **`docs/evidence/2026-09-20-installer-platform-coverage.md`** — stated that a Fedora-44
  build's glibc floor is 2.43 and that Rocky 10 (2.39) therefore could not run it. The
  floor is **GLIBC_2.38** (`tests/build/test_candidate_provenance.py` already said so),
  and the full journey was executed on Rocky 10 and AlmaLinux 10 against exactly such a
  bundle. Debian 12 (2.36) and Ubuntu 22.04 (2.35) genuinely cannot, and fail with the
  precise error that document predicted.
* **The platform matrix had no counterpart to install.sh's own claim.** `install.sh`
  refuses anything outside "Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux, Arch", and
  nothing bound that sentence to what CI runs. It is now declared in
  `specs/1.0.0/release-control/install-support-matrix.yaml`, AlmaLinux was added to the
  journey matrix, and RHEL is recorded as covered by its two rebuilds with the reason
  stated, because it cannot be installed without a paid subscription.

---

## What the pipeline looks like now

```
push / PR to dev ──► dev-ci: lint, tests, security, browser E2E,
                     build-native ─► artifact-smoke (amd64)
                     build-docker (mono image smoke)

push / PR to main ─► ci: lint, tests, security, browser E2E,
                     candidate-build (both arches) ─► candidate-artifact-smoke

manual, any ref ───► release-dry-run: version parity + release checklist +
                     channel report, build (both arches), artifact-smoke,
                     installer journey (six distros), both container images,
                     manifest assembly against a throwaway registry, image
                     boot, staged SHA256SUMS + asset-name discovery.
                     Publishes nothing; permissions are read-only.

v* tag ────────────► release: gate, build, artifact-smoke ─► image-merge
                     ─► publish ─► post-publish verification
```

`artifact-smoke` is one definition in all four. It now installs the candidate, proves the
binary contains its application, starts the unit, waits for `/livez` and `/readyz`, reads
`alembic_version` out of the database the service was pointed at, completes first-run
bootstrap, makes an authenticated request (and asserts the endpoint 401s without a token
*after* bootstrap — before it, the documented pre-bootstrap setup surface answers 200 by
design), then uninstalls and asserts the port is free.

---

## What the gate found on its first real run

Dev CI run 35615123469, the first execution of `artifact-smoke.yml` on a hosted
runner. Everything else in the pipeline was green — `Install .deb (amd64)`,
`Smoke the tarball (amd64)`, both Browser E2E shards, all four backend shards, the
Docker smoke, the coverage gate. `Boot the .deb (amd64)` failed at `Wait for /livez`,
and it found two things.

**The gate was failing the artifact for a condition the gate created.** The boot step
ran `install -d -m 0750 /etc/circuit-breaker`, and `install -d` does not merely create a
missing directory — it rewrites the mode of an existing one. `packaging/postinstall.sh`
deliberately sets that directory to `0755`, because the service runs as
`circuitbreaker` and has to traverse it. At `0750 root:root` it could not, and the unit
crash-looped:

```
circuit-breaker[3850]: PermissionError: [Errno 13] Permission denied:
  '/etc/circuit-breaker/config.yaml'
circuit-breaker[3850]: [PYI-3850:ERROR] Failed to execute script 'start'
systemd[1]: circuit-breaker.service: Main process exited, code=exited, status=1/FAILURE
```

That is worse than a gate not running: it would have sent someone looking for a
packaging defect that is not there. The step now asserts the packaged directory rather
than creating it — if the package stops making it traversable, *that* is what surfaces —
and writes its env file as `root:circuitbreaker 0640`, matching what postinstall gives
`config.toml`.

**And a real product defect underneath it.** `configure_runtime` probed its default
config path with a bare `Path(...).exists()`. That call is not total: it answers False
for a missing file and *raises* when the filesystem refuses to answer. The packaged
layout has no `config.yaml` at all — it uses `config.toml` — so the probe was asking
about a file that is expected to be absent, and any hardened `/etc/circuit-breaker`
turned that question into an unhandled traceback at line one of startup. An operator who
tightened permissions on their own config directory would get a crash-looping service
and a Python stack trace.

The probe now distinguishes three outcomes: present, definitively absent, and
undeterminable — and for the last one it refuses only when the operator actually asked
for that file (`--config` or `CB_CONFIG_PATH`), because continuing would run with
settings they believe are applied. For the built-in default it warns and continues.

The version split is why this survived: CPython 3.12, which the release binary is frozen
from, lets EACCES out of `Path.exists()`; CPython 3.14, which a developer machine is as
likely to run, returns False for it. The defect is real in the artifact and invisible on
a laptop. `apps/backend/tests/test_native_config_probe.py` therefore raises from
`Path.exists()` directly rather than building real permissions, so it asserts the shipped
interpreter's behaviour on any interpreter — and its last case exercises
`configure_runtime` rather than the helper, because every other case stays green if the
wiring is reverted. Mutation-tested: restoring the old expression fails that one test
with the production `PermissionError`.

**Separately, the Docs link check went red** on the same push, in the third-party
`lycheeverse/lychee-action`'s own setup step: `curl -sfLO` exited 22 fetching the pinned
lychee binary. Proven transient rather than assumed — the pinned asset is present in the
release (`gh release view lychee-v0.24.2`), the exact URL answers 200, and a re-run with
no code change passed in 8s.

It does expose a gap worth naming: that job's blocking pass documents itself as
`--offline` so that "a docs PR can be turned red by this repo and by nothing else — no
rate limit, no third-party outage, no flake". The link *checking* is offline; the action's
binary *download* is not, and it carries no retry. The guarantee in that comment is
therefore not the one the mechanism delivers. Left as a recorded gap rather than fixed in
the same change as a boot-gate fix.

## One thing this change cannot do from the repository: make the new gates blocking

Branch protection here is a ruleset, not the legacy `branches/main/protection` API, and
both rulesets list the same 21 required checks:

```
$ gh api repos/BlkLeg/CircuitBreaker/rulesets/13901513   # Main-Branch
$ gh api repos/BlkLeg/CircuitBreaker/rulesets/23638197   # Dev-Branch
required checks (21): Analyze (JavaScript / TypeScript), Analyze (Python),
Backend coverage gate, Backend tests (shard 1..4/4), Bandit (Python SAST),
Checkov (GitHub Actions / IaC), Fresh-install migrations, Frontend Dependency
Audit, Gitleaks (Secret Scanning), Go Vulnerability Scan, Lint, Python
Dependency Audit, Security Gate, Security Suppression Metadata, Semgrep (SAST),
Test, Trivy Config / IaC Scan, Trivy Filesystem Scan
```

The installed-artifact gate is not in that list, and neither is `Browser E2E gate`, which
predates this change. A check that runs and is not required is visible and advisory: it
goes red and the merge proceeds. That is the same "non-blocking job contradicting release
policy" this change otherwise removes, and it is a repository setting rather than
something in the tree, so it is recorded here rather than silently assumed.

The check names to add, once the jobs have passed once:

| Ruleset | Check |
|---|---|
| Dev-Branch | `Artifact Smoke / Install .deb (amd64)` |
| Dev-Branch | `Artifact Smoke / Smoke the tarball (amd64)` |
| Dev-Branch | `Artifact Smoke / Boot the .deb (amd64)` |
| Main-Branch | `Build Packages / Build (amd64)`, `Build Packages / Build (arm64)` |
| Main-Branch | `Artifact Smoke / Install .deb (amd64)`, `… (arm64)` |
| Main-Branch | `Artifact Smoke / Smoke the tarball (amd64)`, `… (arm64)` |
| Main-Branch | `Artifact Smoke / Boot the .deb (amd64)`, `… (arm64)` |

Adding them before the first green run would block every merge on a check that has never
passed, so the order matters: land this, watch one run, then require.

## Suites run

Recorded per CLAUDE.md's rule: name the suite that exercises the change, and run it.

| Suite | Command | Result |
|---|---|---|
| Pre-push gate | `EIO_BACKEND=posix make verify` | **green** — see the note below |
| Repo-policy / build | `pytest tests/build -q` | **816 passed** |
| Frontend unit (inside `make verify`) | `npm run test` | **227 files, 1999 tests passed** |
| Security gate | `scripts/security_scan.sh --gate` | **All scans passed (zero HIGH/CRIT)** |
| Agent unit — status | `go test ./internal/status/...` | **pass**, incl. 2 new |
| Agent unit — link | `go test ./internal/link/...` | **pass** |
| Agent build + vet | `go build ./... && go vet ./internal/status ./cmd/cb-agent` | **clean** |
| Shell lint | `shellcheck -S warning` on `install.sh`-adjacent scripts | **clean** |
| Ruff (gate scope) | `ruff check apps/backend/src/app`, plus the three new test modules | **clean** |
| Workflow parse + every `run:` block | YAML load + `bash -n` per step | **0 failures** |
| Composed agent E2E (targeted) | `make e2e-local E2E_ARGS='-k "black_hole_partition or full_lifecycle"'` | **2 passed, 14 deselected in 358.66s** — both of the tests that failed on the v0.4.3 tag |
| Installer journey | see the table below | |

### Installer journey, executed locally

Rootless podman, systemd containers, the real `install.sh` and the real
`uninstall.sh`, against a bundle built from this tree.

| Distro | Image | Result |
|---|---|---|
| Rocky Linux 10 | `rockylinux/rockylinux:10` | **Journey complete** — install, secrets, Redis readiness against the rendered config, migrations, bootstrap + authenticated request, layout/caps/ordering, restart, reboot-equivalent, installer re-run (secrets and admin account preserved), self-test, `cb uninstall --purge`, "uninstall clean" |
| AlmaLinux 10 | `almalinux:10` | **Journey complete** (after the `/etc/security/limits.conf` fix; it failed the install outright before) |
| Fedora 44 | `fedora:44` | **Journey complete** |
| Arch Linux | `archlinux:latest` | **Journey complete** (after switching the journey's JSON parsing from `python3`, which that image does not ship, to `jq`, which every bootstrap installs) |

Each of those is a full lifecycle, not an install smoke: fifteen sections ending in
"Journey complete".


**A note on `make verify`.** Its first run failed, and the failure was mine: Checkov's
`CKV_GHA_7` refuses `workflow_dispatch` inputs outright, and `release-dry-run.yml` had one
(a boolean for skipping the install matrix). Rather than add a suppression, the input was
removed — a rehearsal with a leg switched off is not the rehearsal that workflow exists to
be, and the ref is already chosen at dispatch time. The gate is green after that change.
Recorded because "the security gate went red on my change and I suppressed it" and "the
security gate went red on my change and I removed the cause" are different things, and
only the second one happened.

**Not executed here, and why:** `debian12` and `ubuntu2204`. Their glibc (2.36 and 2.35)
is below the GLIBC_2.38 floor of a bundle built on this Fedora 44 host, so the binary
cannot load at all — `Failed to load Python shared library … version 'GLIBC_2.38' not
found`, observed, not assumed. CI builds on ubuntu-22.04 (2.35) and is therefore below
every target's floor, which is where those two legs are verified.

**Not executed at all:** the GitHub Actions legs — `artifact-smoke`'s `deb-boot` on both
architectures, `release-dry-run` end to end, and the six-distro journey matrix. They need
GitHub-hosted runners (service containers, `ubuntu-22.04-arm`, a registry). Every `run:`
block in them was parsed and syntax-checked, and the shell constructs that are easy to get
wrong across a YAML block scalar (the nested heredoc in the authenticated-request step)
were executed standalone. That is not the same as running them, and this document does not
claim it is.
