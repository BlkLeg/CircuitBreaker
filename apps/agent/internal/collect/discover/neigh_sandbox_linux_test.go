//go:build linux && (amd64 || arm64)

// Constrained to the two architectures the agent ships (Makefile build-all), because the seccomp
// filter below needs the architecture's audit arch and little-endian argument layout. Elsewhere
// these tests are not compiled rather than skipped.

package discover

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"unsafe"

	"golang.org/x/sys/unix"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// TestNetlinkSocketError_ClassifiesPolicyRefusals pins which socket() errnos are the sandbox.
// EAFNOSUPPORT is what systemd's RestrictAddressFamilies returns and is the RISK-011 signature;
// EPERM and EACCES are seccomp and LSM refusals. A resource limit is not a policy and must keep
// the generic row, or the fleet list would name hosts whose unit is fine.
func TestNetlinkSocketError_ClassifiesPolicyRefusals(t *testing.T) {
	for _, tc := range []struct {
		errno   unix.Errno
		blocked bool
	}{
		{unix.EAFNOSUPPORT, true},
		{unix.EPERM, true},
		{unix.EACCES, true},
		{unix.EMFILE, false},
		{unix.ENOBUFS, false},
		{unix.EPROTONOSUPPORT, false},
	} {
		t.Run(tc.errno.Error(), func(t *testing.T) {
			err := netlinkSocketError(tc.errno)
			if got := errors.Is(err, ErrNetlinkBlocked); got != tc.blocked {
				t.Errorf("errors.Is(%v, ErrNetlinkBlocked) = %v, want %v", err, got, tc.blocked)
			}
			// The kernel's errno must survive the wrap either way: Reason is built from it, and a
			// caller matching the errno itself must not be broken by the classification.
			if !errors.Is(err, tc.errno) {
				t.Errorf("errors.Is(%v, %v) = false, want the errno kept in the chain", err, tc.errno)
			}
			if !strings.HasPrefix(err.Error(), "discover: open netlink socket: ") {
				t.Errorf("error = %q, want the existing open-netlink-socket prefix", err)
			}
		})
	}
}

// sandboxChildEnv selects the child half of TestNeighbors_UnderAnAddressFamilyFilter. The value
// is the errno the filter returns for socket(AF_NETLINK, ...).
const sandboxChildEnv = "CB_AGENT_TEST_NETLINK_FILTER_ERRNO"

// TestNeighbors_UnderAnAddressFamilyFilter reproduces the broken install for real rather than by
// injecting an error: it re-runs this test binary under a seccomp filter that refuses
// socket(AF_NETLINK, ...) with the errno under test — the same kernel mechanism, and for
// EAFNOSUPPORT the same errno, that systemd's RestrictAddressFamilies installs — and asserts that
// the real Neighbors() and the real Readiness() classify it as the sandbox and name the unit fix.
//
// The filter lives in a child process because a seccomp filter can never be removed; installing it
// in the test binary itself would break every test that runs afterwards.
func TestNeighbors_UnderAnAddressFamilyFilter(t *testing.T) {
	if v := os.Getenv(sandboxChildEnv); v != "" {
		runSandboxedChild(v)
		return
	}
	for _, errno := range []unix.Errno{unix.EAFNOSUPPORT, unix.EPERM} {
		t.Run(errno.Error(), func(t *testing.T) {
			cmd := exec.Command(os.Args[0], "-test.run=^TestNeighbors_UnderAnAddressFamilyFilter$", "-test.count=1")
			cmd.Env = append(os.Environ(), sandboxChildEnv+"="+strconv.Itoa(int(errno)))
			out, err := cmd.CombinedOutput()
			text := string(out)
			// Not a skip: an unprivileged process may always install a filter once it has set
			// no_new_privs, so a refusal means the harness itself is confined in a way the agent's
			// unit is not — and a skipped test here would prove nothing, silently.
			if strings.Contains(text, "SECCOMP-UNAVAILABLE") {
				t.Fatalf("could not install the test's seccomp filter: %s", text)
			}
			if err != nil {
				t.Fatalf("sandboxed child failed: %v\n%s", err, text)
			}
			for _, want := range []string{
				"blocked=true",
				"errno=true",
				"state=unavailable",
				"missing=" + MissingAFNetlink,
				"remediation=" + netlinkBlockedRemediation,
				// net.Interfaces needs the same socket, which is why the affected host's scope is
				// empty too. Asserting it here keeps the doc comment on ErrNetlinkBlocked honest.
				"interfaces_err=true",
			} {
				if !strings.Contains(text, want+"\n") {
					t.Errorf("sandboxed child output is missing %q:\n%s", want, text)
				}
			}
		})
	}
}

// runSandboxedChild installs the filter and reports what the agent's own code paths said. It
// writes plain lines to stdout and exits, never returning into the test framework, because the
// framework itself may need socket families the filter does not care about but whose failure
// would be confusing to read back.
func runSandboxedChild(value string) {
	n, err := strconv.Atoi(value)
	if err != nil {
		fmt.Printf("bad %s=%q\n", sandboxChildEnv, value)
		os.Exit(2)
	}
	errno := unix.Errno(n)
	if err := installNetlinkFilter(errno); err != nil {
		fmt.Printf("SECCOMP-UNAVAILABLE: %v\n", err)
		os.Exit(0)
	}

	_, nerr := Neighbors(context.Background())
	fmt.Printf("blocked=%v\n", errors.Is(nerr, ErrNetlinkBlocked))
	fmt.Printf("errno=%v\n", errors.Is(nerr, errno))

	row := neighborReadiness(context.Background(), nil)
	fmt.Printf("state=%s\n", row.State)
	fmt.Printf("missing=%s\n", strings.Join(row.Missing, ","))
	fmt.Printf("remediation=%s\n", row.Remediation)

	_, ierr := net.Interfaces()
	fmt.Printf("interfaces_err=%v\n", ierr != nil)
	os.Exit(0)
}

// auditArch is the seccomp_data.arch value for this build's architecture; the build constraint
// limits this file to the two the agent ships.
func auditArch() (uint32, bool) {
	switch runtime.GOARCH {
	case "amd64":
		return unix.AUDIT_ARCH_X86_64, true
	case "arm64":
		return unix.AUDIT_ARCH_AARCH64, true
	default:
		return 0, false
	}
}

// installNetlinkFilter installs, on every thread of this process, a seccomp filter that fails
// socket(AF_NETLINK, ...) with errno and allows everything else. It is the shape of systemd's
// RestrictAddressFamilies filter reduced to the one family this test cares about.
func installNetlinkFilter(errno unix.Errno) error {
	arch, ok := auditArch()
	if !ok {
		return fmt.Errorf("unsupported GOARCH %s", runtime.GOARCH)
	}
	// struct seccomp_data { int nr; __u32 arch; __u64 instruction_pointer; __u64 args[6]; }.
	// Both shipped architectures are little-endian, so args[0]'s low word is at offset 16.
	const (
		offNr    = 0
		offArch  = 4
		offArg0  = 16
		ldAbs    = unix.BPF_LD | unix.BPF_W | unix.BPF_ABS
		jeqK     = unix.BPF_JMP | unix.BPF_JEQ | unix.BPF_K
		retK     = unix.BPF_RET | unix.BPF_K
		retAllow = unix.SECCOMP_RET_ALLOW
	)
	filter := []unix.SockFilter{
		{Code: ldAbs, K: offArch},
		{Code: jeqK, Jt: 0, Jf: 5, K: arch},
		{Code: ldAbs, K: offNr},
		{Code: jeqK, Jt: 0, Jf: 3, K: uint32(unix.SYS_SOCKET)},
		{Code: ldAbs, K: offArg0},
		{Code: jeqK, Jt: 0, Jf: 1, K: unix.AF_NETLINK},
		{Code: retK, K: unix.SECCOMP_RET_ERRNO | (uint32(errno) & unix.SECCOMP_RET_DATA)},
		{Code: retK, K: retAllow},
	}
	prog := unix.SockFprog{Len: uint16(len(filter)), Filter: &filter[0]}

	if err := unix.Prctl(unix.PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0); err != nil {
		return fmt.Errorf("PR_SET_NO_NEW_PRIVS: %w", err)
	}
	// TSYNC, because the Go runtime already has several threads and the filter must reach the
	// one Neighbors happens to run on.
	if _, _, e := unix.Syscall(unix.SYS_SECCOMP, unix.SECCOMP_SET_MODE_FILTER, unix.SECCOMP_FILTER_FLAG_TSYNC, uintptr(unsafe.Pointer(&prog))); e != 0 {
		return fmt.Errorf("seccomp(SET_MODE_FILTER): %w", e)
	}
	runtime.KeepAlive(filter)
	return nil
}

// corpusNeighborRow returns the discovery.neighbor row of the fixtures/agent_frame_corpus.json
// entry whose description starts with prefix. The backend's fleet list is tested against those
// same entries, so this is where the agent's real output and the server's matcher meet.
func corpusNeighborRow(t *testing.T, prefix string) frame.Readiness {
	t.Helper()
	// internal/collect/discover -> repo root is five levels up.
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "..", "fixtures", "agent_frame_corpus.json"))
	if err != nil {
		t.Fatalf("read corpus: %v", err)
	}
	var entries []struct {
		Description string `json:"description"`
		JSON        struct {
			Payload frame.CapabilityReadinessPayload `json:"payload"`
		} `json:"json"`
	}
	if err := json.Unmarshal(data, &entries); err != nil {
		t.Fatalf("unmarshal corpus: %v", err)
	}
	for _, e := range entries {
		if !strings.HasPrefix(e.Description, prefix) {
			continue
		}
		for _, row := range e.JSON.Payload.Readiness {
			if row.Collector == "discovery.neighbor" {
				return row
			}
		}
	}
	t.Fatalf("corpus has no discovery.neighbor row under a description starting %q", prefix)
	return frame.Readiness{}
}

// TestNetlinkBlockedRow_MatchesTheSharedCorpus pins the exact row an agent under the old unit
// now sends against the corpus entry the backend's GET /agents/netlink-blocked is tested with.
// A reworded reason or remediation, or a renamed Missing token, fails here rather than silently
// dropping the host from the server's list.
func TestNetlinkBlockedRow_MatchesTheSharedCorpus(t *testing.T) {
	blocked := func(context.Context) ([]Neighbor, error) { return nil, netlinkSocketError(unix.EAFNOSUPPORT) }
	got := neighborReadiness(context.Background(), blocked)
	want := corpusNeighborRow(t, "capability.readiness — AF_NETLINK refused by the service sandbox (RISK-011)")
	if !reflect.DeepEqual(got, want) {
		t.Errorf("readiness row = %+v\nwant the corpus row %+v", got, want)
	}
}

// TestLegacyNetlinkBlockedReason_MatchesTheSharedCorpus pins what agents built before the Missing
// token reported for the same failure: the collector's prefix wrapped straight around the errno.
// Those binaries are already in the field and cannot change, and the backend recognises them by
// this exact string, so it must stay what the old wrap produced on this platform.
func TestLegacyNetlinkBlockedReason_MatchesTheSharedCorpus(t *testing.T) {
	legacy := fmt.Errorf("discover: open netlink socket: %w", unix.EAFNOSUPPORT).Error()
	want := corpusNeighborRow(t, "capability.readiness — AF_NETLINK refused by the service sandbox, as an agent built before")
	if want.Reason != legacy {
		t.Errorf("corpus legacy reason = %q, want what pre-token agents sent: %q", want.Reason, legacy)
	}
	if len(want.Missing) != 0 {
		t.Errorf("corpus legacy row carries missing = %v, want none: those agents predate the token", want.Missing)
	}
}
