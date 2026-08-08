# cb-agent Self-Update Fix (Bug 1) — Task Breakdown

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cb-agent self-update actually work on a real install by routing it entirely through
permissions the unprivileged `cb-agent` user already has, instead of renaming a root-owned binary
in place.

**Architecture:** Two levels of symlink indirection through the already-writable state directory —
`/usr/local/bin/cb-agent` (root-owned, created once at install, never touched again) ->
`{stateDir}/current` (cb-agent-owned symlink, re-pointed by every update) ->
`{stateDir}/versions/<version>/cb-agent` (immutable real file). No systemd unit changes, no new
privileged code paths.

**Tech Stack:** Go 1.22 (`apps/agent`), Python/FastAPI (`apps/backend`), POSIX `sh` (install
script), Docker Compose (E2E).

**Derived from:** `specs/2026-08-05-cb-agent-self-update-fix-design.md` (authoritative for
requirements/rationale — this file only adds task boundaries, current-state notes, and exact
signatures/code for implementer subagents). Also see
`plans/2026-08-04-cbi-agent-slice1-gap-closure-tasks.md` Tasks 17, 22-25 (the install/systemd and
self-update tasks whose seam this bug lives in).

**Scope decision (confirmed with the human partner):** the design doc's Testing section asks for a
*new* Docker E2E scenario running inside a real systemd unit
(`ProtectSystem=strict`/`ReadWritePaths`/`NoNewPrivileges` intact). The existing E2E harness
(`apps/agent/e2e/Dockerfile`) does not run systemd at all today — building that from scratch is
out of scope for this fix. Task 4 instead adapts the *existing* harness (already a real,
non-systemd container reproducing the ownership half of the bug) to install through the new
versioned-symlink layout, and un-xfails the existing
`test_agent_update_success_and_forced_rollback`, which already proves the actual regression
end-to-end. A genuine systemd-sandboxed E2E harness remains a legitimate follow-up, not part of
this fix.

**Gap closed beyond the design doc's literal text:** the design doc says "`os.Executable()` remains
useful and unchanged for anything that isn't update-related (none of the current non-update call
sites need to move)." That's incorrect for one call site: `cmd/cb-agent/main.go`'s
`resolveUninstallPaths()` uses `os.Executable()` to find "the binary" to remove during `cb-agent
uninstall`. Under the new symlink layout, `os.Executable()` resolves *through* both symlink levels
to the final real file inside `{stateDir}/versions/<v>/cb-agent` — not the stable
`/usr/local/bin/cb-agent` entry point — which would leave that root-owned top-level symlink behind
after an otherwise-complete uninstall, and would try to derive a `.previous`-backup path that no
longer exists in the new scheme. Task 2 fixes this alongside the rest of `main.go`'s orchestration
changes.

## Global Constraints

Apply to every task below; the task reviewer holds implementers to these:

- Go code follows `apps/agent`'s existing package/error/test style (table-driven tests where the
  existing tests already use that shape, `_test.go` per package, `fmt.Errorf("update: ...: %w",
  err)`-style wrapped errors). Python follows the existing service/test layering in
  `apps/backend/src/app/services` and `apps/backend/tests/services`.
- This codebase carries extensive doc comments explaining non-obvious invariants (crash-safety
  ordering, why a field exists, what a regression a test guards against). Preserve that density
  for new/changed functions — the task briefs below give the core logic and exact signatures;
  write full doc comments in the existing style around them, not just what's shown verbatim.
- Every function this plan renames, re-signatures, or removes has exactly the call sites and test
  references enumerated in its task — grep before finishing a task to confirm no other reference
  was missed (`grep -rn <old-name> apps/agent`).
- No existing host has ever completed a real self-update (confirmed in the design doc's Context
  section) — there is no on-disk legacy state to stay compatible with. Do not add
  backward-compatibility branches for the old flat-file layout or the old marker format.
- `install`, `ln`, `chown` invocations in the install script must remain valid POSIX `sh` (the
  script starts `#!/bin/sh` / `set -eu`) — `apps/backend/tests/services/test_agent_install.py::test_render_install_script_is_valid_bash_syntax`
  enforces this via `bash -n`.
- The Docker E2E test in Task 4 requires a real Docker daemon and a genuine ~2.5-minute wait (the
  real `rollbackWindow`, no test-only override — matching the existing test's own documented
  tradeoff). Docker is confirmed available in this environment; run it for real as this task's
  final verification rather than treating it as unverifiable.
- Commit at the end of each task with a clear message; do not bundle unrelated tasks.

## File Structure

- Modify `apps/agent/internal/update/update.go` — symlink-indirection `Swap`/`Rollback`, two-phase
  marker rewrite (adds `prevVersionDir`), new `PruneVersions`/`CurrentLinkPath`, deletes
  `preserveModeAndOwnership`.
- Modify `apps/agent/internal/update/update_test.go`, `update_durability_test.go` — rewritten
  against the new signatures.
- Modify `apps/agent/cmd/cb-agent/main.go` — `runDaemon`/`onConnected`/`onUpdate`/`watchForRollback`
  switch from `os.Executable()`-derived `binaryPath` to `update.CurrentLinkPath`/a fixed
  `installedBinaryPath` constant; `resolveUninstallPaths` pins to that same fixed path instead of
  `os.Executable()`; `uninstallPaths` drops `previousBinary`.
- Modify `apps/agent/cmd/cb-agent/main_test.go` — rewritten against the new signatures and the new
  uninstall-path fixture.
- Modify `apps/backend/src/app/services/agent_install.py` — `_INSTALL_SCRIPT_TEMPLATE`'s
  binary-install step creates the versioned directory and both symlinks instead of installing
  directly to `/usr/local/bin/cb-agent`.
- Modify `apps/backend/tests/services/test_agent_install.py` — new test for the versioned-symlink
  layout.
- Modify `apps/agent/e2e/Dockerfile` — installs the baked binary through the same versioned-symlink
  layout as the real install script.
- Modify `apps/agent/e2e/test_agent_e2e.py` — removes the `xfail` from
  `test_agent_update_success_and_forced_rollback` now that the underlying bug is fixed.

---

## Task 1: `internal/update` — symlink-indirection Swap/Rollback/marker rewrite

**Current state:** `apps/agent/internal/update/update.go` implements `Swap(newPath, targetPath
string) (string, error)` (renames `targetPath` to `targetPath+".previous"`, moves `newPath` into
`targetPath`, then `preserveModeAndOwnership` restores the original file's mode/owner) and
`Rollback(targetPath string) error` (renames the `.previous` backup back). The marker
(`WriteMarker`/`MarkSwapped`/`ReadMarker`/`ClearMarker`) encodes `"<phase>\n<version>"` and has a
legacy bare-format fallback branch in `ReadMarker`.

**Files:**
- Modify: `apps/agent/internal/update/update.go`
- Modify: `apps/agent/internal/update/update_test.go`
- Modify: `apps/agent/internal/update/update_durability_test.go`
- No changes needed (must stay green): `apps/agent/internal/update/update_security_test.go`,
  `apps/agent/internal/update/update_proxy_test.go` (neither touches `Swap`/`Rollback`/the marker)

**Interfaces produced (Task 2 consumes these):**
- `func CurrentLinkPath(stateDir string) string` — returns `filepath.Join(stateDir, "current")`.
- `func Swap(newBinaryPath, version, stateDir string) (prevVersionDir string, err error)`
- `func Rollback(currentLink, prevVersionDir string) error`
- `func WriteMarker(stateDir, targetVersion string) error` — signature unchanged.
- `func MarkSwapped(stateDir, targetVersion, prevVersionDir string) error` — gains a third param.
- `func ReadMarker(stateDir string) (version, prevVersionDir string, swapped, present bool, err error)`
  — gains a `prevVersionDir` return, inserted second.
- `func ClearMarker(stateDir string) error` — unchanged.
- `func PruneVersions(stateDir, currentLink, keepVersionDir string) error` — removes every
  `{stateDir}/versions/<v>` except the one `currentLink` resolves to and `keepVersionDir` (which
  may be `""`).

- [ ] **Step 1: Replace `update_test.go`'s `TestSwapAndRollback`, `TestMarker_WriteReadClear`,
  `TestMarker_MarkSwappedTransitionsPhase` with versions against the new API, and delete
  `TestMarker_LegacyBareFormatReadsAsSwapped` (the design doc explicitly drops the legacy
  bare-format fallback — nothing in the field can have written it under any scheme).**

  Replace the existing `TestSwapAndRollback` (lines 42-72) with:

  ```go
  func TestSwapAndRollback(t *testing.T) {
  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
  	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(oldVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}

  	newBinary := filepath.Join(dir, "new-download")
  	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}

  	prevVersionDir, err := Swap(newBinary, "0.2.0", dir)
  	if err != nil {
  		t.Fatalf("Swap() error = %v", err)
  	}
  	if prevVersionDir != oldVersionDir {
  		t.Errorf("Swap() prevVersionDir = %q, want %q", prevVersionDir, oldVersionDir)
  	}

  	newVersionDir := filepath.Join(dir, "versions", "0.2.0")
  	target, err := os.Readlink(currentLink)
  	if err != nil || target != newVersionDir {
  		t.Errorf("current symlink = (%q, %v), want %q", target, err, newVersionDir)
  	}
  	got, err := os.ReadFile(filepath.Join(newVersionDir, "cb-agent"))
  	if err != nil || string(got) != "new binary" {
  		t.Errorf("new version contents = (%q, %v), want %q", got, err, "new binary")
  	}

  	if err := Rollback(currentLink, prevVersionDir); err != nil {
  		t.Fatalf("Rollback() error = %v", err)
  	}
  	target, err = os.Readlink(currentLink)
  	if err != nil || target != oldVersionDir {
  		t.Errorf("current symlink after rollback = (%q, %v), want %q", target, err, oldVersionDir)
  	}
  }
  ```

  Replace `TestMarker_WriteReadClear` (lines 74-95) with:

  ```go
  func TestMarker_WriteReadClear(t *testing.T) {
  	dir := t.TempDir()

  	if _, _, _, present, err := ReadMarker(dir); err != nil || present {
  		t.Fatalf("ReadMarker() on fresh dir = (_, _, _, %v, %v), want (_, _, _, false, nil)", present, err)
  	}

  	if err := WriteMarker(dir, "0.2.0"); err != nil {
  		t.Fatalf("WriteMarker() error = %v", err)
  	}
  	version, prevVersionDir, swapped, present, err := ReadMarker(dir)
  	if err != nil || !present || version != "0.2.0" || swapped || prevVersionDir != "" {
  		t.Fatalf("ReadMarker() = (%q, %q, %v, %v, %v), want (\"0.2.0\", \"\", false, true, nil) — WriteMarker alone must not report a completed swap or a previous version", version, prevVersionDir, swapped, present, err)
  	}

  	if err := ClearMarker(dir); err != nil {
  		t.Fatalf("ClearMarker() error = %v", err)
  	}
  	if _, _, _, present, _ := ReadMarker(dir); present {
  		t.Error("marker still present after ClearMarker()")
  	}
  }
  ```

  Replace `TestMarker_MarkSwappedTransitionsPhase` (lines 97-119) with:

  ```go
  func TestMarker_MarkSwappedTransitionsPhase(t *testing.T) {
  	dir := t.TempDir()

  	if err := WriteMarker(dir, "0.9.0"); err != nil {
  		t.Fatalf("WriteMarker() error = %v", err)
  	}
  	if _, _, swapped, present, err := ReadMarker(dir); err != nil || !present || swapped {
  		t.Fatalf("ReadMarker() after WriteMarker() = (_, _, %v, %v, %v), want (_, _, false, true, nil)", swapped, present, err)
  	}

  	prevVersionDir := filepath.Join(dir, "versions", "0.8.0")
  	if err := MarkSwapped(dir, "0.9.0", prevVersionDir); err != nil {
  		t.Fatalf("MarkSwapped() error = %v", err)
  	}
  	version, gotPrev, swapped, present, err := ReadMarker(dir)
  	if err != nil || !present || !swapped || version != "0.9.0" || gotPrev != prevVersionDir {
  		t.Fatalf("ReadMarker() after MarkSwapped() = (%q, %q, %v, %v, %v), want (\"0.9.0\", %q, true, true, nil)", version, gotPrev, swapped, present, err, prevVersionDir)
  	}
  }
  ```

  Delete `TestMarker_LegacyBareFormatReadsAsSwapped` (lines 121-146) entirely.

  Leave `TestDownloadAndVerify_RoundTrips`, `TestRollbackReport_WriteReadClear`,
  `TestClearRollbackReport_AbsentIsNotAnError` untouched.

- [ ] **Step 2: Run the update package's tests to confirm the new/changed ones fail against the
  old production code.**

  Run: `cd apps/agent && go test ./internal/update/... -run 'TestSwapAndRollback|TestMarker_WriteReadClear|TestMarker_MarkSwappedTransitionsPhase' -v`
  Expected: FAIL — compile errors (old `Swap`/`Rollback`/`MarkSwapped`/`ReadMarker` signatures
  don't match the new call sites).

- [ ] **Step 3: Rewrite `update.go`'s production code.**

  Delete `preserveModeAndOwnership` entirely (current lines 346-366) and its call site inside
  `Swap`.

  Replace `Swap` (current lines 306-344, the function plus its doc comment) with:

  ```go
  // CurrentLinkPath returns the path of the "current" symlink under stateDir
  // that Swap/Rollback re-point — the middle link in the two-level indirection
  // /usr/local/bin/cb-agent -> {stateDir}/current ->
  // {stateDir}/versions/<version>/cb-agent (see
  // specs/2026-08-05-cb-agent-self-update-fix-design.md). Exported so
  // cmd/cb-agent/main.go builds the same path without duplicating the
  // "current" literal.
  func CurrentLinkPath(stateDir string) string {
  	return filepath.Join(stateDir, "current")
  }

  // versionDir returns the path of a specific version's install directory
  // under stateDir: {stateDir}/versions/<version>/.
  func versionDir(stateDir, version string) string {
  	return filepath.Join(stateDir, "versions", version)
  }

  // atomicSymlink re-points linkPath to target: create a new symlink at a
  // temp name alongside linkPath, then os.Rename it over linkPath — an atomic
  // same-filesystem rename (mirrors atomicWriteFile's temp-then-rename
  // idiom), so a reader (including a process that crashes and restarts) only
  // ever observes linkPath as either its old target or its new one, never
  // briefly absent.
  func atomicSymlink(linkPath, target string) error {
  	dir := filepath.Dir(linkPath)
  	tmp := filepath.Join(dir, fmt.Sprintf(".tmp-%s-%d", filepath.Base(linkPath), time.Now().UnixNano()))
  	if err := os.Symlink(target, tmp); err != nil {
  		return fmt.Errorf("atomic symlink %s: create temp symlink: %w", linkPath, err)
  	}
  	if err := os.Rename(tmp, linkPath); err != nil {
  		os.Remove(tmp)
  		return fmt.Errorf("atomic symlink %s: rename into place: %w", linkPath, err)
  	}
  	fsyncDir(linkPath)
  	return nil
  }

  // resolveSymlinkAbs reads linkPath's target and, if it's relative, resolves
  // it against linkPath's own directory (matching how the kernel resolves a
  // relative symlink target) so callers always get an absolute path back.
  // Returns ("", nil) if linkPath does not exist.
  func resolveSymlinkAbs(linkPath string) (string, error) {
  	target, err := os.Readlink(linkPath)
  	if err != nil {
  		if os.IsNotExist(err) {
  			return "", nil
  		}
  		return "", err
  	}
  	if filepath.IsAbs(target) {
  		return target, nil
  	}
  	return filepath.Join(filepath.Dir(linkPath), target), nil
  }

  // Swap fsyncs newBinaryPath (see fsyncFile), moves it into
  // {stateDir}/versions/<version>/cb-agent (immutable once written), then
  // atomically re-points {stateDir}/current to that new version directory —
  // so self-update never touches anything outside stateDir, which is already
  // writable by the unprivileged cb-agent user running this process (see
  // specs/2026-08-05-cb-agent-self-update-fix-design.md — this replaces the
  // old in-place rename at a root-owned /usr/local/bin/cb-agent, which that
  // user could never actually perform). Returns the version directory
  // current pointed to *before* the swap, so a later Rollback knows where to
  // point back to; empty if current did not exist yet (never happens against
  // a real install, whose install script always creates it — see
  // agent_install.py — but tolerated so tests can exercise a first-ever swap
  // without seeding one).
  func Swap(newBinaryPath, version, stateDir string) (prevVersionDir string, err error) {
  	if err := fsyncFile(newBinaryPath); err != nil {
  		return "", fmt.Errorf("update: sync new binary: %w", err)
  	}

  	newVersionDir := versionDir(stateDir, version)
  	if err := os.MkdirAll(newVersionDir, 0o755); err != nil {
  		return "", fmt.Errorf("update: create version dir %s: %w", newVersionDir, err)
  	}
  	newBinaryTarget := filepath.Join(newVersionDir, "cb-agent")
  	if err := moveFile(newBinaryPath, newBinaryTarget); err != nil {
  		return "", fmt.Errorf("update: install new binary: %w", err)
  	}
  	if err := os.Chmod(newBinaryTarget, 0o755); err != nil {
  		return "", fmt.Errorf("update: chmod new binary: %w", err)
  	}
  	fsyncDir(newBinaryTarget)

  	currentLink := CurrentLinkPath(stateDir)
  	prevVersionDir, err = resolveSymlinkAbs(currentLink)
  	if err != nil {
  		return "", fmt.Errorf("update: read current symlink: %w", err)
  	}

  	if err := atomicSymlink(currentLink, newVersionDir); err != nil {
  		return "", fmt.Errorf("update: re-point current: %w", err)
  	}
  	return prevVersionDir, nil
  }

  // Rollback re-points currentLink back to prevVersionDir — the inverse of
  // Swap, used when a post-update hello.ack never arrives within
  // rollbackWindow (see cmd/cb-agent/main.go's watchForRollback).
  // prevVersionDir must be non-empty (the caller's ReadMarker/Swap call
  // recorded it) — an empty value means there is nothing to roll back to,
  // which is a caller bug, not a recoverable runtime condition.
  func Rollback(currentLink, prevVersionDir string) error {
  	if prevVersionDir == "" {
  		return fmt.Errorf("update: rollback: no previous version recorded")
  	}
  	if err := atomicSymlink(currentLink, prevVersionDir); err != nil {
  		return fmt.Errorf("update: rollback: %w", err)
  	}
  	return nil
  }

  // PruneVersions removes every {stateDir}/versions/<v> directory except
  // currentLink's live target and keepVersionDir (the version an update was
  // just confirmed away from) — called once an update confirms (a
  // post-update hello.ack arrives; see cmd/cb-agent/main.go's onConnected),
  // mirroring the single-".previous"-backup retention the old scheme kept.
  // keepVersionDir may be "" (nothing to additionally retain beyond
  // current). Best-effort: a failure removing one stale version directory is
  // collected and returned, but does not stop pruning from attempting the
  // rest.
  func PruneVersions(stateDir, currentLink, keepVersionDir string) error {
  	live, err := resolveSymlinkAbs(currentLink)
  	if err != nil {
  		return fmt.Errorf("update: prune versions: read current symlink: %w", err)
  	}

  	versionsRoot := filepath.Join(stateDir, "versions")
  	entries, err := os.ReadDir(versionsRoot)
  	if err != nil {
  		if os.IsNotExist(err) {
  			return nil
  		}
  		return fmt.Errorf("update: prune versions: read %s: %w", versionsRoot, err)
  	}

  	var errs []error
  	for _, entry := range entries {
  		dir := filepath.Join(versionsRoot, entry.Name())
  		if dir == live || dir == keepVersionDir {
  			continue
  		}
  		if err := os.RemoveAll(dir); err != nil {
  			errs = append(errs, fmt.Errorf("remove %s: %w", dir, err))
  		}
  	}
  	if len(errs) > 0 {
  		return fmt.Errorf("update: prune versions: %d failure(s): %w", len(errs), errors.Join(errs...))
  	}
  	return nil
  }
  ```

  Add `"errors"` to `update.go`'s import block (it currently imports `crypto/sha256`,
  `crypto/subtle`, `encoding/hex`, `fmt`, `io`, `net/http`, `os`, `path/filepath`, `strings`,
  `syscall`, `time`, plus the two internal packages — `errors` is new, `time` is already present).

  Replace `WriteMarker`/`MarkSwapped`/`writeMarkerPhase` (current lines 376-425) with:

  ```go
  // WriteMarker durably records that targetVersion is pending confirmation via
  // atomicWriteFile — a torn write here would be worse than useless, since the
  // whole point of the marker is that it's trustworthy after an unplanned
  // restart. Callers (cmd/cb-agent/main.go's onUpdate) must call this *before*
  // executing the binary swap it guards, not after: if a crash lands between
  // WriteMarker and Swap, the marker still correctly names the version that
  // was *about to be* installed, and ReadMarker on restart finds a
  // consistent, recoverable state (Swap never ran, so current is untouched —
  // there's nothing to roll back).
  //
  // The marker written here starts in phasePendingSwap with no previous
  // version recorded yet (Swap hasn't run, so there's nothing to record) —
  // see MarkSwapped, which callers must invoke once Swap actually succeeds.
  func WriteMarker(stateDir, targetVersion string) error {
  	return writeMarkerPhase(stateDir, phasePendingSwap, targetVersion, "")
  }

  // MarkSwapped durably transitions an already-written marker from
  // phasePendingSwap to phasePendingConfirm, recording prevVersionDir (Swap's
  // return value) so a later Rollback or PruneVersions knows which version
  // directory to act on. Callers (cmd/cb-agent/main.go's onUpdate) must call
  // this immediately after Swap returns successfully, before re-exec.
  //
  // If this write itself fails, the swap has already durably happened and
  // cannot be undone from here; the marker is simply left in
  // phasePendingSwap, which forfeits this update's rollback safety net (a
  // restart before confirmation will treat it as abandoned) but is not a
  // correctness violation — callers should log the failure and proceed
  // rather than failing the update outright.
  func MarkSwapped(stateDir, targetVersion, prevVersionDir string) error {
  	return writeMarkerPhase(stateDir, phasePendingConfirm, targetVersion, prevVersionDir)
  }

  // writeMarkerPhase encodes phase, targetVersion, and prevVersionDir into the
  // marker file as "<phase>\n<targetVersion>\n<prevVersionDir>" and writes it
  // via atomicWriteFile. prevVersionDir is "" for phasePendingSwap.
  func writeMarkerPhase(stateDir string, phase markerPhase, targetVersion, prevVersionDir string) error {
  	data := []byte(string(phase) + "\n" + targetVersion + "\n" + prevVersionDir)
  	if err := atomicWriteFile(filepath.Join(stateDir, markerFilename), data, 0o600); err != nil {
  		return fmt.Errorf("update: write marker: %w", err)
  	}
  	return nil
  }
  ```

  Replace `ReadMarker` (current lines 427-466, including its doc comment) with:

  ```go
  // ReadMarker reads back a marker written by WriteMarker/MarkSwapped.
  // version is the target version the marker names; prevVersionDir is the
  // version directory current pointed to before this update's Swap ran,
  // meaningful only when swapped == true — it's Rollback's second argument.
  // swapped reports whether Swap has durably completed for that version
  // (i.e. the marker is in phasePendingConfirm, written by MarkSwapped) —
  // callers must treat swapped == false as "nothing to roll back". present is
  // false with a nil error when no marker exists at all.
  func ReadMarker(stateDir string) (version, prevVersionDir string, swapped, present bool, err error) {
  	data, err := os.ReadFile(filepath.Join(stateDir, markerFilename))
  	if os.IsNotExist(err) {
  		return "", "", false, false, nil
  	}
  	if err != nil {
  		return "", "", false, false, fmt.Errorf("update: read marker: %w", err)
  	}
  	phase, rest, ok := strings.Cut(string(data), "\n")
  	if !ok {
  		return "", "", false, false, fmt.Errorf("update: malformed marker: missing phase separator")
  	}
  	version, prevVersionDir, _ = strings.Cut(rest, "\n")
  	return version, prevVersionDir, markerPhase(phase) == phasePendingConfirm, true, nil
  }
  ```

  `ClearMarker`, `Download`, `VerifySHA256`, `constantTimeEqualHexFold`, `moveFile`, `fsyncFile`,
  `fsyncDir`, `atomicWriteFile`, `WriteRollbackReport`, `ReadRollbackReport`,
  `ClearRollbackReport` are unchanged. `markerPhase`'s own doc comment (current lines 30-58)
  references the old ".previous" mechanics in its historical explanation — leave the type and its
  comment as-is; it documents *why* the two-phase scheme exists, which still holds.

- [ ] **Step 4: Run the update package's tests to confirm the rewritten ones pass.**

  Run: `cd apps/agent && go build ./... && go test ./internal/update/... -v`
  Expected: PASS for every test (the ones touched in Step 1, plus `update_durability_test.go`'s
  tests, which Step 5 below rewrites — run this again after Step 5 too).

- [ ] **Step 5: Rewrite `update_durability_test.go`.**

  Replace `TestSwap_PreservesTargetModeAcrossSwap` (lines 11-39) — mode preservation no longer
  applies (every version is installed fresh at a fixed mode, never renamed over an existing file) —
  with:

  ```go
  // TestSwap_NewVersionAlwaysInstalledAt0755 covers the "fixed 0755, no mode
  // preservation" property that replaces the old preserveModeAndOwnership
  // step (specs/2026-08-05-cb-agent-self-update-fix-design.md): every version
  // directory and binary is created directly by cb-agent, as cb-agent, at a
  // fixed mode — there is no "restore the original owner/mode" step because
  // nothing is ever renamed over an existing root-owned file anymore.
  func TestSwap_NewVersionAlwaysInstalledAt0755(t *testing.T) {
  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
  	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(oldVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	newBinary := filepath.Join(dir, "new-download")
  	// Deliberately a narrower mode than 0755 — Swap must still land the
  	// installed copy at 0755, not preserve this.
  	if err := os.WriteFile(newBinary, []byte("new binary"), 0o700); err != nil {
  		t.Fatal(err)
  	}

  	if _, err := Swap(newBinary, "0.2.0", dir); err != nil {
  		t.Fatalf("Swap() error = %v", err)
  	}

  	info, err := os.Stat(filepath.Join(dir, "versions", "0.2.0", "cb-agent"))
  	if err != nil {
  		t.Fatalf("stat new version binary: %v", err)
  	}
  	if got := info.Mode().Perm(); got != 0o755 {
  		t.Errorf("new version binary mode = %04o, want 0755", got)
  	}
  }
  ```

  Replace `TestSwap_SyncFailureLeavesTargetUntouched` (lines 41-67) with:

  ```go
  // TestSwap_SyncFailureLeavesTargetUntouched covers "sync the downloaded file
  // before replacement": Swap fsyncs newBinaryPath before it does anything at
  // all to current or the versions directory, so a failure syncing the new
  // binary must never leave a half-applied swap.
  func TestSwap_SyncFailureLeavesTargetUntouched(t *testing.T) {
  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.1.0")
  	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(oldVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	missingNewBinary := filepath.Join(dir, "does-not-exist")

  	if _, err := Swap(missingNewBinary, "0.2.0", dir); err == nil {
  		t.Fatal("Swap() error = nil, want an error when the new binary can't be opened/synced")
  	}

  	target, err := os.Readlink(currentLink)
  	if err != nil || target != oldVersionDir {
  		t.Errorf("current symlink = (%q, %v), want unchanged %q", target, err, oldVersionDir)
  	}
  	if _, err := os.Stat(filepath.Join(dir, "versions", "0.2.0")); !os.IsNotExist(err) {
  		t.Error("new version dir created despite a failed sync, want none")
  	}
  }
  ```

  In `TestWriteMarker_OverwritesExistingMarkerAtomically` (lines 92-110), update the `ReadMarker`
  call from `version, _, present, err := ReadMarker(dir)` to
  `version, _, _, present, err := ReadMarker(dir)` (leave the rest of the test unchanged; the
  assertion still checks `version == "0.2.0"`).

  `TestWriteMarker_LeavesNoStrayTempFiles` (lines 69-90) is unchanged — the marker file's name and
  the atomic-write mechanism didn't change, only its contents' shape.

  Replace `TestMarkerWrittenBeforeSwap_SurvivesSimulatedCrashBeforeReplacement` (lines 112-147)
  with:

  ```go
  func TestMarkerWrittenBeforeSwap_SurvivesSimulatedCrashBeforeReplacement(t *testing.T) {
  	dir := t.TempDir()
  	versionDir := filepath.Join(dir, "versions", "0.1.0")
  	if err := os.MkdirAll(versionDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(versionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(versionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}

  	if err := WriteMarker(dir, "0.3.0"); err != nil {
  		t.Fatalf("WriteMarker() error = %v", err)
  	}
  	// Simulated crash: Swap is deliberately never called.

  	version, prevVersionDir, swapped, present, err := ReadMarker(dir)
  	if err != nil || !present || version != "0.3.0" {
  		t.Fatalf("ReadMarker() after simulated crash = (%q, _, _, %v, %v), want (\"0.3.0\", _, _, true, nil) — recoverable state", version, present, err)
  	}
  	if swapped {
  		t.Error("ReadMarker() reports swapped = true, want false — Swap was never called, there is nothing to roll back to")
  	}
  	if prevVersionDir != "" {
  		t.Errorf("ReadMarker() prevVersionDir = %q, want empty — Swap never ran, nothing was recorded", prevVersionDir)
  	}

  	target, err := os.Readlink(currentLink)
  	if err != nil || target != versionDir {
  		t.Errorf("current symlink after simulated crash = (%q, %v), want unchanged %q", target, err, versionDir)
  	}
  }
  ```

  Replace `TestUpdateThenCrashBeforeRestart_MarkerAndBackupRecoverable` (lines 149-201) with:

  ```go
  func TestUpdateThenCrashBeforeRestart_MarkerAndBackupRecoverable(t *testing.T) {
  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.3.0")
  	if err := os.MkdirAll(oldVersionDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(oldVersionDir, "cb-agent"), []byte("old binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(oldVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	newBinary := filepath.Join(dir, "new-download")
  	if err := os.WriteFile(newBinary, []byte("new binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}

  	if err := WriteMarker(dir, "0.4.0"); err != nil {
  		t.Fatalf("WriteMarker() error = %v", err)
  	}
  	prevVersionDir, err := Swap(newBinary, "0.4.0", dir)
  	if err != nil {
  		t.Fatalf("Swap() error = %v", err)
  	}
  	if err := MarkSwapped(dir, "0.4.0", prevVersionDir); err != nil {
  		t.Fatalf("MarkSwapped() error = %v", err)
  	}
  	// Simulated crash: no re-exec, no hello.ack, nothing else runs.

  	version, gotPrev, swapped, present, err := ReadMarker(dir)
  	if err != nil || !present || version != "0.4.0" || !swapped || gotPrev != oldVersionDir {
  		t.Fatalf("ReadMarker() after simulated crash = (%q, %q, %v, %v, %v), want (\"0.4.0\", %q, true, true, nil)", version, gotPrev, swapped, present, err, oldVersionDir)
  	}
  	newVersionDir := filepath.Join(dir, "versions", "0.4.0")
  	target, err := os.Readlink(currentLink)
  	if err != nil || target != newVersionDir {
  		t.Errorf("current symlink = (%q, %v), want %q — the swap itself completed durably", target, err, newVersionDir)
  	}

  	// A fresh process's rollback timer can act on this recovered state
  	// either way: Rollback if hello.ack never confirms in time.
  	if err := Rollback(currentLink, gotPrev); err != nil {
  		t.Fatalf("Rollback() error = %v", err)
  	}
  	target, err = os.Readlink(currentLink)
  	if err != nil || target != oldVersionDir {
  		t.Errorf("current symlink after recovered rollback = (%q, %v), want %q", target, err, oldVersionDir)
  	}
  }
  ```

  `TestMoveFile_CrossDeviceCopyFallbackSyncsDestination` (lines 203-271) is unchanged — it tests
  `moveFile` directly and doesn't touch `Swap`/`Rollback`/the marker.

  Append two new tests covering `PruneVersions` at the end of the file:

  ```go
  // TestPruneVersions_KeepsCurrentAndNamedVersionRemovesRest covers the
  // retention rule Section 5 of specs/2026-08-05-cb-agent-self-update-fix-
  // design.md specifies: after an update confirms, only current's target and
  // the version just confirmed-away-from survive.
  func TestPruneVersions_KeepsCurrentAndNamedVersionRemovesRest(t *testing.T) {
  	dir := t.TempDir()
  	for _, v := range []string{"0.1.0", "0.2.0", "0.3.0"} {
  		if err := os.MkdirAll(filepath.Join(dir, "versions", v), 0o755); err != nil {
  			t.Fatal(err)
  		}
  	}
  	currentDir := filepath.Join(dir, "versions", "0.3.0")
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(currentDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	keepDir := filepath.Join(dir, "versions", "0.2.0")

  	if err := PruneVersions(dir, currentLink, keepDir); err != nil {
  		t.Fatalf("PruneVersions() error = %v", err)
  	}

  	for _, want := range []string{currentDir, keepDir} {
  		if _, err := os.Stat(want); err != nil {
  			t.Errorf("stat %s after PruneVersions() = %v, want it retained", want, err)
  		}
  	}
  	pruned := filepath.Join(dir, "versions", "0.1.0")
  	if _, err := os.Stat(pruned); !os.IsNotExist(err) {
  		t.Errorf("stat %s after PruneVersions() = %v, want removed", pruned, err)
  	}
  }

  // TestPruneVersions_EmptyKeepStillRetainsCurrent covers the first-ever-
  // update case: keepVersionDir is "" (no marker was present — see
  // cmd/cb-agent/main.go's onConnected), but current's own target must never
  // be pruned.
  func TestPruneVersions_EmptyKeepStillRetainsCurrent(t *testing.T) {
  	dir := t.TempDir()
  	currentDir := filepath.Join(dir, "versions", "0.1.0")
  	if err := os.MkdirAll(currentDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	staleDir := filepath.Join(dir, "versions", "0.0.9")
  	if err := os.MkdirAll(staleDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := CurrentLinkPath(dir)
  	if err := os.Symlink(currentDir, currentLink); err != nil {
  		t.Fatal(err)
  	}

  	if err := PruneVersions(dir, currentLink, ""); err != nil {
  		t.Fatalf("PruneVersions() error = %v", err)
  	}

  	if _, err := os.Stat(currentDir); err != nil {
  		t.Errorf("stat current dir after PruneVersions() = %v, want retained", err)
  	}
  	if _, err := os.Stat(staleDir); !os.IsNotExist(err) {
  		t.Errorf("stat stale dir after PruneVersions() = %v, want removed", err)
  	}
  }
  ```

- [ ] **Step 6: Run the full `internal/update` package test suite.**

  Run: `cd apps/agent && go build ./... && go vet ./... && go test ./internal/update/... -v`
  Expected: PASS, all tests, no build or vet errors.

- [ ] **Step 7: Commit.**

  ```bash
  git add apps/agent/internal/update/
  git commit -m "fix(agents/update): symlink-indirection Swap/Rollback so self-update never touches root-owned paths (Bug 1)"
  ```

---

## Task 2: `cmd/cb-agent/main.go` orchestration — currentLink, fixed re-exec target, uninstall fix

**Depends on:** Task 1 (consumes `update.CurrentLinkPath`, `update.Swap`'s new signature, etc.).

**Current state:** `runDaemon` resolves `binaryPath, err := os.Executable()` once and threads it
through `watchForRollback`'s dispatch, `onUpdate`'s `Swap`/re-exec calls, and (indirectly, via a
separate `resolveUninstallPaths` call inside `runUninstall`) uninstall's binary-removal path.
`watchForRollback` and `onUpdate` call the old 2-arg `Swap`/`Rollback` and the old
4-return `ReadMarker`/3-arg... (2-arg) `MarkSwapped`. `uninstallPaths` has a `previousBinary`
field derived from `resolveUninstallPaths`'s `os.Executable()` result.

**Files:**
- Modify: `apps/agent/cmd/cb-agent/main.go`
- Modify: `apps/agent/cmd/cb-agent/main_test.go`

**Interfaces consumed (from Task 1):** `update.CurrentLinkPath`, `update.Swap(newBinaryPath,
version, stateDir)`, `update.Rollback(currentLink, prevVersionDir)`,
`update.ReadMarker(stateDir) (version, prevVersionDir string, swapped, present bool, err error)`,
`update.MarkSwapped(stateDir, targetVersion, prevVersionDir)`, `update.PruneVersions(stateDir,
currentLink, keepVersionDir)`.

- [ ] **Step 1: Update `main_test.go`'s watchForRollback and uninstall-path tests first (they'll
  fail to compile against the still-unmodified `main.go`, which is expected at this point).**

  Replace `TestWatchForRollback_NoConfirmationTriggersRollback` (lines 465-510) with:

  ```go
  func TestWatchForRollback_NoConfirmationTriggersRollback(t *testing.T) {
  	orig := rollbackWindow
  	rollbackWindow = 30 * time.Millisecond
  	defer func() { rollbackWindow = orig }()

  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.5.0")
  	newVersionDir := filepath.Join(dir, "versions", "0.6.0")
  	for _, d := range []string{oldVersionDir, newVersionDir} {
  		if err := os.MkdirAll(d, 0o755); err != nil {
  			t.Fatal(err)
  		}
  	}
  	if err := os.WriteFile(filepath.Join(newVersionDir, "cb-agent"), []byte("new binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := update.CurrentLinkPath(dir)
  	if err := os.Symlink(newVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	// MarkSwapped (not the plain WriteMarker) — this test simulates a
  	// restart *after* update.Swap actually completed, i.e. the marker is in
  	// its phasePendingConfirm phase and prevVersionDir genuinely names
  	// this update's own backup. See
  	// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup for
  	// the phasePendingSwap (Swap never ran) case this must be told apart
  	// from.
  	if err := update.MarkSwapped(dir, "0.6.0", oldVersionDir); err != nil {
  		t.Fatalf("MarkSwapped() error = %v", err)
  	}

  	reExecCalls := 0
  	reExec := func() error {
  		reExecCalls++
  		return nil
  	}

  	watchForRollback(dir, currentLink, "0.6.0", reExec)

  	target, err := os.Readlink(currentLink)
  	if err != nil || target != oldVersionDir {
  		t.Errorf("current symlink = (%q, %v), want rolled back to %q", target, err, oldVersionDir)
  	}
  	if _, _, _, present, _ := update.ReadMarker(dir); present {
  		t.Error("marker still present after rollback, want cleared")
  	}
  	version, present, err := update.ReadRollbackReport(dir)
  	if err != nil || !present || version != "0.6.0" {
  		t.Errorf("ReadRollbackReport() = (%q, %v, %v), want (\"0.6.0\", true, nil) — the fresh process re-exec'd below needs this to report update.status(rolled_back)", version, present, err)
  	}
  	if reExecCalls != 1 {
  		t.Errorf("reExec called %d times, want exactly 1", reExecCalls)
  	}
  }
  ```

  Replace `TestWatchForRollback_ConfirmedWithinWindowRetainsNewBinary` (lines 518-572) with:

  ```go
  func TestWatchForRollback_ConfirmedWithinWindowRetainsNewBinary(t *testing.T) {
  	orig := rollbackWindow
  	rollbackWindow = 150 * time.Millisecond
  	defer func() { rollbackWindow = orig }()

  	dir := t.TempDir()
  	oldVersionDir := filepath.Join(dir, "versions", "0.6.0")
  	newVersionDir := filepath.Join(dir, "versions", "0.7.0")
  	for _, d := range []string{oldVersionDir, newVersionDir} {
  		if err := os.MkdirAll(d, 0o755); err != nil {
  			t.Fatal(err)
  		}
  	}
  	if err := os.WriteFile(filepath.Join(newVersionDir, "cb-agent"), []byte("new binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := update.CurrentLinkPath(dir)
  	if err := os.Symlink(newVersionDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	if err := update.MarkSwapped(dir, "0.7.0", oldVersionDir); err != nil {
  		t.Fatalf("MarkSwapped() error = %v", err)
  	}

  	confirmed := make(chan struct{})
  	go func() {
  		// Well inside the 150ms window — simulates onConnected firing from
  		// an accepted hello.ack shortly after the daemon reconnects.
  		time.Sleep(20 * time.Millisecond)
  		if err := update.ClearMarker(dir); err != nil {
  			t.Errorf("ClearMarker() error = %v", err)
  		}
  		close(confirmed)
  	}()

  	reExecCalls := 0
  	reExec := func() error {
  		reExecCalls++
  		return nil
  	}

  	watchForRollback(dir, currentLink, "0.7.0", reExec)
  	<-confirmed

  	target, err := os.Readlink(currentLink)
  	if err != nil || target != newVersionDir {
  		t.Errorf("current symlink = (%q, %v), want unchanged %q — a confirmed update must not be rolled back", target, err, newVersionDir)
  	}
  	if _, _, _, present, _ := update.ReadMarker(dir); present {
  		t.Error("marker still present, want cleared by the simulated onConnected confirmation")
  	}
  	if _, present, _ := update.ReadRollbackReport(dir); present {
  		t.Error("rollback report present, want none — the update confirmed, no rollback happened")
  	}
  	if reExecCalls != 0 {
  		t.Errorf("reExec called %d times, want 0 (a confirmed update must not re-exec)", reExecCalls)
  	}
  }
  ```

  Replace `TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup` (lines 600-647) with:

  ```go
  func TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup(t *testing.T) {
  	orig := rollbackWindow
  	rollbackWindow = 30 * time.Millisecond
  	defer func() { rollbackWindow = orig }()

  	dir := t.TempDir()
  	// v1Dir is the healthy, currently-running version from an earlier
  	// v0->v1 update that already completed and confirmed (and so, per
  	// PruneVersions, has no stale v0 directory left lying around).
  	v1Dir := filepath.Join(dir, "versions", "1.0.0")
  	if err := os.MkdirAll(v1Dir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(v1Dir, "cb-agent"), []byte("v1 binary (healthy, running)"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := update.CurrentLinkPath(dir)
  	if err := os.Symlink(v1Dir, currentLink); err != nil {
  		t.Fatal(err)
  	}

  	// Reproduces the crash: a v2 update instruction's WriteMarker succeeded,
  	// but the process died before update.Swap ever ran (main.go's onUpdate
  	// calls these in that order). The marker therefore names "2.0.0" but
  	// carries phasePendingSwap, not phasePendingConfirm, and no
  	// prevVersionDir.
  	if err := update.WriteMarker(dir, "2.0.0"); err != nil {
  		t.Fatalf("WriteMarker() error = %v", err)
  	}

  	reExecCalls := 0
  	reExec := func() error {
  		reExecCalls++
  		return nil
  	}

  	watchForRollback(dir, currentLink, "2.0.0", reExec)

  	target, err := os.Readlink(currentLink)
  	if err != nil || target != v1Dir {
  		t.Errorf("current symlink = (%q, %v), want unchanged %q — the healthy running v1 must never be silently replaced", target, err, v1Dir)
  	}
  	if _, _, _, present, _ := update.ReadMarker(dir); present {
  		t.Error("marker still present after an abandoned (pre-swap) update attempt, want cleared")
  	}
  	if _, present, _ := update.ReadRollbackReport(dir); present {
  		t.Error("rollback report present, want none — nothing was rolled back, so there is nothing to report")
  	}
  	if reExecCalls != 0 {
  		t.Errorf("reExec called %d times, want 0 — an abandoned pre-swap attempt must never re-exec", reExecCalls)
  	}
  }
  ```

  Replace `TestWatchForRollback_FailedRollbackStillClearsMarker` (lines 667-700) with:

  ```go
  func TestWatchForRollback_FailedRollbackStillClearsMarker(t *testing.T) {
  	orig := rollbackWindow
  	rollbackWindow = 30 * time.Millisecond
  	defer func() { rollbackWindow = orig }()

  	dir := t.TempDir()
  	currentDir := filepath.Join(dir, "versions", "0.8.0")
  	if err := os.MkdirAll(currentDir, 0o755); err != nil {
  		t.Fatal(err)
  	}
  	if err := os.WriteFile(filepath.Join(currentDir, "cb-agent"), []byte("current binary"), 0o755); err != nil {
  		t.Fatal(err)
  	}
  	currentLink := update.CurrentLinkPath(dir)
  	if err := os.Symlink(currentDir, currentLink); err != nil {
  		t.Fatal(err)
  	}
  	// Deliberately no prevVersionDir recorded — Rollback must fail.
  	if err := update.MarkSwapped(dir, "0.8.0", ""); err != nil {
  		t.Fatalf("MarkSwapped() error = %v", err)
  	}

  	reExecCalls := 0
  	reExec := func() error {
  		reExecCalls++
  		return nil
  	}

  	watchForRollback(dir, currentLink, "0.8.0", reExec)

  	if _, _, _, present, _ := update.ReadMarker(dir); present {
  		t.Error("marker still present after a failed Rollback, want cleared to avoid a permanently stuck retry loop")
  	}
  	target, err := os.Readlink(currentLink)
  	if err != nil || target != currentDir {
  		t.Errorf("current symlink = (%q, %v), want unchanged %q — a failed rollback must not partially mutate current", target, err, currentDir)
  	}
  	if reExecCalls != 0 {
  		t.Errorf("reExec called %d times, want 0 — a failed rollback must not re-exec into whatever partial state resulted", reExecCalls)
  	}
  }
  ```

  In `seedUninstallFootprint` (lines 757-799), remove the `previousBinary` file creation (the
  `previousBinary := binary + ".previous"` line and its `os.WriteFile` block) and remove
  `previousBinary: previousBinary,` from the returned `uninstallPaths{...}` literal.

  In `TestPerformUninstall_RemovesExpectedPathsAndReloadsSystemd` (line 826),
  `TestPerformUninstall_SystemctlDisableFailureDoesNotBlockFileRemoval` (line 984), and
  `TestPerformUninstall_SystemctlReloadFailureStillReportsRemoval` (line 1009), change
  `wantRemoved := []string{paths.unitFile, paths.binary, paths.previousBinary, paths.configFile, paths.stateDir, paths.configDir}`
  to
  `wantRemoved := []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir, paths.configDir}`
  in all three places.

  Delete `TestPerformUninstall_RemovesPreviousBinaryBackup` (lines 898-933) entirely — the
  `.previous` backup concept no longer exists; every versioned binary lives under `stateDir`,
  already covered by `stateDir`'s own wholesale removal.

  In `TestPerformUninstall_MissingPathsSkippedWithoutError` (lines 939-962), remove
  `previousBinary: filepath.Join(root, "does-not-exist", "cb-agent.previous"),` from the
  `uninstallPaths{...}` literal.

  Replace `TestResolveUninstallPaths_UsesRunningBinaryPathNotHardcodedLiteral` (lines 1021-1054)
  with:

  ```go
  // TestResolveUninstallPaths_PinsToInstalledBinaryPath is the regression
  // test for the self-update-fix design gap: resolveUninstallPaths must
  // always target the fixed /usr/local/bin/cb-agent entry point, not
  // os.Executable()'s resolved (symlink-followed) result. Under the
  // versioned-symlink layout (specs/2026-08-05-cb-agent-self-update-fix-
  // design.md), os.Executable() resolves straight through to whatever
  // {stateDir}/versions/<v>/cb-agent happens to be running, which would
  // leave the actual root-owned /usr/local/bin/cb-agent symlink behind after
  // an otherwise-complete uninstall.
  func TestResolveUninstallPaths_PinsToInstalledBinaryPath(t *testing.T) {
  	paths := resolveUninstallPaths()

  	if paths.binary != installedBinaryPath {
  		t.Errorf("resolveUninstallPaths().binary = %q, want the fixed %q", paths.binary, installedBinaryPath)
  	}
  	if paths.unitFile != defaultUninstallPaths.unitFile {
  		t.Errorf("resolveUninstallPaths().unitFile = %q, want %q", paths.unitFile, defaultUninstallPaths.unitFile)
  	}
  	if paths.configFile != defaultUninstallPaths.configFile {
  		t.Errorf("resolveUninstallPaths().configFile = %q, want %q", paths.configFile, defaultUninstallPaths.configFile)
  	}
  	if paths.configDir != defaultUninstallPaths.configDir {
  		t.Errorf("resolveUninstallPaths().configDir = %q, want %q", paths.configDir, defaultUninstallPaths.configDir)
  	}
  	if paths.stateDir != defaultUninstallPaths.stateDir {
  		t.Errorf("resolveUninstallPaths().stateDir = %q, want %q", paths.stateDir, defaultUninstallPaths.stateDir)
  	}
  }
  ```

- [ ] **Step 2: Run `main_test.go` to confirm it now fails to compile against the still-unmodified
  `main.go` (old signatures) — this is the expected failing state before Step 3.**

  Run: `cd apps/agent && go vet ./cmd/cb-agent/...`
  Expected: FAIL — compile errors referencing the old `update.Swap`/`update.MarkSwapped`/
  `update.ReadMarker` signatures and the removed `previousBinary` field.

- [ ] **Step 3: Update `main.go`'s production code.**

  Add a new const near the top of the file, after the `rollbackWindow` var doc comment block
  (after line 38, before `watchForRollback`'s doc comment):

  ```go
  // installedBinaryPath is the stable, root-owned symlink systemd's
  // ExecStart and an operator's interactive shell use
  // (/etc/systemd/system/cb-agent.service, agent_install.py's install
  // script) — see specs/2026-08-05-cb-agent-self-update-fix-design.md.
  // Self-update never touches this path directly; it only ever re-points
  // {stateDir}/current, the middle symlink this one points through.
  const installedBinaryPath = "/usr/local/bin/cb-agent"
  ```

  In `watchForRollback` (lines 64-116), rename the second parameter from `binaryPath` to
  `currentLink` throughout the signature and body, and update its two internal calls:

  - `v, swapped, stillPresent, err := update.ReadMarker(stateDir)` becomes
    `v, prevVersionDir, swapped, stillPresent, err := update.ReadMarker(stateDir)`
  - `if err := update.Rollback(binaryPath); err != nil {` becomes
    `if err := update.Rollback(currentLink, prevVersionDir); err != nil {`

  In `runDaemon`, replace the `binaryPath` resolution and the `watchForRollback` dispatch (current
  lines 198-217):

  ```go
  	binaryPath, err := os.Executable()
  	if err != nil {
  		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
  		os.Exit(1)
  	}

  	// swapped (whether Swap actually completed for this marker — see
  	// update.ReadMarker) is deliberately not consulted here to decide
  	// whether to spawn watchForRollback at all: it's still spawned either
  	// way, and watchForRollback itself makes that determination after its
  	// own ReadMarker call once rollbackWindow elapses. Keeping the decision
  	// in one place (rather than duplicating it here as a fast-path) is what
  	// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup
  	// exercises directly.
  	if pendingVersion, _, present, _ := update.ReadMarker(config.StateDir()); present {
  		log.Printf("cb-agent: resuming after update to %s — watching for a successful link", pendingVersion)
  		go watchForRollback(config.StateDir(), binaryPath, pendingVersion, func() error {
  			return syscall.Exec(binaryPath, os.Args, os.Environ())
  		})
  	}
  ```

  with:

  ```go
  	currentLink := update.CurrentLinkPath(config.StateDir())

  	// swapped (whether Swap actually completed for this marker — see
  	// update.ReadMarker) is deliberately not consulted here to decide
  	// whether to spawn watchForRollback at all: it's still spawned either
  	// way, and watchForRollback itself makes that determination after its
  	// own ReadMarker call once rollbackWindow elapses. Keeping the decision
  	// in one place (rather than duplicating it here as a fast-path) is what
  	// TestWatchForRollback_CrashBeforeSwapDoesNotRollBackToStaleBackup
  	// exercises directly.
  	if pendingVersion, _, _, present, _ := update.ReadMarker(config.StateDir()); present {
  		log.Printf("cb-agent: resuming after update to %s — watching for a successful link", pendingVersion)
  		go watchForRollback(config.StateDir(), currentLink, pendingVersion, func() error {
  			return syscall.Exec(installedBinaryPath, os.Args, os.Environ())
  		})
  	}
  ```

  Replace `onConnected` (current lines 219-227):

  ```go
  	var confirmOnce sync.Once
  	onConnected := func() {
  		confirmOnce.Do(func() {
  			update.ClearMarker(config.StateDir())
  		})
  		if err := statusWriter.SetAccepted(); err != nil {
  			log.Printf("cb-agent: status: %v", err)
  		}
  	}
  ```

  with:

  ```go
  	var confirmOnce sync.Once
  	onConnected := func() {
  		confirmOnce.Do(func() {
  			_, prevVersionDir, _, present, err := update.ReadMarker(config.StateDir())
  			if err != nil {
  				log.Printf("cb-agent: %v", err)
  			}
  			if err := update.ClearMarker(config.StateDir()); err != nil {
  				log.Printf("cb-agent: %v", err)
  			}
  			if present {
  				// The confirmed update's marker is gone — prune every
  				// stale version directory except the one still live and
  				// the one just confirmed away from, mirroring the old
  				// scheme's single-".previous"-backup retention (Section 5,
  				// specs/2026-08-05-cb-agent-self-update-fix-design.md).
  				if err := update.PruneVersions(config.StateDir(), currentLink, prevVersionDir); err != nil {
  					log.Printf("cb-agent: %v", err)
  				}
  			}
  		})
  		if err := statusWriter.SetAccepted(); err != nil {
  			log.Printf("cb-agent: status: %v", err)
  		}
  	}
  ```

  In `onUpdate` (current lines 251-322), replace the `WriteMarker`-through-`return
  syscall.Exec(...)` block:

  ```go
  		if err := update.WriteMarker(config.StateDir(), instr.Version); err != nil {
  			os.Remove(tmpPath)
  			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
  				log.Printf("cb-agent: send failed update.status: %v", sendErr)
  			}
  			return err
  		}
  		if _, err := update.Swap(tmpPath, binaryPath); err != nil {
  			// The swap never happened — clear the marker rather than
  			// leaving a stale one that would (harmlessly, but pointlessly)
  			// send a future restart into a rollback attempt against a
  			// backup that was never created.
  			if clearErr := update.ClearMarker(config.StateDir()); clearErr != nil {
  				log.Printf("cb-agent: %v", clearErr)
  			}
  			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
  				log.Printf("cb-agent: send failed update.status: %v", sendErr)
  			}
  			return err
  		}
  		// Swap succeeded — durably transition the marker from
  		// phasePendingSwap to phasePendingConfirm (see
  		// update.MarkSwapped's doc comment) so a restart's watchForRollback
  		// can trust that targetPath+".previous" is genuinely this update's
  		// backup, not a stale one from some earlier, already-confirmed
  		// update. The swap itself has already happened and can't be undone
  		// from here, so a failure here is logged, not treated as a failed
  		// update: it only costs this particular update its rollback safety
  		// net (see MarkSwapped's doc comment), not correctness.
  		if err := update.MarkSwapped(config.StateDir(), instr.Version); err != nil {
  			log.Printf("cb-agent: %v — update to %s already installed but will not be protected by the rollback window", err, instr.Version)
  		}
  		// Reported now, immediately before re-exec: a successful re-exec
  		// replaces this process's image and never returns here, so
  		// "succeeded" can't instead be sent by link.go after OnUpdate
  		// returns (see SendUpdateStatus's doc comment).
  		if err := send(instr.Version, "succeeded", ""); err != nil {
  			log.Printf("cb-agent: send succeeded update.status: %v", err)
  		}
  		log.Printf("cb-agent: updated to %s — re-executing", instr.Version)
  		return syscall.Exec(binaryPath, os.Args, os.Environ())
  ```

  with:

  ```go
  		if err := update.WriteMarker(config.StateDir(), instr.Version); err != nil {
  			os.Remove(tmpPath)
  			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
  				log.Printf("cb-agent: send failed update.status: %v", sendErr)
  			}
  			return err
  		}
  		prevVersionDir, err := update.Swap(tmpPath, instr.Version, config.StateDir())
  		if err != nil {
  			// The swap never happened — clear the marker rather than
  			// leaving a stale one that would (harmlessly, but pointlessly)
  			// send a future restart into a rollback attempt against a
  			// version that was never installed.
  			if clearErr := update.ClearMarker(config.StateDir()); clearErr != nil {
  				log.Printf("cb-agent: %v", clearErr)
  			}
  			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
  				log.Printf("cb-agent: send failed update.status: %v", sendErr)
  			}
  			return err
  		}
  		// Swap succeeded — durably transition the marker from
  		// phasePendingSwap to phasePendingConfirm and record prevVersionDir
  		// (see update.MarkSwapped's doc comment) so a restart's
  		// watchForRollback can trust which version directory is genuinely
  		// this update's own backup, not a stale one from some earlier,
  		// already-confirmed update. The swap itself has already happened
  		// and can't be undone from here, so a failure here is logged, not
  		// treated as a failed update: it only costs this particular update
  		// its rollback safety net (see MarkSwapped's doc comment), not
  		// correctness.
  		if err := update.MarkSwapped(config.StateDir(), instr.Version, prevVersionDir); err != nil {
  			log.Printf("cb-agent: %v — update to %s already installed but will not be protected by the rollback window", err, instr.Version)
  		}
  		// Reported now, immediately before re-exec: a successful re-exec
  		// replaces this process's image and never returns here, so
  		// "succeeded" can't instead be sent by link.go after OnUpdate
  		// returns (see SendUpdateStatus's doc comment).
  		if err := send(instr.Version, "succeeded", ""); err != nil {
  			log.Printf("cb-agent: send succeeded update.status: %v", err)
  		}
  		log.Printf("cb-agent: updated to %s — re-executing", instr.Version)
  		return syscall.Exec(installedBinaryPath, os.Args, os.Environ())
  ```

  In `uninstallPaths` (current lines 714-721), remove the `previousBinary string` field and its
  doc-comment paragraph explaining it (the paragraph starting "previousBinary is the update-swap
  backup..." in the struct's doc comment, lines ~684-688) — replace that paragraph with a short
  note that no separate backup file exists anymore (every versioned binary lives under
  `stateDir`, which the `stateDir` entry already covers).

  In `defaultUninstallPaths` (current lines 729-735), change `binary: "/usr/local/bin/cb-agent",`
  to `binary: installedBinaryPath,` (same value, now sourced from the shared constant).

  Replace `resolveUninstallPaths` (current lines 737-761, function plus doc comment) with:

  ```go
  // resolveUninstallPaths returns the on-disk footprint `cb-agent uninstall`
  // removes. binary is always the fixed installedBinaryPath — NOT
  // os.Executable()'s result, unlike before the self-update fix (see
  // specs/2026-08-05-cb-agent-self-update-fix-design.md). Under the
  // two-level symlink layout, os.Executable() resolves straight through to
  // whatever {stateDir}/versions/<v>/cb-agent the running process happens to
  // be, not the stable /usr/local/bin/cb-agent entry point — using it here
  // would leave that root-owned top-level symlink behind after an
  // otherwise-complete uninstall. There is no separate ".previous"-backup
  // path to resolve either: every versioned binary lives under stateDir,
  // already covered by paths.stateDir's wholesale removal in
  // performUninstall.
  func resolveUninstallPaths() uninstallPaths {
  	paths := defaultUninstallPaths
  	paths.binary = installedBinaryPath
  	return paths
  }
  ```

  In `performUninstall` (current line 837), change:
  `for _, path := range []string{paths.unitFile, paths.binary, paths.previousBinary, paths.configFile, paths.stateDir} {`
  to:
  `for _, path := range []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir} {`

- [ ] **Step 4: Run the full `cmd/cb-agent` package test suite.**

  Run: `cd apps/agent && go build ./... && go vet ./... && go test ./cmd/cb-agent/... -v`
  Expected: PASS, all tests, no build or vet errors.

- [ ] **Step 5: Grep for any remaining reference to the old shapes this task removed, to catch a
  missed call site.**

  Run: `grep -rn '\.previousBinary\|preserveModeAndOwnership' apps/agent --include='*.go'`
  Expected: no output (both fully removed).

- [ ] **Step 6: Commit.**

  ```bash
  git add apps/agent/cmd/cb-agent/
  git commit -m "fix(agents): main.go orchestration for symlink-indirection self-update; pin uninstall to the fixed binary path (Bug 1)"
  ```

---

## Task 3: Install script (`agent_install.py`) — versioned directory and symlinks

**Depends on:** nothing from Tasks 1-2 (Python-only; independent of the Go changes, though it
implements the same layout Task 1/2's Go code expects to find on disk).

**Current state:** `_INSTALL_SCRIPT_TEMPLATE` in
`apps/backend/src/app/services/agent_install.py` installs the downloaded binary directly to
`/usr/local/bin/cb-agent` via `install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent`, then creates
`/etc/circuit-breaker` and `/var/lib/cb-agent` afterward.

**Files:**
- Modify: `apps/backend/src/app/services/agent_install.py`
- Modify: `apps/backend/tests/services/test_agent_install.py`

- [ ] **Step 1: Add a new failing test for the versioned-symlink layout.**

  Append to `test_agent_install.py`, after `test_render_install_script_is_valid_bash_syntax`:

  ```python
  def test_render_install_script_creates_versioned_symlink_layout():
      """Bug 1 fix (specs/2026-08-05-cb-agent-self-update-fix-design.md): the
      binary must land in a per-version directory under /var/lib/cb-agent,
      never directly at /usr/local/bin/cb-agent, with both symlinks
      (current -> versions/<v>, /usr/local/bin/cb-agent -> current) created
      and correctly owned — this is what lets the unprivileged cb-agent user
      perform a self-update entirely within permissions it already has.
      """
      script = agent_install.render_install_script(
          server_url="https://cb.example.com",
          server_static_pk_hex="ab" * 32,
          tls_pin="c" * 44,
          manifest={"0.5.0": {"linux-amd64": "deadbeef"}},
      )
      assert 'install -d -m 0755 -o cb-agent -g cb-agent "/var/lib/cb-agent/versions/0.5.0"' in script
      assert '"/var/lib/cb-agent/versions/0.5.0/cb-agent"' in script
      assert 'ln -sfn "versions/0.5.0" /var/lib/cb-agent/current' in script
      assert "chown -h cb-agent:cb-agent /var/lib/cb-agent/current" in script
      assert "ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent" in script
      # Never installed directly at the top-level path anymore.
      assert 'install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent' not in script
  ```

- [ ] **Step 2: Run the new test to confirm it fails against the unmodified template.**

  Run: `cd apps/backend && python -m pytest tests/services/test_agent_install.py::test_render_install_script_creates_versioned_symlink_layout -v`
  Expected: FAIL (the old template still installs directly to `/usr/local/bin/cb-agent`).

- [ ] **Step 3: Rewrite `_INSTALL_SCRIPT_TEMPLATE`'s binary-install section.**

  In `agent_install.py`, replace this block (current lines 40-48):

  ```
  TMP_BIN="$(mktemp)"
  CB_BINARY_URL="${{CB_SERVER_URL}}/api/v1/agents/binary/{latest_version}/linux/${{CB_ARCH}}"
  curl -fsSL "$CB_BINARY_URL" -o "$TMP_BIN"
  echo "${{CB_BINARY_SHA256}}  ${{TMP_BIN}}" | sha256sum -c
  install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent
  rm -f "$TMP_BIN"

  mkdir -p /etc/circuit-breaker /var/lib/cb-agent
  chown cb-agent:cb-agent /var/lib/cb-agent
  ```

  with:

  ```
  TMP_BIN="$(mktemp)"
  CB_BINARY_URL="${{CB_SERVER_URL}}/api/v1/agents/binary/{latest_version}/linux/${{CB_ARCH}}"
  curl -fsSL "$CB_BINARY_URL" -o "$TMP_BIN"
  echo "${{CB_BINARY_SHA256}}  ${{TMP_BIN}}" | sha256sum -c

  mkdir -p /etc/circuit-breaker /var/lib/cb-agent
  chown cb-agent:cb-agent /var/lib/cb-agent
  install -d -m 0755 -o cb-agent -g cb-agent "/var/lib/cb-agent/versions/{latest_version}"
  install -m 0755 -o cb-agent -g cb-agent "$TMP_BIN" "/var/lib/cb-agent/versions/{latest_version}/cb-agent"
  rm -f "$TMP_BIN"
  ln -sfn "versions/{latest_version}" /var/lib/cb-agent/current
  chown -h cb-agent:cb-agent /var/lib/cb-agent/current
  ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent
  ```

  (The `mkdir -p .../chown` step moves earlier because the versioned-directory `install -d` now
  needs `/var/lib/cb-agent` to already exist and be owned by `cb-agent`. `ExecStart=/usr/local/bin/cb-agent`
  in the systemd unit template further down and `sudo -u cb-agent /usr/local/bin/cb-agent enroll`
  are both unchanged — they already go through the stable path and don't care what it resolves
  to.)

- [ ] **Step 4: Run the full `test_agent_install.py` suite.**

  Run: `cd apps/backend && python -m pytest tests/services/test_agent_install.py -v`
  Expected: PASS, all tests (including the new one and
  `test_render_install_script_is_valid_bash_syntax`, which validates the new script is still valid
  POSIX `sh`).

- [ ] **Step 5: Commit.**

  ```bash
  git add apps/backend/src/app/services/agent_install.py apps/backend/tests/services/test_agent_install.py
  git commit -m "fix(backend/agent_install): generate versioned-symlink binary layout (Bug 1)"
  ```

---

## Task 4: Docker E2E harness — install through the new layout, un-xfail the regression test

**Depends on:** Tasks 1-2 (the compiled `cb-agent` binary must support the new layout for the E2E
scenario to actually pass).

**Current state:** `apps/agent/e2e/Dockerfile` builds `cb-agent` and `COPY`s it directly to
`/usr/local/bin/cb-agent` (root-owned, since the `COPY` runs before `USER cb-agent` switches),
then runs the daemon directly as `cb-agent` via `ENTRYPOINT` (no systemd in this harness — see
this plan's header for the confirmed scope decision). This container already reproduces the
ownership half of the real bug: a root-owned binary an unprivileged process can't rename in place.
`apps/agent/e2e/test_agent_e2e.py`'s `test_agent_update_success_and_forced_rollback` (step 7) is
currently `@pytest.mark.xfail(...)` for exactly this reason.

**Files:**
- Modify: `apps/agent/e2e/Dockerfile`
- Modify: `apps/agent/e2e/test_agent_e2e.py`

- [ ] **Step 1: Rewrite the Dockerfile's runtime stage to install through the versioned-symlink
  layout.**

  Replace the runtime stage (current lines 10-17) of `apps/agent/e2e/Dockerfile`:

  ```dockerfile
  FROM debian:bookworm-slim
  RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
  COPY --from=build /cb-agent /usr/local/bin/cb-agent
  RUN useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent \
      && mkdir -p /etc/circuit-breaker /var/lib/cb-agent \
      && chown cb-agent:cb-agent /var/lib/cb-agent
  USER cb-agent
  ENTRYPOINT ["/usr/local/bin/cb-agent"]
  ```

  with:

  ```dockerfile
  FROM debian:bookworm-slim
  RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
  # Mirrors the real install script's versioned-symlink layout (Bug 1 fix,
  # specs/2026-08-05-cb-agent-self-update-fix-design.md): the binary lands
  # under /var/lib/cb-agent/versions/<version>/, owned by the unprivileged
  # cb-agent user, and /usr/local/bin/cb-agent is a root-owned symlink chain
  # through it — never a root-owned binary the daemon must rename in place.
  # 0.0.0-dev matches AgentVersion's Go default (no -X ldflag is passed to
  # this build) — the same "starts at the Go default" baseline
  # test_agent_update_success_and_forced_rollback already relies on.
  RUN useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent \
      && mkdir -p /etc/circuit-breaker \
      && mkdir -p /var/lib/cb-agent/versions/0.0.0-dev \
      && chown -R cb-agent:cb-agent /var/lib/cb-agent
  COPY --from=build /cb-agent /var/lib/cb-agent/versions/0.0.0-dev/cb-agent
  RUN chown cb-agent:cb-agent /var/lib/cb-agent/versions/0.0.0-dev/cb-agent \
      && chmod 0755 /var/lib/cb-agent/versions/0.0.0-dev/cb-agent \
      && ln -sfn versions/0.0.0-dev /var/lib/cb-agent/current \
      && chown -h cb-agent:cb-agent /var/lib/cb-agent/current \
      && ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent
  USER cb-agent
  ENTRYPOINT ["/usr/local/bin/cb-agent"]
  ```

  Leave the build stage (current lines 1-8) untouched.

- [ ] **Step 2: Remove the `xfail` marker from the regression test.**

  In `apps/agent/e2e/test_agent_e2e.py`, replace (current lines 849-865):

  ```python
  @pytest.mark.e2e
  @pytest.mark.xfail(
      reason=(
          "Known production bug (follow-up task required): "
          "Agent self-update is structurally blocked by file ownership: binary is installed "
          "root-owned at /usr/local/bin/cb-agent but the agent daemon runs unprivileged. "
          "Further: systemd's ProtectSystem=strict sandbox (from real install script via "
          "apps/backend/src/app/services/agent_install.py's systemd unit template, Task 17 "
          "↔ Tasks 22-25 seam) blocks any write access to /usr/local/bin without "
          "ReadWritePaths covering the binary's directory. The actual swap in "
          "apps/agent/internal/update/update.go's Swap() requires rename-in-place write "
          "access to /usr/local/bin, which cannot succeed under this combination. "
          "Requires dedicated follow-up task, not a quick fix."
      ),
      strict=False,
  )
  def test_agent_update_success_and_forced_rollback():
  ```

  with:

  ```python
  @pytest.mark.e2e
  def test_agent_update_success_and_forced_rollback():
  ```

  Leave the rest of the test body, the module docstring, and every other test function in this
  file untouched — `_agent_status()["version"] == "0.0.0-dev"` still holds against the new
  Dockerfile's baked initial version.

- [ ] **Step 3: Build the E2E image and run the previously-xfail'd test for real — this is the
  actual proof the bug is fixed, not a stand-in for it.**

  Run (from `apps/agent/e2e/`):
  `docker compose -f docker-compose.yml build cb-agent && pytest test_agent_e2e.py -v -m e2e -k test_agent_update_success_and_forced_rollback`

  Expected: PASS. This run genuinely waits out the real ~2.5-minute `rollbackWindow` for the
  forced-rollback half (Step 7b) — that is expected, not a hang; do not interrupt it. If it fails,
  treat that as a real regression in Tasks 1-2's code, not a test-environment issue, and debug
  before proceeding (per superpowers:systematic-debugging) rather than re-adding `xfail`.

  If Docker is genuinely unavailable in the execution environment (it was confirmed available when
  this plan was written), fall back to `docker compose -f docker-compose.yml config` (validates
  the compose file parses) and a careful manual read-through of the Dockerfile diff against Task
  1-2's Go changes, and report this substitution explicitly in the task report so the human partner
  can run the live E2E separately.

- [ ] **Step 4: Run the rest of the E2E suite's fast checks as a sanity pass (not the full 7-scenario
  suite, which is expensive) — confirm nothing else in the file references the old xfail reason or
  breaks due to the Dockerfile change.**

  Run: `grep -n 'xfail\|Known production bug' apps/agent/e2e/test_agent_e2e.py`
  Expected: no output (the only `xfail` usage in this file was the one just removed).

- [ ] **Step 5: Commit.**

  ```bash
  git add apps/agent/e2e/Dockerfile apps/agent/e2e/test_agent_e2e.py
  git commit -m "fix(agents/e2e): install through the versioned-symlink layout, un-xfail the self-update regression test (Bug 1)"
  ```
