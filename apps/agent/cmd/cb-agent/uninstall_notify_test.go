package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"circuitbreaker.dev/cb-agent/internal/link"
)

// What `cb-agent uninstall` is allowed to tell an operator about the server.
//
// It used to print "Notified the server (agent record marked revoked)" on the
// strength of link.Uninstall returning nil, which it did unconditionally. The
// server was in fact never revoking anything (see link.Uninstall's own
// comment), so the one line an operator had to go on was false on every run.
//
// Now the notify has three distinguishable outcomes, and each has a different
// consequence for the operator: confirmed (nothing left to do), nothing here to
// notify about (also nothing left to do — a second run, or a host that was
// never enrolled), and unconfirmed (a record they have to revoke by hand). The
// command's exit status has to separate the last one from the first two, or
// automation removing a fleet cannot tell that it left records behind.

func TestUninstallNotifyReport_ConfirmedIsSuccessOnStdout(t *testing.T) {
	line, toStderr, failed := uninstallNotifyReport(nil)

	if failed {
		t.Error("a confirmed notify must not fail the command")
	}
	if toStderr {
		t.Error("a confirmed notify is not a diagnostic")
	}
	if !strings.Contains(line, "revoked") {
		t.Errorf("line = %q, want it to say the record was revoked", line)
	}
}

func TestUninstallNotifyReport_NothingEnrolledIsSuccess(t *testing.T) {
	line, _, failed := uninstallNotifyReport(errNoLocalAgent)

	if failed {
		t.Error("a host with no enrolled agent has nothing to confirm and must not fail — " +
			"a second `cb-agent uninstall` run lands here and removal is idempotent")
	}
	if strings.Contains(line, "revoked") {
		t.Errorf("line = %q, must not claim a revoke that never happened", line)
	}
}

func TestUninstallNotifyReport_UnconfirmedFailsAndNamesTheRemedy(t *testing.T) {
	line, toStderr, failed := uninstallNotifyReport(link.ErrUninstallUnconfirmed)

	if !failed {
		t.Error("an unconfirmed notify leaves a live agent record on the server; the command " +
			"must not exit 0 and let automation believe the host is gone")
	}
	if !toStderr {
		t.Error("an unconfirmed notify is a diagnostic")
	}
	// The operator's actual next action, not just a complaint.
	if !strings.Contains(line, "revoke") {
		t.Errorf("line = %q, want it to tell the operator to revoke the agent themselves", line)
	}
}

func TestUninstallNotifyReport_UnreachableServerFailsToo(t *testing.T) {
	_, _, failed := uninstallNotifyReport(errors.New("link: dial: connection refused"))

	if !failed {
		t.Error("a server that could not be reached was not told either")
	}
}

func TestNotifyUninstallBestEffort_MissingConfigIsNothingToNotify(t *testing.T) {
	t.Setenv("CB_AGENT_STATE_DIR", t.TempDir())
	withUninstallConfigPath(t, filepath.Join(t.TempDir(), "absent.toml"))

	err := notifyUninstallBestEffort()

	if !errors.Is(err, errNoLocalAgent) {
		t.Fatalf("error = %v, want errNoLocalAgent — no config means nothing was ever enrolled here", err)
	}
}

// The identity check is load-bearing, and it used to be the opposite of one.
func TestNotifyUninstallBestEffort_MissingIdentityDoesNotMintOne(t *testing.T) {
	stateDir := t.TempDir()
	t.Setenv("CB_AGENT_STATE_DIR", stateDir)

	configPath := filepath.Join(t.TempDir(), "agent.toml")
	// A syntactically valid config pointing at a server that must never be
	// dialed: reaching the dial at all is the failure this test describes.
	if err := os.WriteFile(configPath, []byte(
		"server_url = \"https://127.0.0.1:1\"\nserver_static_pk = \""+
			strings.Repeat("ab", 32)+"\"\n"), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}
	withUninstallConfigPath(t, configPath)

	err := notifyUninstallBestEffort()

	if !errors.Is(err, errNoLocalAgent) {
		t.Fatalf("error = %v, want errNoLocalAgent", err)
	}
	// enroll.LoadOrCreateDeviceKey — what this used to call — would have
	// generated a brand-new keypair here and opened a Noise session the server
	// has never seen, which it answers by closing the connection. The old code
	// then reported success anyway. A key file appearing during an *uninstall*
	// is the visible symptom of that.
	if entries, err := os.ReadDir(stateDir); err != nil {
		t.Fatalf("read state dir: %v", err)
	} else if len(entries) != 0 {
		names := make([]string, 0, len(entries))
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("uninstall created %v in the state directory — it must never mint an identity "+
			"to say goodbye with", names)
	}
}

// withUninstallConfigPath points the notify path at a test config for the
// duration of one test, mirroring how this file already indirects paths and the
// systemctl runner so removal can be tested without root.
func withUninstallConfigPath(t *testing.T, path string) {
	t.Helper()
	previous := uninstallConfigPath
	uninstallConfigPath = path
	t.Cleanup(func() { uninstallConfigPath = previous })
}
