// State-directory ownership auditing.
//
// The agent refuses to start when device.key, grants.json or status.json are
// readable by anyone but the agent's own user — a key another local account can
// read is a key that can impersonate this agent to the server.

package main

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"syscall"
)

// sensitiveStateFiles are the file classes auditStateDir enforces mode 0600
// on, at every daemon startup — device.key (agent identity), grants.json
// (cached capability grant, internal/capability), and status.json (runtime
// status, internal/status — mode was set at creation in Task 20; this is
// the startup-time audit/enforcement pass that closes the gap for a file
// that drifts wider after creation).
var sensitiveStateFiles = []string{"device.key", "grants.json", "status.json"}

// auditStateDir enforces the dedicated-user file-permission model
// (specs/2026-07-26-cb-agent-design.md §4.1: a dedicated `cb-agent` user,
// device.key "mode 0600, owned by `cb-agent`") at every daemon startup, not
// only at the moment each file happens to be created.
//
// ORDERING INVARIANT: this must run before every daemon-loop state write —
// grants.json (internal/capability), status.json (internal/status), and
// spool/queue.jsonl (internal/spool). It is deliberately step (1) of
// startDaemonState for exactly that reason; do not move it later. It is *not*
// "before anything at all touches the state directory": device.key is written
// earlier still, by enroll.LoadOrCreateDeviceKey and enroll.Run in runDaemon,
// and that is fine — identity has to exist before there is a daemon to audit
// for. The narrow, real invariant is the one this comment states, and
// TestStartDaemonState_AuditRunsBeforeAnyStateWrite pins it.
//
// Ownership drift on stateDir itself or on any of sensitiveStateFiles fails
// loudly: it returns a non-nil error, which runDaemon turns into a startup
// abort rather than continuing. expectedUID/expectedGID is the identity
// this process is actually running as (callers pass os.Geteuid()/
// os.Getegid()) — a state directory or identity/grant/status file not
// owned by that user means either a broken install (these files should
// only ever be written by the daemon itself) or something worse, and
// silently continuing to operate on files another user can also write is
// not a state this daemon should run in.
//
// Mode drift on a sensitive file is corrected instead of failing startup:
// chmod'd back to 0600 in place. A wider mode is far more plausibly a stale
// file from an older binary, a restored backup, or a manual edit than
// evidence of compromise, so self-healing is the useful default here where
// it isn't for ownership.
//
// A missing stateDir, or a missing individual sensitive file, is not an
// error — a fresh install has no grants.json until the first
// capabilities.set frame ever arrives (spec §4.2), and every caller that
// needs the directory or a particular file to exist creates it before this
// function ever runs in the real startup sequence.
func auditStateDir(stateDir string, expectedUID, expectedGID int) error {
	dirInfo, err := os.Stat(stateDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("audit state dir: stat %s: %w", stateDir, err)
	}
	if err := checkOwnership(stateDir, dirInfo, expectedUID, expectedGID); err != nil {
		return err
	}

	for _, name := range sensitiveStateFiles {
		path := filepath.Join(stateDir, name)
		info, err := os.Stat(path)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return fmt.Errorf("audit state dir: stat %s: %w", path, err)
		}
		if err := checkOwnership(path, info, expectedUID, expectedGID); err != nil {
			return err
		}
		if mode := info.Mode().Perm(); mode != 0o600 {
			if err := os.Chmod(path, 0o600); err != nil {
				return fmt.Errorf("audit state dir: correct mode on %s (was %04o): %w", path, mode, err)
			}
			log.Printf("cb-agent: corrected %s from mode %04o to 0600", path, mode)
		}
	}
	return nil
}

// checkOwnership fails loudly — a non-nil, descriptive error — when info's
// owning uid/gid don't match expectedUID/expectedGID. See auditStateDir's
// doc comment for why ownership drift aborts startup rather than being
// corrected the way mode drift is.
func checkOwnership(path string, info os.FileInfo, expectedUID, expectedGID int) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		// Not a platform where ownership is statable this way — this daemon
		// targets "linux amd64/arm64" only (spec §"Runtime & packaging"),
		// so in practice this never triggers outside a non-Unix test build.
		return nil
	}
	if int(stat.Uid) != expectedUID || int(stat.Gid) != expectedGID {
		return fmt.Errorf(
			"%s is owned by uid=%d gid=%d, want uid=%d gid=%d (the dedicated agent user) — refusing to start",
			path, stat.Uid, stat.Gid, expectedUID, expectedGID,
		)
	}
	return nil
}
