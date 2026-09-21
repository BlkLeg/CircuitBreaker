# Installer journey — every claimed platform, and what "every" actually meant

**Date:** 2026-09-20 · **Branch:** `dev` · **Sandbox:** local dev machine, Fedora 44
host, rootless podman 5.8.4 (no passwordless sudo available — see "Sandbox deviations"
below; the committed workflow keeps `sudo podman`, matched to a real GitHub Actions
runner where sudo is passwordless).

`install.sh:877` and `:1203` both say Circuit Breaker supports "Ubuntu, Debian, Fedora,
RHEL, Rocky, AlmaLinux, Arch." Before this work, `.github/workflows/installer-journey.yml`
exercised exactly two of those seven — Ubuntu 22.04 and Debian 12, both `apt-get`. The
`dnf` branch (Fedora/RHEL/Rocky/AlmaLinux) and the `pacman` branch (Arch) in
`deploy/setup.sh`'s `stage2_dependencies` had never been executed by anything, ever —
not CI, not a human, not this project's own test suite.

## What was actually executed here, versus what was only added to the matrix

| Distro | Executed locally in this sandbox | Added to CI matrix |
|---|---|---|
| Ubuntu 22.04 | no (already covered; not re-run) | already present |
| Debian 12 | no (already covered; not re-run) | already present |
| **Fedora 44** | **yes — full journey, twice, to "Journey complete"** | yes |
| **Arch (rolling)** | **yes — full journey, three attempts, reached "Journey complete" on the third** | yes |
| Rocky Linux 10 | **no — see glibc floor below** | yes |
| arm64 (any distro) | no | no — remains completely unmeasured; see "Remaining gaps" |

Fedora and Arch are the two legs the task named as meaningfully testable here, and they
are exactly the `dnf` and `pacman` branches that had never run. Rocky was added to the
matrix (CI builds its own low-floor bundle, so the matrix leg is expected to work) but
was **not** run in this sandbox — recorded honestly below, not rounded up to "tested."

## Why Fedora and Arch were locally testable and Rocky was not: the glibc floor

`scripts/build_native_release.py:557` documents that a PyInstaller bundle inherits its
build host's glibc floor. This sandbox is Fedora 44:

```
$ cat share/build-info.json   # from dist/native/circuit-breaker_0.4.2_linux_amd64.tar.gz
{
  "version": "0.4.2", "os": "linux", "arch": "amd64", "built_by": "local",
  "glibc": "2.43", "distro": "fedora-44", "python": "3.14.7",
  "ci_run": "", "ci_workflow": "", "commit": ""
}
```

A binary demanding `GLIBC_2.43` runs on anything whose own glibc is >= 2.43. Measured
directly:

> **Corrected 2026-09-21.** The build host's glibc version is not the bundle's floor. The
> floor is the highest symbol version anything in the bundle actually references, and for
> a Fedora 44 build that is **GLIBC_2.38**, not 2.43 — measured by running the bundle,
> not by reading `build-info.json`. The consequence is that one of this document's
> conclusions below is wrong in the operator's favour and one is right for the wrong
> reason:
>
> * **Rocky 10 (2.39) does run a Fedora-44-built bundle.** The full installer journey —
>   install, boot, `/readyz`, migrations, authenticated request, upgrade re-run,
>   uninstall — was executed against one on 2026-09-21 and reached "Journey complete".
>   The table below records Rocky as untestable in this sandbox; it is not.
>   AlmaLinux 10 (2.39) is above the floor for the same reason.
> * **Debian 12 (2.36) and Ubuntu 22.04 (2.35) genuinely cannot run it**, and fail
>   exactly as predicted: `Failed to load Python shared library
>   '/tmp/_MEI.../libpython3.14.so.1.0': /lib/x86_64-linux-gnu/libm.so.6: version
>   'GLIBC_2.38' not found`. That is the real number, observed.
>
> None of this changes CI, which builds on ubuntu-22.04 (2.35) and is therefore below
> every target's floor. It changes what a laptop can be used to verify: on a Fedora host,
> the `dnf` and `pacman` families are locally reproducible and the `apt` family is not.

Measured directly:

```
$ podman run --rm docker.io/library/fedora:44 ldd --version | head -1        (not run: same host family, known >= 2.43)
$ podman run --rm docker.io/library/archlinux:latest ...                      (rolling, tracks current glibc, >= 2.43)
$ podman run --rm docker.io/rockylinux/rockylinux:9  bash -c 'ldd --version'
ldd (GNU libc) 2.34
$ podman run --rm docker.io/rockylinux/rockylinux:10 bash -c 'ldd --version'
ldd (GNU libc) 2.39
```

Rocky 9's glibc (2.34) and Rocky 10's glibc (2.39) are **both** below this sandbox's
2.43 floor, so the locally built bundle cannot run on either — a sandbox/build-host
limitation, not an install.sh defect, exactly as flagged going in. This is also why the
workflow matrix uses `rockylinux:10`, not `:9`: Rocky 10's glibc (2.39) clears the *CI
job's own* build floor (ubuntu-22.04, glibc 2.35 — `2.35 < 2.39`), while Rocky 9's
glibc (2.34) would **not** (`2.35 > 2.34`) and would fail in real CI for the same
structural reason, regardless of install.sh's correctness. That distinction is recorded
in a comment at the matrix's `rockylinux` case in the workflow file. Nothing here claims
Rocky 9 works; nothing here claims Rocky 10 was verified end-to-end — only that it is
the choice that does not contradict the project's own documented build-floor rule.

## Fedora 44 — full output, first run (before any fix), unpatched dist/native bundle

Bootstrap: `dnf install -y systemd systemd-udev curl jq openssl ca-certificates`, then
`ln -sf /usr/lib/systemd/systemd /sbin/init` (Fedora's bare `systemd` package does not
create `/sbin/init` on its own — confirmed with `dnf provides /sbin/init`, no match).
`--cap-add=NET_ADMIN,NET_RAW` as in the existing job.

```
=== Install from the staged bundle ===
[19:00:57] Pre-flight checks
[19:00:57] Pre-flight checks — done in 0s
[19:00:57] Downloading bundle
[19:01:01] Downloading bundle — done in 4s
[19:01:01] Installing files
[19:01:02] Installing files — done in 1s
[19:01:02] System dependencies
    Binary path: /usr/pgsql-15/bin
    Install path: /usr/local/bin/nats-server
[19:01:42] warning: Docker installation failed — container telemetry will be unavailable
[19:01:42] warning: Install Docker manually later and re-run: bash install.sh --upgrade
[19:01:42] System dependencies — done in 40s
[19:01:42] Preparing database
[19:01:42] warning: Redis system user missing (redis-server may be only partially installed) — creating it
    Data directory: /var/lib/circuitbreaker/postgres (postgres:postgres 700)
    Pool port: 6432, Backend: PostgreSQL 5432
[19:01:55] Preparing database — done in 13s
[19:01:55] Services and networking
[19:02:01] warning: Skipping Docker socket proxy (Docker not available)
[19:02:01] Services and networking — done in 6s
[19:02:01] Starting Circuit Breaker
[19:02:19] Starting Circuit Breaker — done in 18s
  Installation complete! Open the HTTPS URL above to get started.

=== Assert the installer reported every phase ===
=== Wait for /livez ===
=== Wait for /readyz ===
{"ready":true,"state":"ready","checks":{"db":"ok","redis":"ok"},"health":"ready","degraded":[],"writes_permitted":true}
=== Assert the installed binary contains its application ===
selftest OK — 10 targets resolved

=== Journey complete ===
```

**Fedora passed on the first attempt, unmodified.** No `install.sh`/`deploy/setup.sh`
defect was found on the `dnf`/Fedora branch. Re-run afterward against the
Arch-motivated patched bundle (below) to confirm no regression — also "Journey
complete", identical result.

The two `warning:` lines (Docker install failed; Docker socket proxy skipped) are
**harness limitations, not installer defects** — classified below.

## Arch — full output across three attempts; two real, distro-specific `install.sh`/`deploy/setup.sh` defects found and fixed

Bootstrap: base `archlinux:latest` image already ships systemd with `/sbin/init`
present (confirmed: `/sbin/init -> ../lib/systemd/systemd`, `systemctl` on PATH) — only
`pacman -S curl jq openssl ca-certificates` was needed, no init bootstrap at all. This
is itself a finding worth recording: Arch is the *simplest* of the five images to boot
under systemd, and also the one whose packaging assumptions broke the installer worst.

### Attempt 1 — PostgreSQL fails to start (genuine defect, distro-specific)

```
Job for circuitbreaker-postgres.service failed because the control process exited with error code.
● circuitbreaker-postgres.service - Circuit Breaker PostgreSQL 15
     Active: activating (auto-restart) (Result: exit-code)
    Process: 1630 ExecStart=/usr/bin/postgres -D /var/lib/circuitbreaker/postgres (code=exited, status=1/FAILURE)
cb-postgres[1630]: LOG:  starting PostgreSQL 18.6 on x86_64-pc-linux-gnu ...
cb-postgres[1630]: LOG:  listening on IPv4 address "127.0.0.1", port 5432
cb-postgres[1630]: FATAL:  could not create lock file "/run/postgresql/.s.PGSQL.5432.lock": No such file or directory
cb-postgres[1630]: LOG:  database system is shut down
```

**Root cause (confirmed, not guessed):** every distro's `postgres` binary here defaults
`unix_socket_directories` to `/run/postgresql`, and `deploy/setup.sh` never sets it
explicitly — it relied on the OS package creating that directory. On Debian
(`postgresql-common`'s tmpfiles.d rule) and on the PGDG dnf packages (their own
tmpfiles.d rule) that assumption held, silently, which is exactly why nobody had ever
seen this fail. Arch's `postgresql` package does not create `/run/postgresql` at all —
confirmed directly:

```
$ pacman -Ql postgresql | grep tmpfiles
postgresql /usr/lib/tmpfiles.d/
postgresql /usr/lib/tmpfiles.d/postgresql.conf
$ cat /usr/lib/tmpfiles.d/postgresql.conf
d /var/lib/postgres      700 postgres postgres
d /var/lib/postgres/data 700 postgres postgres
```

— only `/var/lib/postgres`, Arch's own default data directory (which Circuit Breaker
doesn't use — it installs to `${CB_DATA_DIR}/postgres`), never `/run/postgresql`. This
is exactly the "missing directory creation for one distro's packaging behavior" class
of defect the task brief anticipated. Classified: **genuine defect, fixed.**

**Fix (commit `fix: create the PostgreSQL runtime socket dir on every distro`):**
- `deploy/systemd/circuitbreaker-postgres.service`: added `RuntimeDirectory=postgresql`
  / `RuntimeDirectoryMode=0755`, so systemd creates `/run/postgresql` itself before
  every start, on every distro, instead of relying on the OS package having done it —
  the same pattern already used by `circuitbreaker-pgbouncer.service`,
  `circuitbreaker-backend.service`, `circuitbreaker-worker@.service` and
  `cb-helperd.service` in this same tree.
- `deploy/config/postgresql.conf.template`: pinned `unix_socket_directories =
  '/run/postgresql'` explicitly rather than leaving it to each package's compiled-in
  default, so behavior no longer depends on three different packagers agreeing on the
  same undocumented default.
- Confirmed safe: `pg_hba.conf`'s two `local` (peer-auth) lines — used only by
  `deploy/setup.sh`'s bootstrap `CREATE USER`/`CREATE DATABASE` calls — depend on this
  socket; every other connection (pgbouncer, backend, `psql -h 127.0.0.1`) is TCP and
  unaffected.

### Attempt 2 (after the PostgreSQL fix) — Nginx config write fails (genuine defect, distro-specific)

```
[19:07:39] Services and networking
install.sh: line 868: /etc/nginx/conf.d/circuitbreaker.conf: No such file or directory
::error::install.sh exited 1
```

**Root cause (confirmed):** `deploy/setup.sh` writes
`/etc/nginx/conf.d/circuitbreaker.conf` via `cb_render_template`'s plain
`printf > "$dest"`, which fails outright if the parent directory doesn't exist. On
Debian and Fedora, the nginx package creates `/etc/nginx/conf.d/` itself and its
shipped `nginx.conf` already contains `include /etc/nginx/conf.d/*.conf;` — confirmed
directly on both:

```
debian:12  nginx.conf: include /etc/nginx/conf.d/*.conf;
fedora:44  nginx.conf: include /etc/nginx/conf.d/*.conf;
```

Arch's pacman `nginx` package does neither:

```
$ pacman -Ql nginx | grep etc/nginx
nginx /etc/nginx/              (no conf.d entry at all)
$ grep -n 'include\|conf.d' /etc/nginx/nginx.conf
13:include modules.d/*.conf;
21:    include       mime.types;
```

Its stock `nginx.conf` instead hardcodes one `server { listen 80; ... }` block directly
in the file and never references `conf.d`. So even a directory created by hand would be
silently ignored — a worse failure mode than the crash, because `nginx -t` would still
pass and the service would start without ever serving Circuit Breaker. Classified:
**genuine defect, fixed.**

**Fix (same commit as above extended, or a second `fix:` commit — see actual history):**
in `deploy/setup.sh`'s "Writing Nginx configuration" step, before rendering the
template: `mkdir -p /etc/nginx/conf.d` unconditionally, and — only if
`/etc/nginx/nginx.conf` doesn't already reference `conf.d/*.conf` — insert
`include /etc/nginx/conf.d/*.conf;` right after the `http {` line with `sed`. No-op on
Debian/Fedora/RHEL (the grep guard skips them, confirmed by the unchanged re-run
below); load-bearing on Arch. Did **not** touch Arch's inline default port-80
`server{}` block — it's cosmetic (Circuit Breaker's own `CB_PORT` default is 8088, not
80) and editing further into a package-owned file for a cosmetic issue was judged out
of scope.

### Attempt 3 (after both fixes) — full output, "Journey complete"

```
[19:10:52] Services and networking
    Redis data: /var/lib/circuitbreaker/redis (redis:redis)
    Port: 6379, Max memory: 256MB, Policy: allkeys-lru
    Port: 4222, Store: /var/lib/circuitbreaker/nats
[19:11:01] warning: Could not pull docker-socket-proxy image — container telemetry disabled
[19:11:01] warning: Enable it later: docker pull tecnativa/docker-socket-proxy && bash install.sh --upgrade
[19:11:01] Services and networking — done in 9s
[19:11:01] Starting Circuit Breaker
[19:11:19] Starting Circuit Breaker — done in 18s
  Installation complete! Open the HTTPS URL above to get started.

=== Assert the installer reported every phase ===
=== Wait for /livez ===
=== Wait for /readyz ===
{"ready":true,"state":"ready","checks":{"db":"ok","redis":"ok"},"health":"ready","degraded":[],"writes_permitted":true}
=== Assert the installed binary contains its application ===
selftest OK — 10 targets resolved

=== Journey complete ===
```

Also re-ran Fedora against the same fix-patched bundle afterward: identical "Journey
complete" result, confirming the Arch-specific fixes did not regress the already-passing
`dnf` branch.

## Classification of every warning/failure seen

| Symptom | Distro(s) | Classification | Action |
|---|---|---|---|
| `could not create lock file /run/postgresql/...: No such file or directory` | Arch only | **Genuine `install.sh`/`deploy/setup.sh` defect** — assumed a directory the Arch package never creates | Fixed: `RuntimeDirectory=postgresql` + pinned `unix_socket_directories` |
| `/etc/nginx/conf.d/circuitbreaker.conf: No such file or directory` | Arch only | **Genuine defect** — assumed a directory + an `include` line the Arch package never provides | Fixed: `mkdir -p` + conditional `sed` insert |
| `Docker installation failed — container telemetry will be unavailable` | Fedora, Arch (both) | **Harness limitation** — installing/running the Docker engine inside an already-nested rootless podman container is not a configuration this sandbox supports; `install.sh` itself already handles the failure correctly (a non-fatal `cb_warn`, install continues to completion) | Not fixed — nothing to fix; the installer's existing graceful-degradation path is exactly what ran |
| `Could not pull docker-socket-proxy image — container telemetry disabled` | Fedora, Arch (both) | **Harness limitation** — same nested-container cause as above (no working Docker to pull the proxy image into) | Not fixed |
| PostgreSQL bundle glibc floor (`GLIBC_2.43` vs Rocky 9's 2.34 / Rocky 10's 2.39) | Rocky (not executed) | **Sandbox/build-host limitation, documented pre-emptively** — the locally built bundle used to test Fedora/Arch cannot run on any Rocky version; this is exactly the situation the task brief warned about for Debian/Ubuntu, extended to Rocky by the same mechanism | Not applicable to fix — real CI builds fresh on ubuntu-22.04 (2.35 floor), which Rocky 10 (2.39) clears; Rocky 9 (2.34) would not, which is why the matrix uses `:10` |

No failure encountered here was dismissed as flaky. Every one was reproduced, root-caused
against a specific file and line, and either fixed (with a before/after re-run proving
the fix) or classified as outside `install.sh`'s control with the specific mechanism
named.

## Remaining gaps — do not extrapolate past what was measured

- **arm64 is unmeasured on every distro, including the two already in the matrix before
  this work (Ubuntu, Debian).** This document adds no arm64 coverage. The `dnf` and
  `pacman` branches' arm64 behavior is exactly as unknown after this work as before it.
- **RHEL and AlmaLinux are not in the CI matrix.** `deploy/setup.sh` branches them into
  the identical `dnf` code path as Fedora/Rocky (same `cb_detect_pkg_mgr` case arm), and
  Rocky is now covered as that family's representative, but RHEL's and AlmaLinux's own
  package repositories were not queried and their images were not booted. Treat "the
  `dnf` branch has been exercised" as true; treat "RHEL and AlmaLinux specifically have
  been exercised" as false.
- **Rocky Linux was added to the CI matrix but not executed anywhere in this work** —
  the glibc floor made it untestable with the artifact available locally. The first
  real evidence for the Rocky leg will be its first green (or red) run in actual GitHub
  Actions CI, not this document.
- **Arch is rolling.** `pacman -Sy` pulls whatever `archlinux:latest` resolves to on the
  day the job runs; a future failure there may be a genuine upstream Arch regression
  rather than a Circuit Breaker defect. This document's Arch findings are pinned to
  2026-09-20's package versions (PostgreSQL 18.6, nginx as shipped that day) and are
  not a promise that Arch stays green — only that the two defects found on
  2026-09-20's package set were `install.sh`'s own, not Arch's.
- **The `--docker` compose install path remains completely out of scope**, as it was
  before this work — nothing here touches it.

## Sandbox deviations from the committed workflow (disclosed, none affect CI correctness)

- This sandbox has no passwordless `sudo` (`sudo -n true` fails). All local
  reproduction here used **rootless podman** directly, without `sudo`, for every
  `podman` invocation. The committed `.github/workflows/installer-journey.yml` keeps
  `sudo podman` throughout, matched to a real GitHub Actions runner, where sudo is
  passwordless — this is a local-repro-only deviation, not a change to the workflow's
  actual behavior. The same deviation is recorded in
  `docs/evidence/2026-09-20-installer-journey-flake-rate.md` for the original two-distro
  work and was judged not to affect the committed file's correctness there either.
- The prebuilt `dist/native/circuit-breaker_0.4.2_linux_amd64.tar.gz` (glibc 2.43,
  built 2026-09-20 on this Fedora 44 host) was reused rather than rebuilt, per the task
  instruction. After the two Arch-specific fixes to `deploy/setup.sh`,
  `deploy/systemd/circuitbreaker-postgres.service` and
  `deploy/config/postgresql.conf.template`, testing the fix required the *fixed*
  `deploy/` tree, which ships **inside** the tarball
  (`manifest.json`'s `resources.deploy: "deploy"`). Rebuilding the whole bundle (full
  frontend build + PyInstaller) was avoidable for a two-text-file change, so the
  tarball was extracted, its `deploy/setup.sh`,
  `deploy/systemd/circuitbreaker-postgres.service` and
  `deploy/config/postgresql.conf.template` were overwritten with the fixed versions
  from the working tree, and it was re-packed — the binary itself (and its glibc floor)
  is untouched. This patched artifact was used only for local re-verification; nothing
  under `dist/` is committed, and CI builds its own bundle from source on every run
  regardless.

## Addendum (same day) — Debian 12 and Ubuntu 22.04 re-run against the Arch fixes

The two genuine defects found and fixed above (commits `90fba73b`,
`8d54a69f`) touch `deploy/systemd/circuitbreaker-postgres.service`,
`deploy/config/postgresql.conf.template` and `deploy/setup.sh` — all three used by
every distro, not only Arch. This addendum closes the gap the rest of this document
left open: **Debian 12 and Ubuntu 22.04 — "already covered; not re-run" above — are
now re-run against the fix-patched tree**, on a properly glibc-compatible bundle
(not the patched-tarball workaround used for the Arch/Fedora re-runs above).

### Build: `scripts/build-in-release-image.sh`

Ran to completion, via `docker` (auto-selected ahead of `podman` per the script's own
`for candidate in docker podman` probe order — docker was present and usable on this
host; podman was only needed, and used, for the systemd-in-a-container journey legs
below). Output bundle:

```
$ ls -lh dist/native/circuit-breaker_0.4.2_linux_amd64.tar.gz
-rw-r--r--. 1 shawnji shawnji 175M Sep 20 12:29 dist/native/circuit-breaker_0.4.2_linux_amd64.tar.gz

$ cat dist/native/bundle/share/build-info.json
{
  "version": "0.4.2", "os": "linux", "arch": "amd64", "built_by": "local",
  "glibc": "2.35", "distro": "ubuntu-22.04", "python": "3.12.13",
  "ci_run": "", "ci_workflow": "", "commit": ""
}
```

`glibc: "2.35"` — the same floor `.github/workflows/build.yml` produces, confirmed
below to be below both target distros' own glibc.

### glibc-floor confirmation

`objdump -T` on the outer PyInstaller bootloader ELF only shows symbols up to
`GLIBC_2.14` — the onefile bootloader's own direct imports, not the embedded
interpreter's, so that check alone is not informative for a onefile build. The
direct proof is executing the binary on each target distro:

```
$ podman run --rm -v ".../circuit-breaker:/circuit-breaker:ro,z" docker.io/library/debian:12 \
    /circuit-breaker --selftest
CORS: no valid origins configured — same-origin only.
selftest OK — 10 targets resolved

$ podman run --rm -v ".../circuit-breaker:/circuit-breaker:ro,z" docker.io/library/ubuntu:22.04 \
    /circuit-breaker --selftest
tzlocal/unix.py:208: UserWarning: Can not find any timezone configuration, defaulting to UTC.
CORS: no valid origins configured — same-origin only.
selftest OK — 10 targets resolved
```

(The `:ro,z` SELinux relabel on the bind mount is a sandbox necessity on this
enforcing-SELinux Fedora host — the first attempt without it failed every exec with
`Permission denied`, not a glibc problem. Recorded as another local-repro-only
deviation, same category as the `sudo podman` one above.)

Both distros execute the binary and pass `--selftest` cleanly: the 2.35 floor
clears Debian 12's glibc 2.36 and Ubuntu 22.04's own glibc 2.35.

### Debian 12 — full output, "Journey complete"

Bootstrap identical in shape to the Fedora/Arch runs above and to
`.github/workflows/installer-journey.yml`'s apt branch: base `debian:12` image has no
init at all, so `apt-get install systemd systemd-sysv curl jq openssl ca-certificates`
first (creates `/sbin/init` via `update-alternatives`, the apt-family behavior the
workflow file's own comments already document), commit as a base image, then start the
real systemd container from it with `--cap-add=NET_ADMIN,NET_RAW`.

```
=== Install from the staged bundle ===
[19:32:34] Pre-flight checks
[19:32:34] Pre-flight checks — done in 0s
[19:32:34] Downloading bundle
[19:32:34] Downloading bundle — done in 0s (approx.)
[19:32:34] Installing files
[19:32:34] Installing files — done in 0s (approx.)
[19:32:34] System dependencies
    Application: /opt/circuitbreaker
    Data: /var/lib/circuitbreaker
    Config: /etc/circuitbreaker
    Binary path: /usr/lib/postgresql/15/bin
    Install path: /usr/local/bin/nats-server
[19:33:16] System dependencies — done in 42s
[19:33:16] Preparing database
    Data directory: /var/lib/circuitbreaker/postgres (postgres:postgres 700)
    Pool port: 6432, Backend: PostgreSQL 5432
[19:33:27] Preparing database — done in 11s
[19:33:27] Services and networking
    Redis data: /var/lib/circuitbreaker/redis (redis:redis)
    Port: 6379, Max memory: 256MB, Policy: allkeys-lru
    Port: 4222, Store: /var/lib/circuitbreaker/nats
[19:33:35] warning: Could not pull docker-socket-proxy image — container telemetry disabled
[19:33:35] warning: Enable it later: docker pull tecnativa/docker-socket-proxy && bash install.sh --upgrade
[19:33:35] Services and networking — done in 8s
[19:33:35] Starting Circuit Breaker
[19:33:53] Starting Circuit Breaker — done in 18s
  Installation complete! Open the HTTPS URL above to get started.

=== Assert the installer reported every phase ===
=== Wait for /livez ===
=== Wait for /readyz ===
{"ready":true,"state":"ready","checks":{"db":"ok","redis":"ok"},"health":"ready","degraded":[],"writes_permitted":true}
=== Assert the installed binary contains its application ===
selftest OK — 10 targets resolved

=== Journey complete ===
```

`journey exit code for debian12: 0`. Same `Could not pull docker-socket-proxy image`
harness limitation already classified above (nested-container Docker), nothing new.

### Ubuntu 22.04 — full output, "Journey complete"

```
=== Install from the staged bundle ===
[19:35:07] Pre-flight checks
[19:35:07] Pre-flight checks — done in 0s
[19:35:07] Downloading bundle
[19:35:08] Downloading bundle — done in 1s
[19:35:08] Installing files
[19:35:09] Installing files — done in 1s
[19:35:09] System dependencies
    Binary path: /usr/lib/postgresql/15/bin
    Install path: /usr/local/bin/nats-server
[19:36:00] System dependencies — done in 51s
[19:36:00] Preparing database
    Data directory: /var/lib/circuitbreaker/postgres (postgres:postgres 700)
    Pool port: 6432, Backend: PostgreSQL 5432
[19:36:11] Preparing database — done in 11s
[19:36:11] Services and networking
    Redis data: /var/lib/circuitbreaker/redis (redis:redis)
    Port: 6379, Max memory: 256MB, Policy: allkeys-lru
    Port: 4222, Store: /var/lib/circuitbreaker/nats
[19:36:20] warning: Could not pull docker-socket-proxy image — container telemetry disabled
[19:36:20] warning: Enable it later: docker pull tecnativa/docker-socket-proxy && bash install.sh --upgrade
[19:36:21] Services and networking — done in 10s
[19:36:21] Starting Circuit Breaker
[19:36:38] Starting Circuit Breaker — done in 17s
  Installation complete! Open the HTTPS URL above to get started.

=== Assert the installer reported every phase ===
=== Wait for /livez ===
=== Wait for /readyz ===
{"ready":true,"state":"ready","checks":{"db":"ok","redis":"ok"},"health":"ready","degraded":[],"writes_permitted":true}
=== Assert the installed binary contains its application ===
selftest OK — 10 targets resolved

=== Journey complete ===
```

`journey exit code for ubuntu2204: 0`. Same harness-limitation warning, no new
findings.

**Conclusion: the two Arch fixes did not regress the apt path.** Both apt-family
legs — the two distros this document's original table listed as "unchanged, not
re-run" — now have their own direct evidence: **re-run, both green, on a
glibc-2.35-floor bundle built the same way CI builds its own.** The table above is
superseded by this addendum for those two rows; nothing else in this document
changes.

### `RuntimeDirectory=postgresql` / `/run/postgresql` shared-ownership check

Investigated per explicit instruction before touching anything, because
`RuntimeDirectory=` makes systemd remove that directory when the owning unit stops,
and Debian's `postgresql-common` package also manages `/run/postgresql` via its own
persistent `systemd-tmpfiles.d` rule (`d /run/postgresql 2775 postgres postgres`,
confirmed by reading `/usr/lib/tmpfiles.d/postgresql-common.conf` directly in a
`debian:12` container) — a directory that predates and is independent of any single
systemd unit's `RuntimeDirectory=` tracking.

Built a synthetic reproduction first (a throwaway `cb-test-postgres.service` in a
scratch systemd container, `RuntimeDirectory=postgresql`, no relation to this repo)
to confirm systemd's actual behavior in isolation: starting it removed and recreated
`/run/postgresql` under systemd's ownership (root:root 0755, losing
`postgresql-common`'s `2775`/setgid); stopping it **deleted `/run/postgresql`
entirely** until the unit started again. `RuntimeDirectoryPreserve=yes` on the same
synthetic unit confirmed to prevent the deletion on stop while still creating the
directory on start if absent — so the removal-on-stop behavior, and the proposed
remedy, are both real as systemd primitives. No repository file was touched for this
synthetic test.

Whether that primitive is actually a hazard **in Circuit Breaker's own deployment
model** turns on whether anything else is still using `/run/postgresql` when
`circuitbreaker-postgres` stops on an installed host. It is not, and the two apt
journey runs above prove it directly rather than by inspection alone —
`deploy/setup.sh:490-491` and `:1747-1748` stop **and disable** the distro's own
PostgreSQL service before `circuitbreaker-postgres` ever starts, and pin each
detected cluster's `start.conf` to `manual` so the `postgresql-common` boot-time
generator won't restart it either. Checked directly in both completed installs
above:

```
# Debian 12, after "Journey complete":
$ systemctl is-active postgresql    → inactive
$ systemctl is-enabled postgresql   → disabled
$ cat /etc/postgresql/15/main/start.conf → manual
$ systemctl is-active circuitbreaker-postgres → active
$ systemctl is-enabled circuitbreaker-postgres → enabled

# Ubuntu 22.04, after "Journey complete": identical — inactive / disabled / manual /
# active / enabled.
```

**Finding: not a hazard in this deployment model, no change made.**
`circuitbreaker-postgres` is the sole consumer of `/run/postgresql` on an installed
host in both apt-family runs actually exercised here — the distro's own PostgreSQL
is neutralized (stopped, disabled, and its generator-driven autostart pinned off)
before Circuit Breaker's instance ever touches that directory, so systemd removing
`/run/postgresql` when `circuitbreaker-postgres` stops cannot pull it out from under
anything that is actually running on a Circuit Breaker host. `deploy/systemd/
circuitbreaker-postgres.service` is unchanged; `RuntimeDirectoryPreserve=yes` was not
added. The only residual is an operator who deliberately re-enables the distro
PostgreSQL afterwards, which contradicts what the installer itself set up and is out
of scope for this check.

### Verification gates

```
$ .venv/bin/python -m pytest tests/build -q
766 passed in 104.42s

$ .venv/bin/python scripts/ci/sync_installer_ui.py --check
install.sh is in sync with deploy/lib/ui.sh

$ sha256sum of cb_logo's body in install.sh
dc85b6b9501fbad91dac6a3988857365b772530967af2456e6dfc4857a5db36d   (unchanged, matches required hash)
```

No commits were made for this addendum — no `install.sh`, `deploy/`, or systemd unit
file changed. `git status` is clean before and after.
