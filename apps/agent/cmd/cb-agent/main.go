package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/logging"
	"circuitbreaker.dev/cb-agent/internal/status"
)

// AgentVersion is overridden at build time via -ldflags "-X main.AgentVersion=1.2.3".
var AgentVersion = "0.0.0-dev"

// readinessReportInterval is the floor between two capability.readiness
// frames: unless a report is forced (its content changed, or a fresh link came
// up), queueReadiness drops it. reconcileTickInterval is how often the daemon
// re-offers the current report to that floor, so the server hears from an
// agent at least once every readiness interval *even when host_telemetry is
// disabled and no collection ever runs* — the slice-2 contract's "every 15
// minutes as reconciliation", which used to be a side effect of a successful
// collection and therefore stopped exactly when it mattered most.
//
// Vars, not consts, so tests can shrink them rather than waiting out the
// production values — same pattern as rollbackWindow above.
var (
	readinessReportInterval = 15 * time.Minute
	reconcileTickInterval   = time.Minute
)

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
	case "signing-key":
		runSigningKey()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

// configureLogging gives agent.toml's log_level an effect. An unknown value is
// returned as an error rather than ignored: the setting used to be decoded and
// dropped, so a typo looked exactly like a working configuration.
func configureLogging(cfg *config.Config) error {
	return logging.Configure(cfg.LogLevel)
}

// shouldEnroll reports whether runDaemon must call retryEnroll before
// proceeding to startDaemonState. Split out from the inline check purely so
// a test can pin the startup decision itself — present marker skips, absent
// marker calls Run — without needing a real config file or network access,
// the same reason rollbackExpiredUpdate and watchForRollback above take
// their inputs as parameters rather than reading globals directly.
func shouldEnroll(stateDir string) bool {
	return !enroll.IsEnrolled(stateDir)
}

// retryEnroll drives enroll.Run in a loop instead of letting a single failed
// attempt kill the process. Surviving a server outage is the agent's entire
// job; dying because one happened to be in progress the moment the process
// started — which crash-loops the whole daemon under systemd's or Docker's
// restart policy, collecting and spooling nothing for as long as the outage
// lasts — was the worst possible failure mode. Returns nil once Run succeeds
// (status "active", which is also where enroll.MarkEnrolled runs). Returns
// ctx.Err() only when ctx is canceled while waiting between attempts —
// runDaemon's cue that the process is being asked to stop, not that
// enrollment failed for good.
//
// Every non-refusal attempt is scheduled by link.RetrySchedule, reusing
// Phase 1's classification and ladder rather than a second, independently-
// tuned copy of it — see that type's doc comment for why. A "rejected" or
// "revoked" answer is different in kind, not just severity: it means an
// operator looked at this device and said no, which retrying at network
// speed does not change and silently exiting cannot surface. So it bypasses
// the ladder entirely, waits on link.EnrollRefusalDelay's slow, steady poll
// instead (so an un-revoke is picked up without anyone SSHing to the box),
// and is written to status.json so `cb-agent status` explains the wait.
func retryEnroll(ctx context.Context, cfg *config.Config, key *enroll.DeviceKey, agentVersion, stateDir string) error {
	trust := link.ResolveTrust(cfg, stateDir)
	sched := link.NewRetrySchedule()
	// A dedicated Writer rather than one shared with startDaemonState: there
	// is no daemon-lifetime status.Writer yet at this point in the startup
	// sequence (auditStateDir and the rest of startDaemonState's step 3
	// haven't run), and constructing one is free — status.NewWriter writes
	// nothing to disk itself, only the SetRejected call below does, and only
	// on an actual refusal. startDaemonState's own Writer, built once
	// enrollment succeeds, then becomes the one `cb-agent status` reads from
	// for the rest of this process's life.
	statusWriter := status.NewWriter(stateDir, agentVersion, key.FingerprintGrouped())

	for {
		err := enroll.Run(cfg, key, agentVersion, trust, stateDir)
		if err == nil {
			return nil
		}

		var delay time.Duration
		switch {
		case errors.Is(err, enroll.ErrRejected):
			delay = link.EnrollRefusalDelay()
			if werr := statusWriter.SetRejected("rejected"); werr != nil {
				log.Printf("cb-agent: status: %v", werr)
			}
		case errors.Is(err, enroll.ErrRevoked):
			delay = link.EnrollRefusalDelay()
			if werr := statusWriter.SetRejected("revoked"); werr != nil {
				log.Printf("cb-agent: status: %v", werr)
			}
		default:
			delay = sched.Next(err)
		}

		log.Printf("cb-agent: enrollment failed (%v) — retrying in %s", err, delay)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}
