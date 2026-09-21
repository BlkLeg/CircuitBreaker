# Installer journey — container route, first execution ever

**Date:** 2026-09-20 · **Branch:** `dev` · **Sandbox:** local dev machine, Fedora 44 host,
rootless podman 5.8.4, systemd host (not GitHub Actions — see "Sandbox deviations" below).

This is the record required by `scripts/ci/installer-journey.sh` and
`.github/workflows/installer-journey.yml`: does `podman --systemd=always` reliably run
`install.sh` end to end, or does the workflow need to fall back to a nested VM. Nothing
has ever executed `install.sh` before this. **Bugs found while proving that are listed
in full — they are the most valuable output of this task**, not a footnote.

## Headline result: the journey never printed "Journey complete" here — read this before the decision

Be precise about what was and was not achieved: **0 of the 25 total runs in this
sandbox (20 in-place + 5 fresh-container) reached the script's final "Journey complete"
line.** This is not a clean pass. It is reported honestly rather than rounded up.

What *was* established, with evidence: every failure has a specific, identified,
non-random cause, and none of those causes is podman/systemd/cgroup-delegation
flakiness. 7 of 7 fresh container boots this session reached a fully running
installation that answered both `/livez` and `/readyz` with 200 — the mechanism itself
never once failed to reach that state. The remaining, single blocking step
(`--selftest`) failed identically and deterministically every time, for a reason traced
to the specific reused build artifact, not to the container route (see below).

## Decision: adopt the container route for the mechanism; the journey is not yet green

The brief's rule ("adopt if 20/20 pass, fall back to a VM if it fails twice or more for
reasons not the installer's fault") does not cleanly cover this outcome, so this is a
judgment call, stated plainly: the container/systemd mechanism is adopted because it
showed zero flakiness across 7 fresh boots — a VM would not fix a bundle-artifact bug or
a phase-ledger design choice, so switching to it and re-measuring would reproduce the
identical result at far higher cost per run. But **the workflow should not be treated as
a green, mergeable required check until the `--selftest` finding below is resolved or
re-tested against a non-stale bundle** — right now every run of it, in CI or locally,
will fail at that exact step. That is the correct, honest state to hand off in.

## What "20 consecutive runs" actually measured, and why the number below is 0/20

The brief's Step 6 loop re-invokes `installer-journey.sh` against the **same** running
target 20 times, matching the literal script in the task brief. That is a real thing to
know (does `install.sh` survive being re-run in place — a documented, intentional use
case: `--unattended` is called out for "Proxmox LXC provisioning, cloud-init, Ansible,
CI"), but it is a **different measurement** than "does a fresh CI job flake." The actual
CI workflow gets a brand-new container every run. Both were measured separately; neither
was faked.

### Measurement A — the brief's literal loop, in place, 20 runs

```
pass=0 fail=20
```

Every one of the 20 runs failed identically, at the same assertion, for the same reason:

```
::error::installer never reported the phase: System dependencies
```

**Root cause, pinned to source:** `install.sh:1734` —

```bash
if [[ "$UPGRADE_MODE" == "true" ]]; then
  run_upgrade
  exit 0
fi

# Full Fresh Install Flow
cb_phase_begin deps "System dependencies"
```

Run 1 of the loop installed Circuit Breaker for real (the container had already been
installed once during earlier interactive debugging, so even the loop's first iteration
landed in upgrade mode — this is disclosed, not hidden: see "Sandbox deviations"). Every
run after the first finds an existing installation and takes `run_upgrade()`
(`deploy/setup.sh:1841`), which uses an intentionally **separate** five-phase ledger —
`cb_phase_begin upgrade_check "Pre-flight checks"`, `backup "Creating pre-upgrade
backup"`, `apply_bundle "Installing new version"`, `apply "Applying configuration and
migrations"`, `start "Restarting Circuit Breaker"` — never the fresh-install phase
names the journey script (and the task brief) assert on. This split is deliberate
(commit `960ddebe` "give the upgrade path five phases" plus the "no duplicate keys"
comment at `install.sh:105-116`), not an accident, so this is **not** something to
silently patch in `install.sh`. It does mean: the brief's literal 20-in-place-run
loop cannot pass runs 2-20 against any target the loop itself already installed, and
that is a property of the loop's methodology, not of container flakiness. It also means
a re-applied Ansible/cloud-init run of `install.sh --unattended` produces a completely
different phase transcript than a first run — worth knowing if anything downstream
parses that transcript.

One more data point from these runs, not otherwise investigated further (out of scope
for this task): in upgrade mode the backend service came up and then exited with
`status=3/NOTIMPLEMENTED` while `install.sh` itself still printed "Installation
complete!" and exited 0. `apps/backend/src/app/start.py` has a comment referencing this
same exit code ("a silent exit with code 3 / NOTIMPLEMENTED on all platforms. (#87 /
#81)"). Flagged for whoever owns the upgrade path; not chased down here.

### Measurement B — fresh container per run, 5 runs

Because Measurement A cannot speak to container-route reliability once every run shares
one already-installed target, a second loop tore the container down and recreated it
from a clean base image before every run (mirroring what the real CI workflow does per
job).

```
pass=0 fail=5
```

All 5 runs are failures by the journey script's exit code, but **all 5 reached the same
point** — every phase reported, `/livez` and `/readyz` both answered 200 — and failed
at the identical, final assertion:

```
=== Wait for /readyz ===
{"ready":true,"state":"ready","checks":{"db":"ok","redis":"ok"},"health":"ready","degraded":[],"writes_permitted":true}
=== Assert the installed binary contains its application ===
selftest FAILED — could not import ASGI module 'app.main': RuntimeError("CB_DB_URL must
start with 'postgresql://' (got: ''). SQLite is no longer supported as of v0.2.0. Set
CB_DB_URL=postgresql://breaker:YOUR_PASSWORD@postgres:5432/circuitbreaker")
::error::the installed binary failed its self-test
```

5 of 5 identical. This is the signal the container-vs-VM decision actually needs:
**zero flakiness in the mechanism** (podman `--systemd=always`, cgroup delegation,
service startup, health endpoints) across 7 total fresh-container boots this session.
The one remaining failure is deterministic and traces to the artifact, not the harness
— see below.

## Bug found and root-caused, not fixed (out of scope)

`circuit-breaker --selftest`, run bare (no environment, as the journey script and the
tool's own docstring both intend — *"runs in a container with no services, and on an
air-gapped host"*), fails in the **shipped frozen bundle**
(`dist/native/circuit-breaker_0.5.0_linux_amd64.tar.gz`) but **passes** when the
identical check is run from the current `dev`-branch source tree with the same empty
environment:

```
$ CB_DB_URL= unset; python3 apps/backend/src/app/start.py --selftest
selftest OK — 10 targets resolved
```

`apps/backend/src/app/startup/selftest.py` calls `os.environ.setdefault("CB_DB_URL",
"postgresql://selftest:dummy@localhost/selftest")` before importing `app.main`, which
is exactly what should make this environment-independent — and does, from source.
Against the frozen artifact it does not: `app/db/session.py`'s module-level
`os.environ.get("CB_DB_URL", settings.database_url)` sees `''`, not the default. This
bundle is tagged 0.5.0; the repo's `VERSION` file (per `CLAUDE.md`) is 0.4.2 — the
artifact does not correspond to a commit on this branch, which is consistent with a
stale/differently-built artifact rather than a live bug in current source. Per this
task's instructions, the bundle was reused rather than rebuilt (rebuilding is a
many-minute `build_native_release.py` run) and `install.sh`/backend source were not
touched. **This should be re-tested against a bundle built from current `dev`** before
concluding whether it is still live; I could not close that loop here without violating
"do not rebuild."

## Two defects in the workflow as drafted in the task brief — fixed before anything else could run

Both are in `.github/workflows/installer-journey.yml` as committed; neither needed an
`install.sh` change.

1. **`docker.io/library/ubuntu:22.04` / `debian:12` have no init system at all.**
   `podman run ... /sbin/init` fails before the container starts:
   `crun: executable file \`/sbin/init\` not found`. There is no way to `apt-get install
   systemd` afterward, because the container never starts without a valid entrypoint.
   100% reproducible, not a flake. Fixed by bootstrapping: boot the base image with a
   keep-alive command, install `systemd systemd-sysv` (which creates the `/sbin/init`
   symlink) plus `curl jq openssl ca-certificates`, `podman commit` that as a local
   image, then start the real systemd container from it.
2. **Missing `CAP_NET_RAW`/`CAP_NET_ADMIN`.** `deploy/setup.sh` runs `setcap
   cap_net_raw+ep` on the installed binary, and `circuitbreaker-backend.service`
   declares `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN`. A container whose
   capability bounding set lacks a capability a binary's file capabilities request
   cannot exec that binary — the kernel returns `EPERM` on `execve()` itself:
   `Failed to execute /opt/circuitbreaker/bin/circuit-breaker: Operation not permitted`,
   systemd status `203/EXEC`. Reproduced directly with `strace`: `execve(...) = -1 EPERM
   (Operation not permitted)`, confirmed as the file-capability/bounding-set interaction
   by removing `cap_net_raw` from the test binary and observing the same failure
   disappear. Fixed with `--cap-add=NET_ADMIN,NET_RAW` on the container run command.

Both fixes are in the committed workflow, with the reasoning inlined as comments at the
point of use.

## Sandbox deviations from the brief's exact commands (disclosed)

- **No passwordless `sudo`** in this sandbox, so all local testing used plain
  (rootless) `podman`, not `sudo podman`. Root-mode podman (as the actual CI workflow
  uses via `sudo`) has a larger default capability set than rootless podman; the
  `--cap-add=NET_ADMIN,NET_RAW` fix is defensive for both — `NET_ADMIN` is outside
  Docker/podman's default 14 capabilities either way.
- **SELinux is Enforcing on this host** (Fedora); GitHub Actions' `ubuntu-22.04`
  runners are not SELinux-enforcing. The brief's `-v "$PWD:/workspace:ro"` bind mount
  was denied here (`user_home_t` vs. `container_file_t`); local testing substituted
  `podman cp` of just the bundle, `install.sh`, and the journey script into the
  container instead of a bind mount. This is a sandbox-only substitution — the
  workflow file itself keeps the bind mount, which is correct for the actual runner.
- **glibc mismatch forced a base-image substitution for measurement, not for the
  workflow file.** `dist/native/circuit-breaker_0.5.0_linux_amd64.tar.gz` was built on
  this host's glibc 2.43 (Fedora 44); PyInstaller does not statically link glibc, so the
  frozen binary requires symbols (`GLIBC_ABI_GNU2_TLS`) that Ubuntu 22.04 (2.35) and
  even 24.04 (2.39) do not have — `/lib/x86_64-linux-gnu/libc.so.6: version
  'GLIBC_ABI_GNU2_TLS' not found`. Local measurement therefore used a Fedora-latest
  base image (matching glibc) instead of Ubuntu/Debian, purely to get past this and
  exercise the installer mechanics. **The actual CI workflow does not have this
  problem** — it builds the bundle fresh inside the `ubuntu-22.04` runner in the
  "Build the candidate bundle" step, so the binary and the target always share a glibc.
  This is flagged as a general packaging risk worth someone's attention regardless
  (a bundle built on a newer-glibc dev machine and shipped to users on an older-glibc
  distro would hit the same wall in production), but it is outside this task's scope.

## Commands run

```
bash -n scripts/ci/installer-journey.sh          # syntax OK
shellcheck scripts/ci/installer-journey.sh       # clean
.venv/bin/python -m pytest tests/build -q        # 743 passed
.venv/bin/python -m pytest tests/build/test_scheduled_workflows_pin_their_ref.py \
  tests/build/test_workflow_job_graph.py -q      # 4 passed
```
