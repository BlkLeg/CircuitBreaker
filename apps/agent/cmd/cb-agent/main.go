package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/hostinfo"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/spool"
	"circuitbreaker.dev/cb-agent/internal/status"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// AgentVersion is overridden at build time via -ldflags "-X main.AgentVersion=1.2.3".
var AgentVersion = "0.0.0-dev"

// rollbackWindow is how long runDaemon, after resuming with a pending update
// marker (internal/update.WriteMarker), waits for a successful hello.ack-
// gated OnConnected (Task 4) to clear that marker before concluding the
// update never confirmed and rolling back to the previous binary. A var, not
// a const, so tests can shrink it rather than waiting out the production
// value — mirrors internal/link's stabilityWindow/rekeyInterval pattern.
var rollbackWindow = 2 * time.Minute

// watchForRollback waits up to rollbackWindow for the update marker naming
// pendingVersion to be cleared — which onConnected (wired in runDaemon)
// does exactly once, the moment a post-update connection reaches an
// accepted hello.ack (Task 4's OnConnected gating, not merely a completed
// Noise handshake). If the marker is still present and still names
// pendingVersion once the window elapses, the update never confirmed:
// watchForRollback restores the previous binary, persists a rollback report
// for the next connection to send (this process has no live link to report
// over — that's exactly why it's rolling back), clears the marker, and
// re-execs via reExec.
//
// If the marker is still present but was never confirmed to have reached
// phasePendingConfirm (update.ReadMarker's swapped == false), then
// update.Swap never actually ran for this attempt — most likely a crash
// landed between WriteMarker and Swap in onUpdate. There is nothing to roll
// back: the binary at binaryPath was never touched, and targetPath+
// ".previous" (if it exists at all) belongs to some earlier,
// already-confirmed update, not this one — using it here would silently
// downgrade a healthy running binary to a stale, unrelated backup. The
// marker is simply cleared and the abandoned attempt logged.
//
// reExec is a parameter rather than a direct syscall.Exec call so tests can
// observe a rollback decision without actually replacing the test binary's
// process image; runDaemon passes a closure that does call syscall.Exec.
func watchForRollback(stateDir, binaryPath, pendingVersion string, reExec func() error) {
	time.Sleep(rollbackWindow)

	v, swapped, stillPresent, err := update.ReadMarker(stateDir)
	if err != nil {
		log.Printf("cb-agent: %v", err)
		return
	}
	if !stillPresent || v != pendingVersion {
		// Cleared by onConnected (confirmed) or superseded by a newer
		// update's marker — either way, this window's job is done.
		return
	}
	if !swapped {
		log.Printf("cb-agent: update to %s never completed its binary swap (crashed before Swap ran) — nothing to roll back, clearing marker", pendingVersion)
		if err := update.ClearMarker(stateDir); err != nil {
			log.Printf("cb-agent: %v", err)
		}
		return
	}

	log.Printf("cb-agent: update to %s did not confirm within %s — rolling back", pendingVersion, rollbackWindow)
	if err := update.Rollback(binaryPath); err != nil {
		// Rollback failed (no .previous, unreadable, cross-device error,
		// ...): the marker must still be cleared here. Leaving it in place
		// would re-arm this exact same doomed rollback attempt on every
		// subsequent restart, forever, until some unrelated hello.ack
		// eventually clears it via the normal success path — a permanently
		// stuck retry loop for no benefit, since there is nothing further
		// waiting on the marker either way: the currently-running binary is
		// whatever it already is regardless of whether the marker is
		// cleared now or later.
		log.Printf("cb-agent: rollback failed: %v — clearing marker to avoid a permanently stuck retry loop", err)
		if clearErr := update.ClearMarker(stateDir); clearErr != nil {
			log.Printf("cb-agent: %v", clearErr)
		}
		return
	}
	// This process has no live /link connection to report the rollback over
	// (that's precisely why it's rolling back) — persist it so the process
	// re-exec'd below, once it reconnects, sends the
	// update.status(rolled_back) frame (see
	// internal/update.WriteRollbackReport's doc comment).
	if err := update.WriteRollbackReport(stateDir, pendingVersion); err != nil {
		log.Printf("cb-agent: %v", err)
	}
	if err := update.ClearMarker(stateDir); err != nil {
		log.Printf("cb-agent: %v", err)
	}
	if err := reExec(); err != nil {
		log.Printf("cb-agent: re-exec after rollback failed: %v", err)
	}
}

func main() {
	if len(os.Args) < 2 {
		runDaemon()
		return
	}
	switch os.Args[1] {
	case "version":
		runVersion()
	case "status":
		runStatus()
	case "enroll":
		runEnroll()
	case "uninstall":
		runUninstall()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runDaemon() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if err := enroll.Run(cfg, key, AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: enrollment: %v\n", err)
		os.Exit(1)
	}

	capGate := capability.New(config.StateDir())
	if err := capGate.LoadCached(); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
	}

	// statusWriter is the source `cb-agent status` reads from — see
	// internal/status. It starts from whatever the capability gate already
	// has cached (a restart while disconnected shouldn't make status forget
	// the last-known grants) and the readiness this host can report before
	// any link attempt (readiness has no network dependency — see
	// hostinfo.Collect).
	statusWriter := status.NewWriter(config.StateDir(), AgentVersion, key.FingerprintGrouped())
	if err := statusWriter.SetGrants(capGate.Grants()); err != nil {
		log.Printf("cb-agent: status: %v", err)
	}
	if err := statusWriter.SetReadiness(hostinfo.Collect(AgentVersion).Readiness); err != nil {
		log.Printf("cb-agent: status: %v", err)
	}

	// Audit the dedicated-user file-permission model (specs/2026-07-26-cb-
	// agent-design.md §4.1) before touching anything else in the state
	// directory: identity (device.key), cached grant (grants.json), and
	// runtime status (status.json) must all be owned by the user this
	// process is actually running as, and mode 0600. Ownership drift aborts
	// startup outright (see auditStateDir's doc comment); mode drift is
	// corrected in place.
	if err := auditStateDir(config.StateDir(), os.Geteuid(), os.Getegid()); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	// sp is the outbound *data* frame spool (internal/spool) — never
	// heartbeat/control traffic, see frame.IsDataFrame. Opening it here, at
	// daemon startup and before the link ever connects, is what makes an
	// unclean shutdown's persisted backlog recover (spool.Open's load()) and
	// become visible in `cb-agent status` before this run's first connection
	// attempt even completes.
	sp, err := openSpool(cfg, config.StateDir(), statusWriter)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

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

	var confirmOnce sync.Once
	onConnected := func() {
		confirmOnce.Do(func() {
			update.ClearMarker(config.StateDir())
		})
		if err := statusWriter.SetAccepted(); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
	}

	onRejected := func(reason string) {
		if err := statusWriter.SetRejected(reason); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
	}

	onDisconnected := func(cause error) {
		if err := statusWriter.SetDisconnected(cause); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
	}

	onCapabilitiesSet := func(payload json.RawMessage) error {
		if err := capGate.ApplyGrants(payload); err != nil {
			return err
		}
		if err := statusWriter.SetGrants(capGate.Grants()); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
		return nil
	}

	onUpdate := func(payload json.RawMessage, send link.SendUpdateStatus) error {
		var instr update.Instruction
		if err := json.Unmarshal(payload, &instr); err != nil {
			return err
		}
		if err := send(instr.Version, "started", ""); err != nil {
			log.Printf("cb-agent: send started update.status: %v", err)
		}
		tmpPath, err := update.Download(cfg, instr)
		if err != nil {
			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
				log.Printf("cb-agent: send failed update.status: %v", sendErr)
			}
			return err
		}
		if err := update.VerifySHA256(tmpPath, instr.SHA256); err != nil {
			os.Remove(tmpPath)
			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
				log.Printf("cb-agent: send failed update.status: %v", sendErr)
			}
			return err
		}
		// Task 25: the rollback marker must be durably written *before* the
		// binary is actually replaced, not after. If a crash lands between
		// these two steps, the marker still correctly names the version
		// that was about to be installed — a recoverable state, since the
		// swap never ran and there's nothing to roll back. Writing the
		// marker only after a successful Swap would instead let a crash in
		// that window leave a replaced (and possibly broken) binary running
		// with no marker at all — no rollback safety net.
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
	}

	onSpoolStats := func(depth int, bytes int64) {
		if err := statusWriter.SetSpoolStats(depth, bytes); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := link.Run(ctx, link.Options{
		Config: cfg, Key: key, AgentVersion: AgentVersion,
		StateDir:          config.StateDir(),
		OnCapabilitiesSet: onCapabilitiesSet,
		OnUpdate:          onUpdate,
		OnConnected:       onConnected,
		OnRejected:        onRejected,
		OnDisconnected:    onDisconnected,
		ReportPendingUpdateOutcome: func() (string, bool) {
			version, ok, _ := update.ReadRollbackReport(config.StateDir())
			return version, ok
		},
		ClearPendingUpdateOutcome: func() {
			if err := update.ClearRollbackReport(config.StateDir()); err != nil {
				log.Printf("cb-agent: %v", err)
			}
		},
		Spool:        sp,
		OnSpoolStats: onSpoolStats,
		// DataFrames is left unset: no producer exists yet in Slice 1 (Global
		// Constraints — the spool stays idle end-to-end until Slice 2+ wires
		// a real telemetry/probe/discovery collector into it).
	}); err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// openSpool opens the outbound data-frame spool at stateDir, defaulting its
// capacity to spool.DefaultCapBytes when cfg leaves SpoolCapBytes at its
// zero value (no spool_cap_bytes configured in agent.toml), and reports the
// spool's post-recovery depth/size into statusWriter. spool.Open's load()
// does the actual unclean-shutdown recovery (internal/spool); calling it
// here, before the daemon's first link attempt, is what makes that recovery
// happen at daemon startup rather than never.
func openSpool(cfg *config.Config, stateDir string, statusWriter *status.Writer) (*spool.Spool, error) {
	capBytes := cfg.SpoolCapBytes
	if capBytes <= 0 {
		capBytes = spool.DefaultCapBytes
	}
	sp, err := spool.Open(stateDir, capBytes)
	if err != nil {
		return nil, err
	}
	size, err := sp.SizeBytes()
	if err != nil {
		return nil, err
	}
	if err := statusWriter.SetSpoolStats(sp.Len(), size); err != nil {
		log.Printf("cb-agent: status: %v", err)
	}
	return sp, nil
}

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

func runVersion() {
	if err := printVersion(os.Stdout, config.StateDir(), AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// printVersion writes "cb-agent <version>" and, only when a device key
// already exists at stateDir, a "fingerprint: ..." line. It reads
// device.key if present but never creates one — `cb-agent version` is an
// inspection command and must not generate agent identity as a side effect.
func printVersion(w io.Writer, stateDir, agentVersion string) error {
	fmt.Fprintf(w, "cb-agent %s\n", agentVersion)
	key, ok, err := enroll.LoadDeviceKey(stateDir)
	if err != nil {
		return err
	}
	if ok {
		fmt.Fprintf(w, "fingerprint: %s\n", key.FingerprintGrouped())
	}
	return nil
}

func runStatus() {
	if err := printStatus(os.Stdout, config.StateDir()); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// printStatus reads the daemon's runtime status file (internal/status) and
// reports truthful daemon state. It never touches device.key and never
// starts or contacts the daemon — if the daemon has never run, or hasn't
// reached its first status write yet, it says so rather than fabricating a
// state.
func printStatus(w io.Writer, stateDir string) error {
	st, ok, err := status.Read(stateDir)
	if err != nil {
		return err
	}
	if !ok {
		fmt.Fprintln(w, "no status recorded yet — the daemon has not run, or has not reached its first link attempt")
		return nil
	}

	fmt.Fprintf(w, "version: %s\n", st.Version)
	if st.Fingerprint != "" {
		fmt.Fprintf(w, "fingerprint: %s\n", st.Fingerprint)
	}
	fmt.Fprintf(w, "link: %s\n", st.LinkState)
	if !st.LastConnected.IsZero() {
		fmt.Fprintf(w, "last connected: %s\n", st.LastConnected.Format(time.RFC3339))
	}
	if st.LastError != "" {
		fmt.Fprintf(w, "last error: %s (%s)\n", st.LastError, st.LastErrorAt.Format(time.RFC3339))
	}

	if len(st.Grants) == 0 {
		fmt.Fprintln(w, "grants: none")
	} else {
		fmt.Fprintln(w, "grants:")
		for _, name := range sortedKeys(st.Grants) {
			fmt.Fprintf(w, "  %s: %v\n", name, st.Grants[name])
		}
	}

	if len(st.Readiness) == 0 {
		fmt.Fprintln(w, "readiness: none reported")
	} else {
		for _, r := range st.Readiness {
			line := fmt.Sprintf("readiness: %s = %s", r.Collector, r.State)
			if r.Reason != "" {
				line += fmt.Sprintf(" (%s)", r.Reason)
			}
			fmt.Fprintln(w, line)
		}
	}

	fmt.Fprintf(w, "spool: depth=%d bytes=%d\n", st.SpoolDepth, st.SpoolBytes)
	return nil
}

// sortedKeys returns m's keys sorted, so printStatus's grants listing has a
// stable, testable order instead of Go's randomized map iteration.
func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func runEnroll() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	if err := enroll.Run(cfg, key, AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// runUninstall is the `cb-agent uninstall` entry point (spec §4.7): it
// requires root (disabling a systemd unit and removing root-owned files
// under /etc and /usr/local/bin isn't possible otherwise), best-effort
// notifies the server so the agent's row flips to revoked (see
// notifyUninstallBestEffort), then actually disables/removes/reloads —
// unlike this function's pre-Task-29 form, which only ever printed the
// systemctl/rm commands for an operator to run by hand.
func runUninstall() {
	if err := requireRoot(os.Geteuid()); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if err := notifyUninstallBestEffort(); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: could not notify server (continuing anyway): %v\n", err)
	} else {
		fmt.Println("Notified the server (agent record marked revoked).")
	}

	result := performUninstall(resolveUninstallPaths(), runSystemctl)

	if result.DisabledUnit {
		fmt.Printf("Disabled systemd unit %q.\n", uninstallUnitName)
	} else {
		fmt.Fprintf(os.Stderr, "cb-agent: could not disable systemd unit %q: %v\n", uninstallUnitName, result.DisableErr)
	}

	if len(result.Removed) == 0 {
		fmt.Println("Removed: nothing found on disk.")
	} else {
		fmt.Println("Removed:")
		for _, path := range result.Removed {
			fmt.Printf("  %s\n", path)
		}
	}
	for _, path := range result.RemoveErrs {
		fmt.Fprintf(os.Stderr, "cb-agent: could not remove %s: %v\n", path.path, path.err)
	}

	if result.ReloadedDaemon {
		fmt.Println("Reloaded systemd.")
	} else {
		fmt.Fprintf(os.Stderr, "cb-agent: could not reload systemd: %v\n", result.ReloadErr)
	}

	if result.DisableErr != nil || len(result.RemoveErrs) > 0 || result.ReloadErr != nil {
		os.Exit(1)
	}
}

// notifyUninstallBestEffort loads whatever config/identity is still present
// and sends the one-shot `uninstall` frame over link.Uninstall. Config or
// identity that's already missing (e.g. a second uninstall attempt after a
// first one partially completed) is reported as this function's error
// rather than panicking or being treated as fatal to the caller — runUninstall
// proceeds to remove files regardless, since notifying the server is
// explicitly best-effort (Global Constraints / this task's brief).
func notifyUninstallBestEffort() error {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		return err
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		return err
	}
	return notifyUninstall(cfg, key)
}

func notifyUninstall(cfg *config.Config, key *enroll.DeviceKey) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return link.Uninstall(ctx, link.Options{Config: cfg, Key: key})
}

// requireRoot fails loudly unless euid is 0. `cb-agent uninstall` disables a
// systemd unit and removes root-owned files (the unit file under
// /etc/systemd/system, the binary under /usr/local/bin, /etc/circuit-breaker,
// and the state dir — see uninstallPaths), none of which an unprivileged
// user can do; refusing up front beats a confusing pile of
// permission-denied errors partway through removal.
func requireRoot(euid int) error {
	if euid != 0 {
		return fmt.Errorf("cb-agent uninstall must be run as root (uid 0), got uid %d — re-run with sudo", euid)
	}
	return nil
}

// uninstallUnitName is the systemd unit `cb-agent uninstall` disables and
// whose reload it triggers — the same unit name the install script
// (plans/2026-07-27-cb-agent-slice1.md Task 17) registers at
// defaultUninstallPaths.unitFile.
const uninstallUnitName = "cb-agent"

// uninstallPaths is the on-disk footprint `cb-agent uninstall` removes.
//
// unitFile/binary mirror the install script's own write targets (spec
// §"Files on disk": "/etc/systemd/system/cb-agent.service" the unit,
// "/usr/local/bin/cb-agent" the binary). previousBinary is the update-swap
// backup internal/update.Swap leaves at <binary>+".previous" (see
// update.go's Swap/Rollback) — NOT under the state dir, despite an earlier
// version of this comment and the Task 29 report claiming otherwise; it is
// never removed on its own, so a self-update host that never uninstalls
// would otherwise carry it forever.
//
// configFile ("/etc/circuit-breaker/agent.toml") and configDir
// ("/etc/circuit-breaker", its parent) are deliberately two separate
// entries, NOT "remove configDir wholesale" as an earlier version of this
// type did: /etc/circuit-breaker is co-owned by the main CircuitBreaker
// server, not agent-exclusive — packaging/postinstall.sh (the server's own
// installer) creates that directory and writes config.toml and
// circuit-breaker.env there, the latter holding a freshly generated
// CB_VAULT_KEY, CB_DB_URL, and NATS_AUTH_TOKEN; the server reads
// config.toml at runtime (apps/backend/src/app/core/config_toml.py), and
// the server's own uninstall.sh requires an interactive confirmation before
// ever touching that directory. On a host where cb-agent monitors the
// CircuitBreaker server itself, blindly removing configDir would destroy
// the server's config and leave its vault permanently undecryptable — see
// performUninstall's handling of configDir for how this is enforced (only
// configFile is ever removed directly; configDir is removed only if
// agent.toml's removal left it empty).
//
// stateDir is exactly config.StateDir(), the same directory Task 30's
// auditStateDir treats as this agent's identity/grant/status footprint
// (device.key, grants.json, status.json all live directly under it, plus
// spool/) — removing it wholesale means this list never needs to be kept
// in sync file-by-file with sensitiveStateFiles as that set grows. Unlike
// configDir, stateDir is exclusively cb-agent's own — nothing else is ever
// expected to write there — so removing it wholesale remains correct.
type uninstallPaths struct {
	unitFile       string
	binary         string
	previousBinary string
	configFile     string
	configDir      string
	stateDir       string
}

// defaultUninstallPaths is the static fallback footprint. binary and
// previousBinary are placeholders here — resolveUninstallPaths overrides
// both with the actual running binary's path (via os.Executable()) before
// this is ever passed to performUninstall in production; defaultUninstallPaths
// itself is used directly only as resolveUninstallPaths' fallback base when
// os.Executable() fails.
var defaultUninstallPaths = uninstallPaths{
	unitFile:   "/etc/systemd/system/cb-agent.service",
	binary:     "/usr/local/bin/cb-agent",
	configFile: "/etc/circuit-breaker/agent.toml",
	configDir:  "/etc/circuit-breaker",
	stateDir:   config.StateDir(),
}

// resolveUninstallPaths builds the on-disk footprint `cb-agent uninstall`
// removes, resolving the actual running binary's path via os.Executable()
// rather than trusting defaultUninstallPaths.binary's hardcoded
// "/usr/local/bin/cb-agent" literal — if cb-agent was installed somewhere
// else, the hardcoded literal would silently be skipped from removal with
// no indication to the operator that it wasn't found where expected.
// previousBinary (see uninstallPaths' doc comment) is derived from
// whichever binary path was actually resolved, so a non-default install
// location's ".previous" backup is found too.
//
// os.Executable() failing is rare enough in practice (its own doc comment:
// "not guaranteed to be stable" only across certain exotic cases, e.g. the
// binary being replaced/deleted while running) that it isn't worth aborting
// the whole uninstall over — this falls back to the historical hardcoded
// path instead, with a note printed so the operator knows to check.
func resolveUninstallPaths() uninstallPaths {
	paths := defaultUninstallPaths
	if exe, err := os.Executable(); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: could not resolve running binary path (%v) — falling back to %s\n", err, paths.binary)
	} else {
		paths.binary = exe
	}
	paths.previousBinary = paths.binary + ".previous"
	return paths
}

// systemctlRunner invokes one systemctl subcommand — args exactly as passed
// to exec.Command("systemctl", args...) in production. A function value
// (not a direct exec.Command call inside performUninstall) so tests can
// substitute a fake that records invocations and touches no real systemd —
// mirrors this package's existing reExec-as-a-parameter pattern (see
// watchForRollback).
type systemctlRunner func(args ...string) error

// runSystemctl is the production systemctlRunner. Combined output is folded
// into the returned error so a failure (e.g. "Unit cb-agent.service not
// loaded", which is not fatal to uninstall — see performUninstall) is at
// least visible to the operator instead of a bare exit-status error.
func runSystemctl(args ...string) error {
	out, err := exec.Command("systemctl", args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("systemctl %s: %w: %s", strings.Join(args, " "), err, strings.TrimSpace(string(out)))
	}
	return nil
}

// pathRemoveErr pairs a path performUninstall failed to remove with the
// error that removal hit, so runUninstall's summary can name exactly which
// path failed rather than a single opaque combined error.
type pathRemoveErr struct {
	path string
	err  error
}

// uninstallResult is performUninstall's report of exactly what happened,
// precise enough for runUninstall to print a truthful summary rather than
// assuming every step succeeded.
type uninstallResult struct {
	DisabledUnit   bool
	DisableErr     error
	Removed        []string
	RemoveErrs     []pathRemoveErr
	ReloadedDaemon bool
	ReloadErr      error
}

// performUninstall disables the systemd unit, removes every path in paths
// that exists, and reloads systemd, in that order — order matters:
// disable-before-remove stops systemd from restarting the service mid-
// removal (e.g. an active unit's Restart=on-failure racing the unit-file
// deletion), and daemon-reload runs last so systemd's unit cache is
// refreshed only once the unit file is actually gone.
//
// Each of the three phases is independent and best-effort with respect to
// the others: a failed disable (unit never installed, systemd absent
// entirely in a container, ...) must not block file removal, and a failed
// removal of one path must not block the others or the final daemon-reload.
// Every outcome is recorded on the returned uninstallResult rather than
// stopping early, so the caller can report a complete, truthful summary.
//
// paths.configDir (/etc/circuit-breaker) is handled separately from every
// other path in the list, and deliberately never passed through
// os.RemoveAll: it is co-owned by the main CircuitBreaker server (see
// uninstallPaths' doc comment), so only paths.configFile (this agent's own
// agent.toml) is removed directly. configDir itself is removed with a
// non-recursive os.Remove only once agent.toml's removal has left it empty
// — on a co-located host where the server's own config.toml/
// circuit-breaker.env are still present, that remove is skipped entirely,
// silently, and is not reported as an error: an operator uninstalling
// cb-agent from a host that also runs the CircuitBreaker server must never
// see this as a failure, and must never have the server's files touched.
func performUninstall(paths uninstallPaths, systemctl systemctlRunner) uninstallResult {
	var result uninstallResult

	if err := systemctl("disable", "--now", uninstallUnitName); err != nil {
		result.DisableErr = err
	} else {
		result.DisabledUnit = true
	}

	for _, path := range []string{paths.unitFile, paths.binary, paths.previousBinary, paths.configFile, paths.stateDir} {
		if path == "" {
			continue
		}
		if _, err := os.Stat(path); err != nil {
			if os.IsNotExist(err) {
				continue
			}
			result.RemoveErrs = append(result.RemoveErrs, pathRemoveErr{path: path, err: err})
			continue
		}
		if err := os.RemoveAll(path); err != nil {
			result.RemoveErrs = append(result.RemoveErrs, pathRemoveErr{path: path, err: err})
			continue
		}
		result.Removed = append(result.Removed, path)
	}

	if paths.configDir != "" {
		if entries, err := os.ReadDir(paths.configDir); err != nil {
			if !os.IsNotExist(err) {
				result.RemoveErrs = append(result.RemoveErrs, pathRemoveErr{path: paths.configDir, err: err})
			}
		} else if len(entries) == 0 {
			if err := os.Remove(paths.configDir); err != nil {
				result.RemoveErrs = append(result.RemoveErrs, pathRemoveErr{path: paths.configDir, err: err})
			} else {
				result.Removed = append(result.Removed, paths.configDir)
			}
		}
		// else: other files remain (e.g. the main CircuitBreaker server's
		// own config.toml/circuit-breaker.env on a co-located host) —
		// expected, silent no-op; see this function's doc comment.
	}

	if err := systemctl("daemon-reload"); err != nil {
		result.ReloadErr = err
	} else {
		result.ReloadedDaemon = true
	}

	return result
}
