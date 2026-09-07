// The one-shot subcommands: version, signing-key, status and enroll.
//
// Everything here writes to an io.Writer taken as an argument rather than to
// stdout directly, which is what makes the output assertable in main_test.go.

package main

import (
	"fmt"
	"io"
	"os"
	"sort"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/spool"
	"circuitbreaker.dev/cb-agent/internal/status"
	"circuitbreaker.dev/cb-agent/internal/update"
)

func runVersion() {
	if err := printVersion(os.Stdout, config.StateDir(), AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// runSigningKey prints the Ed25519 update-signing public key embedded in
// this binary at build time, or nothing at all for a warn-mode build that
// carries none.
//
// It exists because a wrong `-X` package path sets the variable silently:
// the build succeeds, the binary verifies nothing, and the only symptom is
// an update path that quietly stopped being enforceable. `make
// verify-signing-key` reads this to prove the flag landed. Public key only —
// it is not secret, and nothing here can print the private half because the
// binary has never held it.
func runSigningKey() {
	fmt.Println(update.SigningPublicKey)
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
	printSpoolLoss(w, st.SpoolEvictions)
	return nil
}

// printSpoolLoss reports permanently destroyed observations, and prints
// nothing at all when there are none.
//
// Silence on zero is the deliberate half. A "spool loss: 0" line on every
// healthy agent trains an operator to skip the line, which would defeat the
// point on the one agent where it is not zero. Where it does print, it says
// in plain words that the data is gone — not "evicted", which reads as
// housekeeping — and names the window that was destroyed. The cause and its
// remedy come from printSpoolLossCause.
func printSpoolLoss(w io.Writer, stats spool.EvictionStats) {
	if stats.Frames <= 0 {
		return
	}
	fmt.Fprintf(w,
		"spool loss: %d observation(s) (%d bytes) were permanently discarded — the spool could not keep them\n",
		stats.Frames, stats.Bytes)
	if !stats.OldestDroppedTS.IsZero() && !stats.NewestDroppedTS.IsZero() {
		fmt.Fprintf(w, "  destroyed window: %s .. %s (this data is gone and cannot be recovered)\n",
			stats.OldestDroppedTS.UTC().Format(time.RFC3339),
			stats.NewestDroppedTS.UTC().Format(time.RFC3339))
	}
	if !stats.LastEvictedAt.IsZero() {
		fmt.Fprintf(w, "  most recently discarded: %s\n", stats.LastEvictedAt.UTC().Format(time.RFC3339))
	}
	printSpoolLossCause(w, stats.LastDestroyedCause, stats.LastDestroyedReason)
}

// printSpoolLossCause names what destroyed data most recently and gives that
// cause's remedy, keeping the other one in view without pretending it is
// equally likely.
//
// Two causes share the counter deliberately — the operator-facing fact is
// identical — but their remedies are opposite, so getting this wrong is worse
// than saying nothing. Telling an operator with a read-only state directory
// to raise a size cap is the confidently-wrong reporting this whole effort
// exists to end, and it is what this printed before the record carried a
// cause.
//
// It switches on the code, never on `reason`, which is display copy. An
// unrecognised or absent code — a record written by an agent that predates
// the field, since upgrades happen on the operator's own schedule — lists
// both rather than asserting a cause it does not know.
func printSpoolLossCause(w io.Writer, cause, reason string) {
	switch cause {
	case spool.CauseSizeCap:
		fmt.Fprintf(w, "  most recent cause: %s and dropped its oldest observations\n", reason)
		fmt.Fprintln(w, "    remedy: raise spool_cap_bytes in agent.toml so a longer outage fits, then restart the agent")
		fmt.Fprintln(w, "  this counter also records observations the spool could not write at all, if any earlier ones were")
	case spool.CauseWriteFailed:
		fmt.Fprintf(w, "  most recent cause: the spool could not write at all (%s)\n", reason)
		fmt.Fprintln(w, "    remedy: free or remount this agent's state directory, then restart the agent")
		fmt.Fprintln(w, "  raising spool_cap_bytes will not help this: the observations never reached the buffer")
	default:
		fmt.Fprintln(w, "  usual cause: the spool hit its size cap during an outage and dropped its oldest observations")
		fmt.Fprintln(w, "    remedy: raise spool_cap_bytes in agent.toml so a longer outage fits, then restart the agent")
		fmt.Fprintln(w, "  other cause: the spool could not write at all (full disk, read-only state directory)")
		fmt.Fprintln(w, "    remedy: check this agent's log for a 'could not be buffered' line, and free or remount the disk")
	}
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
	if err := enroll.Run(cfg, key, AgentVersion, link.ResolveTrust(cfg, config.StateDir()), config.StateDir()); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}
