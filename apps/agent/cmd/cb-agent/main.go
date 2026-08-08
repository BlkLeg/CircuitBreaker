package main

import (
	"bytes"
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
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
	discovercollect "circuitbreaker.dev/cb-agent/internal/collect/discover"
	hostcollect "circuitbreaker.dev/cb-agent/internal/collect/host"
	probecollect "circuitbreaker.dev/cb-agent/internal/collect/probe"
	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/hostinfo"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/netscope"
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

// reExecDelayEnvOverride is a narrowly-scoped, test-only escape hatch,
// mirroring internal/link's rekeyIntervalEnvOverride: if set to a positive
// integer number of milliseconds, onUpdate sleeps that long immediately
// before re-exec'ing into the newly-swapped binary. It exists solely so the
// Docker E2E harness (apps/agent/e2e) can reliably win the race against a
// freshly re-exec'd process reconnecting and self-confirming an update
// before the test's own docker-network-disconnect trigger can land — on a
// local Docker bridge network, re-exec-to-hello.ack routinely completes in
// well under 100ms, faster than an external log-poll-then-subprocess-spawn
// trigger can reliably beat. No production deployment path (the install
// script, systemd unit, or any documented config) ever sets this variable;
// when it is unset, as in every real deployment, onUpdate re-execs
// immediately, exactly as it always has.
const reExecDelayEnvOverride = "CB_AGENT_TEST_PRE_REEXEC_DELAY_MS"

// resolveReExecDelay reads reExecDelayEnvOverride. Split out from inline use
// purely so a unit test can call it directly without depending on process
// env at the actual call site.
func resolveReExecDelay() time.Duration {
	if v := os.Getenv(reExecDelayEnvOverride); v != "" {
		if ms, err := strconv.Atoi(v); err == nil && ms > 0 {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return 0
}

// installedBinaryPath is the stable, root-owned symlink systemd's
// ExecStart and an operator's interactive shell use
// (/etc/systemd/system/cb-agent.service, agent_install.py's install
// script) — see specs/2026-08-05-cb-agent-self-update-fix-design.md.
// Self-update never touches this path directly; it only ever re-points
// {stateDir}/current, the middle symlink this one points through.
const installedBinaryPath = "/usr/local/bin/cb-agent"

// watchForRollback waits up to rollbackWindow for the update marker naming
// pendingVersion to be cleared — which onConnected (wired in runDaemon)
// does exactly once, the moment a post-update connection reaches an
// accepted hello.ack (Task 4's OnConnected gating, not merely a completed
// Noise handshake). If the marker is still present and still names
// pendingVersion once the window elapses, the update never confirmed:
// watchForRollback re-points currentLink back to the marker's recorded
// prevVersionDir (update.Rollback), persists a rollback report for the next
// connection to send (this process has no live link to report over —
// that's exactly why it's rolling back), clears the marker, and re-execs
// via reExec.
//
// If the marker is still present but was never confirmed to have reached
// phasePendingConfirm (update.ReadMarker's swapped == false), then
// update.Swap never actually ran for this attempt — most likely a crash
// landed between WriteMarker and Swap in onUpdate. There is nothing to roll
// back: currentLink was never re-pointed, and prevVersionDir (if the marker
// even carries one) belongs to some earlier, already-confirmed update, not
// this one — using it here would silently downgrade a healthy running
// binary to a stale, unrelated version. The marker is simply cleared and
// the abandoned attempt logged.
//
// reExec is a parameter rather than a direct syscall.Exec call so tests can
// observe a rollback decision without actually replacing the test binary's
// process image; runDaemon passes a closure that does call syscall.Exec.
func watchForRollback(stateDir, currentLink, pendingVersion string, reExec func() error) {
	time.Sleep(rollbackWindow)

	v, prevVersionDir, swapped, stillPresent, err := update.ReadMarker(stateDir)
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
	if err := update.Rollback(currentLink, prevVersionDir); err != nil {
		// Rollback failed (empty prevVersionDir, a symlink error, ...): the
		// marker must still be cleared here. Leaving it in place
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

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	rt, err := startDaemonState(cfg, key, AgentVersion, ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	statusWriter := rt.statusWriter
	queueReadiness := rt.queueReadiness

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
		// Order matters: the link is up before the forced report, otherwise
		// queueReadiness drops it as unlinked. This is the one forced send
		// per connection — it delivers whatever state changed during the
		// outage, and it stamps the rate-limit budget, so the reconciliation
		// ticker cannot immediately double-send behind it.
		rt.linked.Store(true)
		queueReadiness(true)
	}

	onRejected := func(reason string) {
		if err := statusWriter.SetRejected(reason); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
	}

	onDisconnected := func(cause error) {
		// Stop spending the readiness budget on frames runOnce would discard;
		// the next OnConnected re-arms the send with the newest payload.
		rt.linked.Store(false)
		if err := statusWriter.SetDisconnected(cause); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
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
		if d := resolveReExecDelay(); d > 0 {
			time.Sleep(d)
		}
		return syscall.Exec(installedBinaryPath, os.Args, os.Environ())
	}

	if err := link.Run(ctx, rt.linkOptions(cfg, key, AgentVersion, linkHooks{
		onUpdate:       onUpdate,
		onConnected:    onConnected,
		onRejected:     onRejected,
		onDisconnected: onDisconnected,
	})); err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}

// linkHooks are the connection-lifecycle handlers runDaemon owns rather than
// startDaemonState: each turns a connection event into an update-marker
// decision, a re-exec or a status-file write, and those depend on runDaemon's
// own process-lifetime state (the confirm-once guard, the current-version
// symlink, os.Args) rather than on anything daemonRuntime holds.
//
// The zero value is legal, because link.Run nil-defaults every one of these
// four — which is what lets a test drive the *inbound* bindings without an
// update marker, a status file or a re-exec target.
type linkHooks struct {
	onUpdate       func(payload json.RawMessage, send link.SendUpdateStatus) error
	onConnected    func()
	onRejected     func(reason string)
	onDisconnected func(cause error)
}

// linkOptions assembles the one link.Options the daemon runs with.
//
// It is a method on daemonRuntime rather than a literal inside runDaemon
// because these bindings are the *only* delivery path for a server -> agent
// frame, and a missing one is not a compile error — it is a frame type the
// agent decodes, accepts, and silently drops. That is exactly how
// `discovery.request` came to be unwired: the runtime was constructed,
// configured and started, its own tests passed, and nothing ever handed it a
// dispatch, so a scan job sat at `running` until its dispatch deadline
// expired. Reachable options are what let a test assert the bindings rather
// than trust them.
func (rt *daemonRuntime) linkOptions(
	cfg *config.Config, key *enroll.DeviceKey, agentVersion string, hooks linkHooks,
) link.Options {
	return link.Options{
		Config: cfg, Key: key, AgentVersion: agentVersion,
		StateDir:          config.StateDir(),
		OnCapabilitiesSet: rt.onCapabilitiesSet,
		// All four are their runtime's own methods rather than wrappers: they
		// run on link's inbound goroutine, and internal/collect/probe's and
		// internal/collect/discover's contract is precisely that none of them
		// dials, resolves nor blocks on a consumer there. Anything wrapped
		// around them would be a place for that property to be lost.
		OnProbeAssign:      rt.probeRuntime.Assign,
		OnProbeCancel:      rt.probeRuntime.Cancel,
		OnDiscoveryRequest: rt.discoverRuntime.Request,
		OnDiscoveryCancel:  rt.discoverRuntime.Cancel,
		OnUpdate:           hooks.onUpdate,
		OnConnected:        hooks.onConnected,
		OnRejected:         hooks.onRejected,
		OnDisconnected:     hooks.onDisconnected,
		ReportPendingUpdateOutcome: func() (string, bool) {
			version, ok, _ := update.ReadRollbackReport(config.StateDir())
			return version, ok
		},
		ClearPendingUpdateOutcome: func() {
			if err := update.ClearRollbackReport(config.StateDir()); err != nil {
				log.Printf("cb-agent: %v", err)
			}
		},
		Spool:         rt.sp,
		DataFrames:    rt.dataFrames,
		ControlFrames: rt.controlFrames,
		OnSpoolStats: func(depth int, bytes int64) {
			if err := rt.statusWriter.SetSpoolStats(depth, bytes); err != nil {
				log.Printf("cb-agent: status: %v", err)
			}
		},
	}
}

// daemonRuntime is everything startDaemonState builds and runDaemon needs
// afterwards: the capability gate, the runtime status writer, the outbound
// data-frame spool, the two frame channels link.Run drains, the probe and
// discovery runtimes that linkOptions binds link's inbound callbacks to
// (probe.assign/probe.cancel and discovery.request/discovery.cancel
// respectively), the closures (queueReadiness, publishReadiness,
// applyHostConfig, applyProbeConfig, applyDiscoveryConfig) that the link's
// callbacks fire, and the linked flag those callbacks flip.
// Bundling them in a struct is what lets the startup sequence be exercised by
// a test without executing the full daemon (link.Run, signal handling, the
// update-rollback watcher).
type daemonRuntime struct {
	capGate       *capability.Gate
	statusWriter  *status.Writer
	sp            *spool.Spool
	dataFrames    chan frame.Frame
	controlFrames chan frame.Frame

	// linked mirrors the link's connected state. runOnce discards control
	// frames until the connection is established (internal/link), so
	// queueReadiness consults it before spending the readiness budget on a
	// frame that would be thrown away. runDaemon's OnConnected/OnDisconnected
	// own the writes.
	linked *atomic.Bool

	// probeRuntime executes server-assigned monitor checks. It exists whether
	// or not `remote_probe` is granted — applyProbeConfig is what enables or
	// disables it — so linkOptions can bind link's callbacks to it
	// unconditionally and an assignment sent to an ungranted agent is refused
	// with a `rejected` result instead of being silently swallowed.
	probeRuntime *probecollect.Runtime

	// discoverRuntime executes server-dispatched local-network discovery. Like
	// probeRuntime it exists whether or not `local_discovery` is granted, and for
	// a sharper reason than symmetry: once the grant is off, the backend's own
	// grant gate (agent_link.dispatch_frame) drops this agent's terminal
	// discovery.finding, so a dispatch that arrived at a nil handler would be a
	// scan job nothing ever closes — it would hang for its whole dispatch
	// deadline. A constructed runtime refuses it with a terminal `rejected`
	// summary instead, which is the frame that closes the job.
	discoverRuntime *discovercollect.Runtime

	queueReadiness   func(force bool)
	publishReadiness func(items []frame.Readiness)
	applyHostConfig  func()
	// applyProbeConfig re-reads the gate's `remote_probe` grant and pushes the
	// scope and concurrency it names into probeRuntime, or disables it. It is
	// called from onCapabilitiesSet directly rather than from a
	// capability.Gate.Changes() subscription: that channel delivers at most
	// one coalesced signal, nothing consumes it, and a consumer would race the
	// direct call applyHostConfig already makes.
	applyProbeConfig func()
	// applyDiscoveryConfig is applyProbeConfig's counterpart for
	// `local_discovery`: it re-derives this host's scope, rebuilds the validator
	// from the gate's current grant and pushes both into discoverRuntime, or
	// disables it outright. Called from onCapabilitiesSet for the same reason
	// applyProbeConfig is, and never from a Gate.Changes() subscription.
	//
	// Rebuilding the validator rather than the runtime is the whole of Task 14's
	// grant-change path: nothing restarts, every dispatch in flight keeps running,
	// and the next request is judged against the new authorization.
	applyDiscoveryConfig func()

	// onCapabilitiesSet is the capabilities.set handler internal/link fires.
	// It lives here rather than in runDaemon because it is the thing that
	// turns a server grant payload into installed state plus the readiness
	// rows that report what could not be honored (D-6), and that is startup
	// state, not link plumbing.
	onCapabilitiesSet func(payload json.RawMessage) error
}

// newHostCollector constructs the host-telemetry collector applyHostConfig
// installs. It is a var rather than a direct call purely as a test seam —
// startDaemonState's defining property is that it starts the collector
// goroutine, and no test may read the real /proc or /sys. Production never
// reassigns it. (Same pattern as rollbackWindow above.)
var newHostCollector = func(cfg capability.HostConfig) collect.Collector {
	return hostcollect.New(cfg)
}

// newProbeRuntime, probeReadiness and hostNetworkFacts are the probe half of
// the same seam, and exist for the same reason: the production checkers open
// real sockets, readiness opens an unprivileged ICMP socket, and the scope
// evaluator's input is whatever interfaces the machine happens to have. No
// test may depend on any of the three. Production never reassigns them.
var newProbeRuntime = func(out chan<- frame.Frame) *probecollect.Runtime {
	return probecollect.New(out, probecollect.Options{})
}

var probeReadiness = probecollect.Readiness

// newDiscoverRuntime and discoverReadiness are the discovery half of the same
// seam, for the same reason again: the production collectors open ICMP and TCP
// sockets, and readiness dumps the kernel's neighbor cache, opens an
// unprivileged ICMP socket and reads this machine's resolver configuration. No
// test may depend on any of it. Production never reassigns either.
//
// The runtime is constructed with RuntimeOptions' defaults for every collector
// and with no Validator, deliberately: a Runtime without one scans nothing, so a
// wiring mistake reads as a refusal rather than as an approval. applyDiscoveryConfig
// installs the real one, built from the grant, before the first request can arrive.
var newDiscoverRuntime = func(out chan<- frame.Frame) *discovercollect.Runtime {
	return discovercollect.NewRuntime(out, discovercollect.RuntimeOptions{})
}

// discoverReadiness takes a context where probeReadiness takes none, because one
// of discovery's four checks is a real kernel round trip (see discover.Readiness).
// The daemon's own lifetime context is what bounds it, so a wedged netlink socket
// cannot outlive the daemon that asked.
var discoverReadiness = discovercollect.Readiness

// hostNetworkFacts reports this host's directly connected networks. It has two
// readers: netscope.Derive needs them to turn the server's grant config into
// the scope this agent enforces for itself (§3), and every capability.readiness
// frame carries them so the server's copy is refreshed mid-session rather than
// only at reconnect (Slice 4 D-8). It is hostinfo's own hello enumerator, not a
// second one — the server compares the two reports for equality to decide
// whether the scope generation moved, so two enumerators that disagreed by a
// single sort order would churn it forever.
//
// It is re-read on every call rather than captured once at startup, so an
// interface that comes up after the daemon started is reflected at the next
// readiness report instead of at the next restart.
var hostNetworkFacts = hostinfo.Networks

// probeInterfaceFacts re-labels the hello report as the scope evaluator's
// input. The two structs carry identical JSON, but internal/netscope must not
// import internal/frame (the backend decodes the same facts out of
// agent_networks.facts), so the copy lives here rather than becoming a
// dependency edge.
func probeInterfaceFacts(networks []frame.NetworkFacts) []netscope.InterfaceFacts {
	facts := make([]netscope.InterfaceFacts, 0, len(networks))
	for _, n := range networks {
		facts = append(facts, netscope.InterfaceFacts{Name: n.Name, Flags: n.Flags, Addrs: n.Addrs})
	}
	return facts
}

// startDaemonState performs the daemon's startup sequence in the one order
// that is actually safe, and hands runDaemon back everything that sequence
// produced. The order is load-bearing, top to bottom:
//
//  1. auditStateDir — before any daemon-loop state write (see its doc
//     comment). Nothing below may run against a state directory this process
//     does not own.
//  2. the capability gate, restored from its cached grant, so step 5 knows
//     whether host telemetry is granted at all.
//  3. the status writer, fully constructed and seeded with the cached grants
//     and the startup identity readiness, *before* step 5 captures it. This
//     is what removes the data race: the collector goroutine step 6 starts
//     reads statusWriter, and a nil-then-assign ordering made that read
//     unsynchronized (and silently swallowed the first readiness report).
//  4. the spool — spool.Open's unclean-shutdown recovery must be reflected in
//     status.json before the first connection attempt.
//  5. the readiness/collector closures, which capture 2, 3 and 4.
//  6. the probe and discovery runtimes and their apply*Config closures, which
//     capture 5. Both runtimes are constructed and started here, before the
//     gate's grant is pushed into either, so linkOptions can bind link's probe and
//     discovery callbacks to them unconditionally — work dispatched to an
//     ungranted agent is then refused with a terminal `rejected` frame, which is
//     what closes the server-side run or job, rather than dropped on a nil
//     handler.
//  7. the readiness reconciliation ticker, which only offers the report
//     built by 5 to the link.
//  8. applyHostConfig(), applyProbeConfig() and applyDiscoveryConfig() last,
//     because they are the steps that start the collector goroutine — whose very
//     first collection fires immediately — and open (or actively close) this
//     agent's probe and discovery scopes.
//
// ctx is the daemon's lifetime context; the collector goroutine and both
// runtimes' workers are children of it, so canceling ctx stops all three.
func startDaemonState(cfg *config.Config, key *enroll.DeviceKey, agentVersion string, ctx context.Context) (*daemonRuntime, error) {
	// (1) Audit the dedicated-user file-permission model
	// (specs/2026-07-26-cb-agent-design.md §4.1) before this daemon writes
	// any state: identity (device.key), cached grant (grants.json), and
	// runtime status (status.json) must all be owned by the user this
	// process is actually running as, and mode 0600. Ownership drift aborts
	// startup outright (see auditStateDir's doc comment); mode drift is
	// corrected in place.
	if err := auditStateDir(config.StateDir(), os.Geteuid(), os.Getegid()); err != nil {
		return nil, err
	}

	// (2) The capability gate, restored from its on-disk cache — a restart
	// while disconnected must not make the agent forget its last-known
	// grants. A corrupt or unreadable cache is logged and treated as "no
	// grants", never as a startup failure.
	capGate := capability.New(config.StateDir())
	// Faults isolate per capability (D-6): one unreadable cached grant no
	// longer costs the agent every capability it had. They are held here and
	// published once publishReadiness exists, so the daemon re-reports them
	// on its first connection instead of swallowing them.
	cachedGrantFaults, err := capGate.LoadCached()
	if err != nil {
		log.Printf("cb-agent: %v", err)
	}

	// (3) statusWriter is the source `cb-agent status` reads from — see
	// internal/status. It is constructed here, before anything captures it,
	// and seeded with the cached grants and the readiness this host can
	// report before any link attempt (readiness has no network dependency —
	// see hostinfo.Collect). MergeReadiness, not a whole-slice replacement,
	// so the collector's own host.* rows and this identity row coexist.
	identityReadiness := hostinfo.Collect(agentVersion).Readiness
	statusWriter := status.NewWriter(config.StateDir(), agentVersion, key.FingerprintGrouped())
	if err := statusWriter.SetGrants(capGate.Grants()); err != nil {
		log.Printf("cb-agent: status: %v", err)
	}
	if err := statusWriter.MergeReadiness(identityReadiness); err != nil {
		log.Printf("cb-agent: status: %v", err)
	}

	// (4) sp is the outbound *data* frame spool (internal/spool) — never
	// heartbeat/control traffic, see frame.IsDataFrame. Opening it here, at
	// daemon startup and before the link ever connects, is what makes an
	// unclean shutdown's persisted backlog recover (spool.Open's load()) and
	// become visible in `cb-agent status` before this run's first connection
	// attempt even completes.
	sp, err := openSpool(cfg, config.StateDir(), statusWriter)
	if err != nil {
		return nil, err
	}

	// (5) The closures. readinessState is the daemon's single source of
	// truth for collector readiness: publishReadiness upserts into it and is
	// the *only* producer of readinessPayload, so the collector, the
	// capability-disable path and any future collector all report through
	// one sink and every frame carries the full merged set. It is seeded
	// with the startup identity report because the backend never persists
	// hello.readiness — capability.readiness is the only ingest path, so an
	// entry that travels only in hello never reaches the server at all.
	// queueReadiness rate-limits those frames to one per
	// readinessReportInterval unless forced (a changed report, or a fresh
	// connection); applyHostConfig (re)installs the host collector to match
	// the gate's current grant.
	dataFrames := make(chan frame.Frame, 8)
	controlFrames := make(chan frame.Frame, 8)
	// The interface enumerator is captured here, once, rather than read from
	// its package var at each use. publishReadiness runs on the host
	// collector's own goroutine as well as on the link's, and a test that
	// restores the seam in t.Cleanup while that goroutine is still collecting
	// would race with it. Production never reassigns it, so the capture costs
	// nothing and makes the seam a construction-time one.
	networkFacts := hostNetworkFacts
	var linked atomic.Bool
	var readinessMu sync.Mutex
	readinessState := make(map[string]frame.Readiness, len(identityReadiness)+len(hostcollect.CollectorNames))
	for _, r := range identityReadiness {
		readinessState[r.Collector] = r
	}
	var readinessPayload json.RawMessage
	var readinessSentAt time.Time
	// The last networks report that was actually enumerated. capability.readiness
	// carries `networks` with no omitempty (D-8) so that an agent which has lost
	// every interface can send `[]` and replace the server's copy — which means
	// there is no encoding for "I could not look". hostinfo.Networks returns nil
	// for exactly that case, and sending it as `[]` would tell the server every
	// interface was gone: a wiped scope and a bumped generation every time
	// /sys/class/net was momentarily unreadable. Repeating the last real report
	// is the one answer that is true either way, and record_network_facts'
	// change gate makes the repeat free. The seed is `[]` rather than nil so the
	// very first frame is still a JSON array; an agent that has never once
	// enumerated its interfaces has nothing truer to say.
	lastNetworks := []frame.NetworkFacts{}
	// A force that has been asked for but not yet spent. The send below is
	// deliberately non-blocking — controlFrames is bounded and publishReadiness
	// runs on the host collector's goroutine, which must not stall behind the
	// link's websocket writer — so a forced frame can be dropped outright. By
	// then publishReadiness has already overwritten readinessPayload, which
	// makes the dropped change the new dedup baseline: no later publish of the
	// same state computes `changed` again, and the reconcile tick's unforced
	// call is refused by the readinessReportInterval floor. Remembering the
	// unspent force is what stops that change from being silently swallowed
	// for a whole report interval — a networks-only change (D-8) has no other
	// re-reporter, and the server would sit on a stale scope until then.
	readinessForcePending := false
	queueReadiness := func(force bool) {
		// Unlinked: runOnce drops control frames until the connection is
		// established (internal/link), so sending here would consume the
		// rate-limit budget for a frame nobody receives — and leave the
		// agent readiness-dark for up to readinessReportInterval after it
		// reconnects. Returning *without* stamping readinessSentAt is the
		// point; OnConnected's queueReadiness(true) re-arms the send.
		if !linked.Load() {
			return
		}
		readinessMu.Lock()
		defer readinessMu.Unlock()
		readinessForcePending = readinessForcePending || force
		if len(readinessPayload) == 0 || (!readinessForcePending && time.Since(readinessSentAt) < readinessReportInterval) {
			return
		}
		select {
		case controlFrames <- frame.Frame{Type: frame.TypeCapabilityReadiness, TS: time.Now().UTC(), Payload: append(json.RawMessage(nil), readinessPayload...)}:
			readinessSentAt = time.Now()
			// Only a frame that actually left clears the debt. The payload sent
			// is always the newest one, so a single send settles however many
			// forces piled up behind a busy writer.
			readinessForcePending = false
		default:
		}
	}
	publishReadiness := func(items []frame.Readiness) {
		// Enumerated before the lock: this is a syscall into the kernel's
		// interface list, and readinessMu is also taken by queueReadiness on
		// the link's own goroutine.
		networks := networkFacts()
		readinessMu.Lock()
		if networks == nil {
			networks = lastNetworks
		}
		lastNetworks = networks
		for _, r := range items {
			readinessState[r.Collector] = r
		}
		merged := make([]frame.Readiness, 0, len(readinessState))
		for _, r := range readinessState {
			merged = append(merged, r)
		}
		sort.Slice(merged, func(i, j int) bool { return merged[i].Collector < merged[j].Collector })
		// No nil guard on statusWriter: it is assigned above, before this
		// closure can exist, and the compiler enforces that via :=.
		if err := statusWriter.MergeReadiness(merged); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
		payload, err := json.Marshal(frame.CapabilityReadinessPayload{Readiness: merged, Networks: networks})
		if err != nil {
			readinessMu.Unlock()
			return
		}
		changed := !bytes.Equal(readinessPayload, payload)
		readinessPayload = payload
		readinessMu.Unlock()
		queueReadiness(changed)
	}
	var collectorMu sync.Mutex
	var hostRunner *collect.Runner
	applyHostConfig := func() {
		collectorMu.Lock()
		defer collectorMu.Unlock()
		if hostRunner != nil {
			hostRunner.Stop()
			hostRunner = nil
		}
		hostCfg, enabled := capGate.HostConfig()
		if !enabled {
			// The grant is gone, so nothing will ever report these
			// collectors again — and ingest_readiness only upserts, it never
			// deletes. Actively overwriting every host collector with
			// "disabled" is therefore the only way the server's rows stop
			// saying "Live" (D-4). Driving it off hostcollect.CollectorNames
			// rather than a local list is what keeps a newly added probe
			// from being left behind at a stale state.
			items := make([]frame.Readiness, 0, len(hostcollect.CollectorNames))
			for _, name := range hostcollect.CollectorNames {
				items = append(items, frame.Readiness{Collector: name, State: "disabled"})
			}
			publishReadiness(items)
			return
		}
		// Re-enabling needs no symmetric "enabling" report: the runner's very
		// first collection fires immediately (internal/collect's Runner.run)
		// and hostcollect.Collect populates readiness for every name in
		// CollectorNames on every run, error or not — so the disabled rows
		// above are overwritten by that first report. That coupling is the
		// reason neither list may drift from the other.
		hostRunner = collect.NewRunner(newHostCollector(hostCfg), dataFrames)
		hostRunner.OnReadiness = publishReadiness
		hostRunner.Reset(ctx, time.Duration(hostCfg.IntervalS)*time.Second)
	}

	// (6) The probe runtime. Results are data frames, so they go to
	// dataFrames — never controlFrames: probe.result spools through an outage
	// instead of being dropped while disconnected, and link's assertDataFrame
	// panics the other way round. Started before applyProbeConfig runs so
	// there is a dispatcher and a result pump waiting for the first
	// assignment; ctx is the daemon's, so a shutdown cancels every open run.
	probeRuntime := newProbeRuntime(dataFrames)
	probeRuntime.Start(ctx)
	applyProbeConfig := func() {
		cfg, granted := capGate.RemoteProbeConfig()
		if !granted {
			// Disable, not just "stop accepting": a revoked grant must stop
			// probing now rather than at the end of the current deadline, and
			// every run still open is closed out with a `cancelled` result so
			// the backend is not left waiting one out.
			probeRuntime.Disable("remote_probe is not granted on this agent")
			// The same D-4 reasoning as applyHostConfig's disable branch:
			// ingest_readiness only ever upserts, so a row nothing will report
			// again has to be actively overwritten or Agent Detail shows this
			// vantage as probe-ready forever. Driving it off
			// probecollect.ProbeNames rather than a local list is what keeps a
			// newly added check type from being left behind at a stale state.
			items := make([]frame.Readiness, 0, len(probecollect.ProbeNames))
			for _, name := range probecollect.ProbeNames {
				items = append(items, frame.Readiness{Collector: name, State: "disabled"})
			}
			publishReadiness(items)
			return
		}
		// The scope this agent enforces is derived here, from *this host's*
		// own interfaces plus the server's normalized grant config — never
		// from anything host-editable (§3, and see Gate.RemoteProbeConfig).
		// Configure needs no restart: an in-flight check keeps running, and a
		// raised concurrency limit is picked up by the dispatcher within one
		// poll.
		scope := netscope.Derive(probeInterfaceFacts(networkFacts()), cfg.Config)
		probeRuntime.Configure(scope, cfg.MaxConcurrent)
		publishReadiness(probeReadiness())
	}

	// (6b) The discovery runtime. Findings — including the terminal summary that
	// closes the scan job — are data frames, so they go to dataFrames: a
	// discovery.finding spools through an outage instead of being dropped while
	// disconnected, which is the whole reason its finding ids are replay-stable
	// digests rather than fresh samples. Started before applyDiscoveryConfig runs
	// so there is a dispatcher and a finding pump waiting for the first request;
	// ctx is the daemon's, so a shutdown cancels every open dispatch and closes
	// each of them out with a `cancelled` summary.
	discoverRuntime := newDiscoverRuntime(dataFrames)
	discoverRuntime.Start(ctx)
	applyDiscoveryConfig := func() {
		cfg, granted := capGate.LocalDiscoveryConfig()
		if !granted {
			// Disable, not just "stop accepting", for a reason sharper than the
			// probe half's: D-14 requires a revoked grant to stop scanning now,
			// and once `local_discovery` is off the backend's own grant gate
			// drops this agent's terminal discovery.finding — so a dispatch left
			// running would produce findings nobody accepts and a job nothing
			// ever closes. Disable cancels each one in flight, and each is closed
			// out with a `cancelled` summary while the grant that carries it is
			// still installed.
			discoverRuntime.Disable("local_discovery is not granted on this agent")
			// The same D-4 reasoning as the two disable branches above:
			// ingest_readiness only ever upserts, so a row nothing will report
			// again has to be actively overwritten or Agent Detail keeps reading
			// this vantage as a discovery-ready one. Driving it off
			// discover.DiscoverNames rather than a local list is what keeps a
			// newly added discovery method from being left behind at a stale
			// state, and publishing through publishReadiness is what puts these
			// rows on the same single frame Task 13 gave `networks` to.
			items := make([]frame.Readiness, 0, len(discovercollect.DiscoverNames))
			for _, name := range discovercollect.DiscoverNames {
				items = append(items, frame.Readiness{Collector: name, State: "disabled"})
			}
			publishReadiness(items)
			return
		}
		// The same derivation applyProbeConfig makes, from the same enumerator:
		// this host's own interfaces plus the server's normalized grant config,
		// never anything host-editable (§3). There is deliberately no second
		// enumerator — the server compares the facts this agent reports against
		// the ones it stored to decide whether the scope generation moved, and two
		// enumerators that disagreed would churn it forever.
		//
		// Configure needs no restart: a dispatch in flight keeps running against
		// the authorization it was admitted under, and the next request is judged
		// against this validator. A grant change that *invalidates* live work is
		// D-16's scope-version path, which the server drives with an explicit
		// discovery.cancel per dispatch, because only the server knows which jobs
		// it has already closed.
		scope := netscope.Derive(probeInterfaceFacts(networkFacts()), cfg.Config)
		discoverRuntime.Configure(scope, discovercollect.NewValidator(cfg, nil))
		publishReadiness(discoverReadiness(ctx))
	}

	// onCapabilitiesSet installs a server grant payload. Per-capability faults
	// are not frame failures — returning nil for a fault-only outcome is what
	// stops internal/link's runOnce from logging the whole capabilities.set as
	// failed — they are reported as capability.<name> = degraded through the
	// same publishReadiness sink every collector uses. Only a payload that is
	// not a grant map at all is an error, and that leaves the gate untouched.
	onCapabilitiesSet := func(payload json.RawMessage) error {
		faults, err := capGate.ApplyGrants(payload)
		if err != nil {
			return err
		}
		if err := statusWriter.SetGrants(capGate.Grants()); err != nil {
			log.Printf("cb-agent: status: %v", err)
		}
		publishReadiness(capabilityReadiness(capGate.Snapshot(), faults))
		applyHostConfig()
		applyProbeConfig()
		applyDiscoveryConfig()
		return nil
	}

	// The cached grant's faults, now that there is somewhere to report them.
	// Publishing "ready" for the capabilities that loaded cleanly is what lets
	// a corrected config clear a previously degraded row.
	publishReadiness(capabilityReadiness(capGate.Snapshot(), cachedGrantFaults))

	// (7) Reconciliation. The 15-minute floor in queueReadiness needs
	// something to push against: without this ticker the only caller is a
	// successful collection, so a disabled or persistently failing collector
	// silently stops reporting altogether — precisely the state the server
	// most needs to hear about. It queues rather than sends: queueReadiness
	// is the single funnel, and controlFrames is drained by the one
	// websocket writer in internal/link's runOnce select loop.
	go func() {
		ticker := time.NewTicker(reconcileTickInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				queueReadiness(false)
			}
		}
	}()

	// (8) Last: this starts the collector goroutine, whose first collection
	// fires immediately (internal/collect's Runner.run), and opens (or, for an
	// ungranted capability, actively closes) this agent's probe and discovery
	// scopes.
	applyHostConfig()
	applyProbeConfig()
	applyDiscoveryConfig()

	return &daemonRuntime{
		capGate:              capGate,
		statusWriter:         statusWriter,
		sp:                   sp,
		dataFrames:           dataFrames,
		controlFrames:        controlFrames,
		linked:               &linked,
		probeRuntime:         probeRuntime,
		discoverRuntime:      discoverRuntime,
		queueReadiness:       queueReadiness,
		publishReadiness:     publishReadiness,
		applyHostConfig:      applyHostConfig,
		applyProbeConfig:     applyProbeConfig,
		applyDiscoveryConfig: applyDiscoveryConfig,
		onCapabilitiesSet:    onCapabilitiesSet,
	}, nil
}

// capabilityFaultRemediation is the operator-facing instruction attached to
// every capability.<name> = degraded readiness row.
const capabilityFaultRemediation = "correct this capability's configuration in Agent Detail"

// capabilityReadiness turns an installed grant snapshot plus the faults it was
// installed with into one readiness row per capability: degraded (with the
// reason) for a capability whose configuration could not be honored as sent,
// ready for every capability that applied cleanly. Reporting the clean ones too
// is what makes a corrected configuration clear its own degraded row —
// ingest_readiness only ever upserts, so a row the UI should stop showing must
// be actively overwritten.
func capabilityReadiness(snapshot capability.Snapshot, faults []capability.GrantFault) []frame.Readiness {
	reasons := make(map[string]string, len(faults))
	for _, f := range faults {
		reasons[f.Capability] = f.Reason
	}
	items := make([]frame.Readiness, 0, len(snapshot))
	for name := range snapshot {
		if reason, ok := reasons[name]; ok {
			items = append(items, frame.Readiness{
				Collector:   "capability." + name,
				State:       "degraded",
				Reason:      reason,
				Remediation: capabilityFaultRemediation,
			})
			continue
		}
		items = append(items, frame.Readiness{Collector: "capability." + name, State: "ready"})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Collector < items[j].Collector })
	return items
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
// "/usr/local/bin/cb-agent" the binary). There is no separate backup file
// to track anymore: under the two-level symlink layout
// (specs/2026-08-05-cb-agent-self-update-fix-design.md), every versioned
// binary self-update ever installs lives under {stateDir}/versions/, which
// stateDir's own wholesale removal below already covers — unlike the old
// scheme's single <binary>+".previous" backup, sitting outside stateDir and
// needing its own explicit removal entry here.
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
	unitFile   string
	binary     string
	configFile string
	configDir  string
	stateDir   string
}

// defaultUninstallPaths is the static fallback footprint. binary is a
// placeholder here — resolveUninstallPaths always overrides it with
// installedBinaryPath before this is ever passed to performUninstall in
// production; defaultUninstallPaths itself is used directly only as
// resolveUninstallPaths' fallback base for every other field.
var defaultUninstallPaths = uninstallPaths{
	unitFile:   "/etc/systemd/system/cb-agent.service",
	binary:     installedBinaryPath,
	configFile: "/etc/circuit-breaker/agent.toml",
	configDir:  "/etc/circuit-breaker",
	stateDir:   config.StateDir(),
}

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

	for _, path := range []string{paths.unitFile, paths.binary, paths.configFile, paths.stateDir} {
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
