package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"sort"
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

	if pendingVersion, present, _ := update.ReadMarker(config.StateDir()); present {
		log.Printf("cb-agent: resuming after update to %s — watching for a successful link", pendingVersion)
		go func() {
			time.Sleep(2 * time.Minute)
			if v, stillPresent, _ := update.ReadMarker(config.StateDir()); stillPresent && v == pendingVersion {
				log.Printf("cb-agent: update to %s did not confirm within 2 minutes — rolling back", pendingVersion)
				if err := update.Rollback(binaryPath); err != nil {
					log.Printf("cb-agent: rollback failed: %v", err)
					return
				}
				// This process has no live /link connection to report the
				// rollback over (that's precisely why it's rolling back) —
				// persist it so the process re-exec'd below, once it
				// reconnects, sends the update.status(rolled_back) frame
				// (see internal/update.WriteRollbackReport's doc comment).
				if err := update.WriteRollbackReport(config.StateDir(), pendingVersion); err != nil {
					log.Printf("cb-agent: %v", err)
				}
				update.ClearMarker(config.StateDir())
				syscall.Exec(binaryPath, os.Args, os.Environ()) //nolint:errcheck // best-effort re-exec after rollback
			}
		}()
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
		if _, err := update.Swap(tmpPath, binaryPath); err != nil {
			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
				log.Printf("cb-agent: send failed update.status: %v", sendErr)
			}
			return err
		}
		if err := update.WriteMarker(config.StateDir(), instr.Version); err != nil {
			if sendErr := send(instr.Version, "failed", err.Error()); sendErr != nil {
				log.Printf("cb-agent: send failed update.status: %v", sendErr)
			}
			return err
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

func runUninstall() {
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

	if err := notifyUninstall(cfg, key); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: could not notify server (continuing anyway): %v\n", err)
	}
	fmt.Println("Notified the server. Run as root to finish removal:")
	fmt.Println("  systemctl disable --now cb-agent")
	fmt.Println("  rm -f /etc/systemd/system/cb-agent.service /usr/local/bin/cb-agent")
	fmt.Println("  rm -rf /var/lib/cb-agent /etc/circuit-breaker")
}

func notifyUninstall(cfg *config.Config, key *enroll.DeviceKey) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return link.Uninstall(ctx, link.Options{Config: cfg, Key: key})
}
