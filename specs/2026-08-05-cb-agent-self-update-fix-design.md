# cb-agent — Self-Update Fix Design (Bug 1)

**Date:** 2026-08-05
**Status:** Approved
**Related:** `specs/2026-07-26-cb-agent-design.md` (§ Self-update decision this design repairs),
`plans/2026-08-04-cbi-agent-slice1-gap-closure-tasks.md` (Tasks 17, 22-25 — the install/systemd
and self-update tasks whose seam this bug lives in), `.superpowers/sdd/2026-08-04-cbi-agent-slice1-gap-closure-tasks/progress.md`
(Task 31's finding that first surfaced this bug)

## Context

Task 31's Docker E2E acceptance test (the first thing to ever exercise agent self-update against
a *real* systemd install, rather than a unit test running as its own user) found that self-update
cannot succeed on any host installed via the real install script:

- `update.Swap()` renames the running binary in place at a fixed path (`/usr/local/bin/cb-agent`),
  which requires write access to that file and its containing directory.
- The binary is root-owned (created by the install script, which runs as root); the daemon runs
  as the dedicated unprivileged `cb-agent` system user (`User=cb-agent` in the systemd unit).
- The systemd unit sets `ProtectSystem=strict` with `ReadWritePaths=/var/lib/cb-agent` only —
  `/usr/local/bin` is not writable by the service — and `NoNewPrivileges=true` forecloses any
  escalation route.

No unit test could have caught this: every existing `update.Swap`/`Rollback` test runs as the
test process's own (typically privileged, or at least self-owning) user against a temp
directory, never against the real install's ownership/sandbox combination. No host has ever
completed a real self-update — the mechanism has been structurally non-functional since Tasks
22-25 shipped it.

Confirmed: no host in the field needs to be migrated in place by this fix. This design only
needs to make self-update work going forward, on hosts installed by the corrected
`install-agent.sh`.

## Decisions

| Question | Decision |
|---|---|
| Fix shape | Symlink indirection through the already-writable state directory — no privilege changes |
| New privileged code paths | None. Self-update stays entirely within permissions `cb-agent` already has today |
| systemd unit changes | None (`ExecStart`, `ProtectSystem`, `ReadWritePaths`, `NoNewPrivileges` all untouched) |
| Existing installs | Not migrated — none has ever completed a real update; only new installs are fixed |
| Version retention | Live version + immediately-previous only, mirroring today's single `.previous` |

### Rejected alternatives

- **Root-side update helper** (an `ExecStartPre=+...` line or separate privileged unit that
  performs the swap on the unprivileged daemon's behalf). Introduces a genuinely new privilege
  boundary crossing — a root-executed code path acting on data an unprivileged process supplied —
  which needs its own hardening and security review, and needs some way for the unprivileged
  daemon to trigger its own restart (a further privilege question). Rejected: the symlink
  approach achieves the same outcome with zero new privileged surface.
- **Loosen the systemd sandbox** (add `/usr/local/bin` to `ReadWritePaths`, or drop
  `ProtectSystem=strict`). Directly undoes Task 30's hardening for the sole benefit of this one
  feature, and widens what a compromised agent process could do to the host far beyond the
  binary it's supposed to update. Rejected outright.
- **Migrate existing installs in place.** Unnecessary — confirmed no host has ever completed a
  real self-update, so there is nothing on any real host to preserve or migrate.

## 1. Directory / symlink layout

Two levels of indirection, both new:

```
/usr/local/bin/cb-agent              (symlink, root-owned, created once at install — never
                                       touched again after that)
    -> {stateDir}/current            (symlink, cb-agent-owned — this is what self-update
                                       re-points)
        -> {stateDir}/versions/1.4.0/cb-agent   (real file, immutable once written)
```

`{stateDir}` is the existing `config.StateDir()` (`/var/lib/cb-agent` in production, already the
sole `ReadWritePaths` entry and already owned by `cb-agent:cb-agent`). `ExecStart=/usr/local/bin/cb-agent`
in the unit file is untouched — it's still the stable, familiar, PATH-visible entry point both
systemd and an operator's interactive shell use; only what it ultimately resolves to changes
after an update.

## 2. Install script (`agent_install.py`)

`_INSTALL_SCRIPT_TEMPLATE`'s binary-install step changes from:

```sh
install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent
```

to creating the versioned layout and both symlinks:

```sh
install -d -m 0755 -o cb-agent -g cb-agent "/var/lib/cb-agent/versions/{latest_version}"
install -m 0755 -o cb-agent -g cb-agent "$TMP_BIN" "/var/lib/cb-agent/versions/{latest_version}/cb-agent"
ln -sfn "versions/{latest_version}" /var/lib/cb-agent/current
chown -h cb-agent:cb-agent /var/lib/cb-agent/current
ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent
```

(`/var/lib/cb-agent` itself and its ownership are already created earlier in the script — see
the existing `mkdir -p ... && chown cb-agent:cb-agent /var/lib/cb-agent` lines, unchanged.)
`sudo -u cb-agent /usr/local/bin/cb-agent enroll` and `systemctl enable --now cb-agent` are
unchanged; they already go through the stable path and don't care what it resolves to.

## 3. `update.go` rewrite

`os.Executable()` resolves symlinks to their final real target (Linux implements it via
`readlink /proc/self/exe`), so it can no longer be the swap/rollback/re-exec target — using it
would mean re-pointing or re-execing one specific version's immutable file instead of the
indirection point. Every call site that currently derives a target from `os.Executable()` for
update purposes switches to a fixed path instead: `currentLink := filepath.Join(config.StateDir(), "current")`.

- **`Swap(newBinaryPath, versionsDir, currentLink string) (prevVersionDir string, err error)`**
  — replaces today's `Swap(newPath, targetPath string)`. Moves the verified new binary into
  `versionsDir/<version>/cb-agent` (fsynced, matching today's `fsyncFile`/`fsyncDir` durability
  guarantees), then atomically re-points `currentLink`: `os.Symlink` to a temp name in the same
  directory, `os.Rename` over `currentLink` (atomic same-filesystem rename, exactly like
  `atomicWriteFile`'s existing temp-then-rename idiom), then `fsyncDir(currentLink)`. Returns the
  previous version's directory (read by resolving `currentLink`'s target *before* the swap) so
  `Rollback` knows where to point back to.
- **`Rollback(currentLink, prevVersionDir string) error`** — replaces today's
  `Rollback(targetPath string)`. Re-points `currentLink` back to `prevVersionDir` via the same
  atomic symlink-rename.
- **Marker / two-phase-confirm logic** (`WriteMarker`/`MarkSwapped`/`ReadMarker`/`ClearMarker`) —
  same shape and the same crash-safety ordering guarantee as today (write phase-pending-swap
  *before* the swap runs; write phase-pending-confirm only *after* it durably succeeds), just
  persisting the previous version directory instead of relying on an implicit fixed `.previous`
  path. The legacy bare-marker-format fallback (`ReadMarker`'s no-phase-prefix branch, there for
  pre-Task-25 binaries) is dropped: nothing in the field has ever completed a real swap under any
  scheme, old or new, so there is no legacy on-disk state to stay compatible with.
- **`preserveModeAndOwnership`** is deleted. It existed to restore a root-owned target file's
  original mode/ownership after being renamed over — every version directory and binary is now
  created directly by `cb-agent`, as `cb-agent`, at a fixed `0755`, so there is no
  "restore the original owner" step because nothing is ever renamed over an existing root-owned
  file anymore.

## 4. `main.go` orchestration

Every place `binaryPath, err := os.Executable()` currently feeds `Swap`/`Rollback` switches to
the fixed `currentLink`. The re-exec calls (`syscall.Exec(binaryPath, os.Args, os.Environ())`)
switch to exec'ing `/usr/local/bin/cb-agent` (the stable top-level path) instead of the resolved
`binaryPath` — so the kernel resolves the symlink chain fresh at exec time and picks up whatever
`current` points to *now*, not whatever was running before the swap. `os.Executable()` remains
useful and unchanged for anything that isn't update-related (none of the current non-update call
sites need to move).

## 5. Version retention

After an update is confirmed (a `hello.ack` arrives inside the confirmation window and the
marker clears), prune every version directory except `current`'s target and the one just
confirmed-away-from. No configurable retention count — this mirrors today's single `.previous`
behavior and there's no requirement motivating more.

## 6. Testing

- Unit tests for the new symlink-swap primitive: atomic re-point under normal operation, and a
  simulated crash between the temp-symlink create and the rename (proving the pre-swap state is
  always recoverable, mirroring the existing marker-ordering tests).
- `Swap`/`Rollback`/marker tests rewritten against the new signatures, replacing (not
  supplementing) the file-rename-based versions they make obsolete.
- `main.go`'s existing `onUpdate`/rollback/re-exec tests updated for the `currentLink`-based
  flow, including a real-symlink-chain fixture rather than a bare temp file.
- A **new** Docker E2E scenario reproducing Task 31's original step 7 (successful update +
  forced rollback) against the *fixed* install layout — real `useradd cb-agent`, the real
  systemd unit with `ProtectSystem=strict`/`ReadWritePaths`/`NoNewPrivileges` intact, matching
  production exactly. This is the regression test that actually proves the P0 is closed: unit
  tests running as their own user cannot reproduce the permission boundary that caused the bug,
  so they cannot prove it's fixed either.
- `agent_install.py`'s install-script generation gets a test (or an existing one is extended)
  asserting the generated script creates the versions directory, both symlinks, and the
  correct ownership — whatever the existing coverage convention for that script is; confirm
  during planning.

## Non-goals

- Migrating any already-installed host to the new layout (none needs it — see Context).
- Changing systemd sandboxing, privilege model, or the install script's use of root for the
  one-time initial install.
- Configurable version-retention depth.
