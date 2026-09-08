// `cb-agent uninstall`: stop the unit, tell the server, and remove what the
// installer put on disk.
//
// Paths and the systemctl runner are indirected through variables so the
// removal can be tested without root and without touching a real system.

package main

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"strings"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/link"
)

// runUninstall is the `cb-agent uninstall` entry point (spec §4.7): it
// requires root (disabling a systemd unit and removing root-owned files
// under /etc and /usr/local/bin isn't possible otherwise), tells the server
// so the agent's row flips to revoked (see notifyUninstallBestEffort), then
// actually disables/removes/reloads — unlike this function's pre-Task-29 form,
// which only ever printed the systemctl/rm commands for an operator to run by
// hand.
//
// Removal happens whether or not the server was reached; only the exit status
// and the printed line distinguish the outcomes. That order — notify first,
// remove second — is deliberate: the config and device identity the notify
// needs are among the things removal deletes.
func runUninstall() {
	if err := requireRoot(os.Geteuid()); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	notifyLine, notifyToStderr, notifyFailed := uninstallNotifyReport(notifyUninstallBestEffort())
	if notifyToStderr {
		fmt.Fprintln(os.Stderr, notifyLine)
	} else {
		fmt.Println(notifyLine)
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

	// An unconfirmed notify counts towards the exit status, alongside the
	// on-disk failures. Local removal succeeded either way and the message
	// above says so, but a server that still lists this agent is unfinished
	// work: automation decommissioning a fleet has to be able to see that it
	// left records behind, and exit 0 is how it is told there is nothing left
	// to do.
	if result.DisableErr != nil || len(result.RemoveErrs) > 0 ||
		result.ReloadErr != nil || notifyFailed {
		os.Exit(1)
	}
}

// errNoLocalAgent means there is nothing on this host for the server to be told
// about: no config file, or no device identity beside it. It is a success, not a
// failure — a second `cb-agent uninstall` run after a completed first one lands
// here, as does a host that was never enrolled, and removal is idempotent by
// design (see performUninstall). Reporting it as a failure would make the second
// run of an idempotent command exit non-zero.
var errNoLocalAgent = errors.New("no enrolled agent on this host")

// uninstallNotifyReport turns one notify outcome into the line the operator
// sees, where it goes, and whether it fails the command.
//
// Split out as a pure function because it is the part with the actual contract
// in it: the old code had two branches, printed "Notified the server (agent
// record marked revoked)" on a nil error that was returned unconditionally, and
// let a failed notify exit 0. Three outcomes, and only one of them leaves the
// operator with something to do.
func uninstallNotifyReport(err error) (line string, toStderr bool, failed bool) {
	switch {
	case err == nil:
		return "Notified the server (agent record marked revoked).", false, false
	case errors.Is(err, errNoLocalAgent):
		return "No enrolled agent found on this host; the server has nothing to be told.", false, false
	default:
		return fmt.Sprintf(
			"cb-agent: the server did NOT confirm this uninstall: %v\n"+
				"cb-agent: local removal continues, but this agent may still be listed as "+
				"active — revoke it in Settings → Agents.", err), true, true
	}
}

// notifyUninstallBestEffort tells the server this agent is going away, and
// returns nil only when the server confirmed it (see link.Uninstall for what
// that confirmation is and why an unconfirmed one used to be indistinguishable
// from success).
//
// Best-effort still describes the *caller*: runUninstall removes files whatever
// happens here, because an unreachable or already-decommissioned server must
// never block an operator from removing an agent from their own host. What is no
// longer best-effort is the reporting — see uninstallNotifyReport.
//
// A missing config or identity returns errNoLocalAgent rather than a failure:
// there is nothing here to tell the server about.
func notifyUninstallBestEffort() error {
	cfg, err := config.Load(uninstallConfigPath)
	if errors.Is(err, fs.ErrNotExist) {
		return errNoLocalAgent
	}
	if err != nil {
		return err
	}
	// LoadDeviceKey, not LoadOrCreateDeviceKey. The load-or-create form turned
	// a missing identity into a *newly minted* one, opened a Noise session with
	// a static key the server has never seen, and got the connection closed at
	// `resolve_agent_for_handshake` — after which the old unconditional `return
	// nil` reported success. Uninstall is the one command that must never
	// create an identity, and a missing one is not a failure either: there is
	// simply nothing here to tell the server about.
	key, ok, err := enroll.LoadDeviceKey(config.StateDir())
	if err != nil {
		return err
	}
	if !ok {
		return errNoLocalAgent
	}
	return notifyUninstall(cfg, key)
}

func notifyUninstall(cfg *config.Config, key *enroll.DeviceKey) error {
	ctx, cancel := context.WithTimeout(context.Background(), uninstallNotifyTimeout)
	defer cancel()
	return link.Uninstall(ctx, link.Options{
		Config: cfg,
		Key:    key,
		// StateDir was missing, and it is not cosmetic: link.ResolveTrust reads
		// the *promoted* TLS trust policy and any pending pin rotation from
		// there, and returns agent.toml's original pin when it is empty. On a
		// host that has been through a certificate rotation, agent.toml names
		// the retired certificate — so the notify could not connect at all,
		// and the uninstall would silently leave the agent listed as active.
		StateDir: config.StateDir(),
		// Reported on the hello this connection sends, so the server records
		// what actually uninstalled rather than an empty version string.
		AgentVersion: AgentVersion,
	})
}

// uninstallNotifyTimeout bounds the whole notify: dial, handshake, hello,
// uninstall frame, and the wait for the server's acknowledgement. The server
// coalesces delivery acknowledgements at 4 frames or ~1s, so a healthy server
// answers in about a second; the rest of the budget is for a slow or loaded one.
// An operator's terminal must not hang here — an unconfirmed uninstall is a
// reported outcome, not a reason to wait indefinitely.
const uninstallNotifyTimeout = 10 * time.Second

// uninstallConfigPath is this agent's own config file, and the file whose
// absence means nothing was ever enrolled here. A variable rather than a
// constant for the same reason the paths and the systemctl runner below are
// indirected: so the notify path can be tested without /etc.
var uninstallConfigPath = "/etc/circuit-breaker/agent.toml"

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
	configFile: uninstallConfigPath,
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
