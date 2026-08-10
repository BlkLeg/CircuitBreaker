package host

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
)

// ---------------------------------------------------------------------------
// Harness. The Docker probe resolves its socket through Collector.Root
// (docker.go's c.path("/var/run/docker.sock")), so a unix listener inside the
// collector's temporary root is a complete substitute for the daemon: no test
// in this file touches the real Docker socket, /proc, /sys or the network.
// ---------------------------------------------------------------------------

// dockerRoot returns a short-lived directory for a collector root. t.TempDir()
// is deliberately not used: its name embeds the (long) test name and a unix
// socket path is capped at ~108 bytes, which several of the test names below
// would blow past once "/var/run/docker.sock" is appended.
func dockerRoot(t *testing.T) string {
	t.Helper()
	root, err := os.MkdirTemp("", "cbdk")
	if err != nil {
		t.Fatalf("MkdirTemp() error = %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(root) })
	return root
}

// newDockerCollector wires a Collector at a short root holding only the two
// sources host.core requires, so every readiness entry other than host.docker
// is either "ready" (core) or "disabled" (the optional probes).
func newDockerCollector(t *testing.T, includeDocker bool) (*Collector, string) {
	t.Helper()
	root := dockerRoot(t)
	writeTree(t, root, map[string]string{"/proc/stat": baselineProcStat, "/proc/meminfo": baselineMeminfo})
	clock := time.Unix(1750000000, 0).UTC()
	c := &Collector{
		Root:   root,
		Config: capability.HostConfig{IntervalS: 30, IncludeDocker: includeDocker},
		Now:    func() time.Time { return clock },
		Usage: func(path string) (FSUsage, error) {
			return FSUsage{}, fmt.Errorf("statfs %s: not used by docker tests", path)
		},
	}
	return c, root
}

// startFakeDocker listens on <root>/var/run/docker.sock and serves handler
// until the test ends.
func startFakeDocker(t *testing.T, root string, handler http.Handler) {
	t.Helper()
	dir := filepath.Join(root, "var", "run")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%s) error = %v", dir, err)
	}
	socket := filepath.Join(dir, "docker.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatalf("net.Listen(unix, %s) error = %v", socket, err)
	}
	server := &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
		_ = server.Close()
	})
}

// dockerMux routes the two endpoints docker.go calls. Every canned body is
// therefore attached to an explicit path rather than to a catch-all.
func dockerMux(list, stats http.HandlerFunc) http.Handler {
	mux := http.NewServeMux()
	if list != nil {
		mux.HandleFunc("/v1.41/containers/json", list)
	}
	if stats != nil {
		mux.HandleFunc("/v1.41/containers/{id}/stats", stats)
	}
	return mux
}

func jsonHandler(status int, body string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}
}

// containerList renders a Docker /containers/json body. names of nil renders an
// empty "Names" array, which is the shape docker.go's len(item.Names) guard sees.
func containerList(t *testing.T, entries ...dockerContainer) string {
	t.Helper()
	items := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		names := e.Names
		if names == nil {
			names = []string{}
		}
		items = append(items, map[string]any{"Id": e.ID, "Names": names, "Image": e.Image, "State": e.State, "Status": e.Status})
	}
	body, err := json.Marshal(items)
	if err != nil {
		t.Fatalf("Marshal(container list) error = %v", err)
	}
	return string(body)
}

func dockerPayload(t *testing.T, res collect.Result) map[string]any {
	t.Helper()
	payload, ok := res.Payload.Docker.(map[string]any)
	if !ok {
		t.Fatalf("Payload.Docker = %T(%v), want map[string]any", res.Payload.Docker, res.Payload.Docker)
	}
	return payload
}

func dockerContainerList(t *testing.T, res collect.Result) []map[string]any {
	t.Helper()
	items, ok := dockerPayload(t, res)["containers"].([]map[string]any)
	if !ok {
		t.Fatalf("Payload.Docker[containers] = %T, want []map[string]any", dockerPayload(t, res)["containers"])
	}
	return items
}

func mustCollect(t *testing.T, c *Collector) collect.Result {
	t.Helper()
	res, err := c.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil", err)
	}
	return res
}

// ---------------------------------------------------------------------------
// Failure branches.
// ---------------------------------------------------------------------------

func TestDocker_SocketAbsentReportsUnavailableWithRemediation(t *testing.T) {
	c, _ := newDockerCollector(t, true)

	res := mustCollect(t, c)

	got := readinessFor(t, res, "host.docker")
	if got.State != "unavailable" {
		t.Errorf("readiness[host.docker].State = %q, want %q", got.State, "unavailable")
	}
	if !strings.Contains(got.Reason, "open Docker socket") {
		t.Errorf("readiness[host.docker].Reason = %q, want it to contain %q", got.Reason, "open Docker socket")
	}
	// The single user-facing instruction for the most common Docker failure.
	if want := "rerun the installer and verify membership in the docker group"; got.Remediation != want {
		t.Errorf("readiness[host.docker].Remediation = %q, want %q", got.Remediation, want)
	}
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "degraded")
	}
}

func TestDocker_SocketUnreadable(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root bypasses unix socket permissions")
	}
	c, root := newDockerCollector(t, true)
	startFakeDocker(t, root, dockerMux(jsonHandler(http.StatusOK, "[]"), nil))
	socket := filepath.Join(root, "var", "run", "docker.sock")
	if err := os.Chmod(socket, 0o000); err != nil {
		t.Fatalf("Chmod(%s, 0000) error = %v", socket, err)
	}

	res := mustCollect(t, c)

	got := readinessFor(t, res, "host.docker")
	if got.State != "unavailable" || !strings.Contains(got.Reason, "open Docker socket") {
		t.Errorf("readiness[host.docker] = %+v, want unavailable with an %q reason", got, "open Docker socket")
	}
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "degraded")
	}
}

func TestDocker_DisabledReportsDisabledAndLeavesPayloadNil(t *testing.T) {
	c, root := newDockerCollector(t, false)
	// A reachable daemon proves the disable is honored rather than merely
	// coinciding with an unreachable socket.
	startFakeDocker(t, root, dockerMux(jsonHandler(http.StatusOK, containerList(t, dockerContainer{ID: "a", Image: "nginx", State: "running"})), nil))

	res := mustCollect(t, c)

	wantState(t, res, "host.docker", "disabled")
	if readinessFor(t, res, "host.docker").Reason != "" {
		t.Errorf("readiness[host.docker].Reason = %q, want empty for a disabled collector", readinessFor(t, res, "host.docker").Reason)
	}
	if res.Payload.Docker != nil {
		t.Errorf("Payload.Docker = %v, want nil when the collector is disabled", res.Payload.Docker)
	}
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "healthy")
	}
}

func TestDocker_ApiErrorBranches(t *testing.T) {
	cases := []struct {
		name       string
		status     int
		body       string
		wantReason string
	}{
		{"non-200 response", http.StatusInternalServerError, "boom", "Docker API returned 500 Internal Server Error"},
		{"undecodable body", http.StatusOK, "{not json", "decode Docker response"},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			c, root := newDockerCollector(t, true)
			startFakeDocker(t, root, dockerMux(jsonHandler(tt.status, tt.body), nil))

			res := mustCollect(t, c)

			got := readinessFor(t, res, "host.docker")
			if got.State != "unavailable" {
				t.Errorf("readiness[host.docker].State = %q, want %q", got.State, "unavailable")
			}
			if !strings.Contains(got.Reason, tt.wantReason) {
				t.Errorf("readiness[host.docker].Reason = %q, want it to contain %q", got.Reason, tt.wantReason)
			}
			if res.Payload.Status != "degraded" {
				t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "degraded")
			}
			if res.Payload.Docker != nil {
				t.Errorf("Payload.Docker = %v, want nil when the list call failed", res.Payload.Docker)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Success branches.
// ---------------------------------------------------------------------------

func TestDocker_MoreThanOneHundredContainersTruncatesAndDegrades(t *testing.T) {
	entries := make([]dockerContainer, 0, 150)
	for i := 0; i < 150; i++ {
		entries = append(entries, dockerContainer{ID: fmt.Sprintf("c%03d", i), Names: []string{fmt.Sprintf("/c%03d", i)}, Image: "busybox", State: "exited", Status: "Exited (0)"})
	}
	c, root := newDockerCollector(t, true)
	startFakeDocker(t, root, dockerMux(jsonHandler(http.StatusOK, containerList(t, entries...)), nil))

	res := mustCollect(t, c)

	payload := dockerPayload(t, res)
	if got := len(dockerContainerList(t, res)); got != 100 {
		t.Errorf("len(containers) = %d, want 100", got)
	}
	if got := payload["total"]; got != 100 {
		t.Errorf("docker[total] = %v, want 100", got)
	}
	if got := payload["running"]; got != 0 {
		t.Errorf("docker[running] = %v, want 0", got)
	}
	// truncated + degraded are the only signals the list is incomplete.
	if got := payload["truncated"]; got != true {
		t.Errorf("docker[truncated] = %v, want true", got)
	}
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "degraded")
	}
	wantState(t, res, "host.docker", "ready")
}

func TestDocker_StatsFailureLeavesContainerWithoutStatsAndDoesNotDegrade(t *testing.T) {
	// A body that would otherwise decode into a complete stats map, so the
	// 500 case below cannot be absorbed by the decode guard the way a
	// non-JSON body is — deleting dockerStatsSummary's status check makes
	// that case, and only that case, fail.
	const wellFormed = `{
		"cpu_stats": {"cpu_usage": {"total_usage": 200000000}, "system_cpu_usage": 2000000000, "online_cpus": 4},
		"precpu_stats": {"cpu_usage": {"total_usage": 100000000}, "system_cpu_usage": 1000000000},
		"memory_stats": {"usage": 536870912, "limit": 1073741824},
		"networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}}
	}`
	cases := []struct {
		name   string
		status int
		body   string
	}{
		{"stats endpoint errors", http.StatusInternalServerError, "nope"},
		{"stats body is malformed", http.StatusOK, "{not json"},
		{"stats endpoint errors with a well-formed body", http.StatusInternalServerError, wellFormed},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			c, root := newDockerCollector(t, true)
			list := containerList(t, dockerContainer{ID: "abc123", Names: []string{"/web"}, Image: "nginx:1", State: "running", Status: "Up 2 hours"})
			startFakeDocker(t, root, dockerMux(jsonHandler(http.StatusOK, list), jsonHandler(tt.status, tt.body)))

			res := mustCollect(t, c)

			item := mustItem(t, dockerContainerList(t, res), "id", "abc123")
			for key, want := range map[string]string{"name": "/web", "image": "nginx:1", "state": "running", "status": "Up 2 hours"} {
				if got, _ := item[key].(string); got != want {
					t.Errorf("container[%q] = %q, want %q", key, got, want)
				}
			}
			for _, key := range []string{"memory_used_bytes", "memory_limit_bytes", "memory_pct", "cpu_pct", "network_rx_bytes", "network_tx_bytes"} {
				if _, ok := item[key]; ok {
					t.Errorf("container[%q] = %v, want the key to be absent when stats fail", key, item[key])
				}
			}
			// A stats failure is per-container detail loss, not a collector fault.
			wantState(t, res, "host.docker", "ready")
			if res.Payload.Status != "healthy" {
				t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "healthy")
			}
			if got := dockerPayload(t, res)["running"]; got != 1 {
				t.Errorf("docker[running] = %v, want 1", got)
			}
		})
	}
}

func TestDocker_CPUPercentMatchesDockerFormula(t *testing.T) {
	// (200000000-100000000) * 4 * 100 / (2000000000-1000000000) = 40.
	const fullStats = `{
		"cpu_stats": {"cpu_usage": {"total_usage": 200000000}, "system_cpu_usage": 2000000000, "online_cpus": 4},
		"precpu_stats": {"cpu_usage": {"total_usage": 100000000}, "system_cpu_usage": 1000000000},
		"memory_stats": {"usage": 536870912, "limit": 1073741824},
		"networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}, "eth1": {"rx_bytes": 30, "tx_bytes": 40}}
	}`
	// online_cpus 0 leaves the formula undefined, so cpu_pct must be omitted.
	const noCPUStats = `{
		"cpu_stats": {"cpu_usage": {"total_usage": 200000000}, "system_cpu_usage": 2000000000, "online_cpus": 0},
		"precpu_stats": {"cpu_usage": {"total_usage": 100000000}, "system_cpu_usage": 1000000000},
		"memory_stats": {"usage": 100, "limit": 0},
		"networks": {}
	}`
	bodies := map[string]string{"full": fullStats, "nocpu": noCPUStats}
	c, root := newDockerCollector(t, true)
	list := containerList(t,
		dockerContainer{ID: "full", Names: []string{"/web"}, Image: "nginx:1", State: "running", Status: "Up 2 hours"},
		dockerContainer{ID: "nocpu", Names: nil, Image: "redis:7", State: "running", Status: "Up 5 minutes"},
		dockerContainer{ID: "stopped", Names: []string{"/batch"}, Image: "busybox", State: "exited", Status: "Exited (0)"},
	)
	stats := func(w http.ResponseWriter, r *http.Request) {
		body, ok := bodies[r.PathValue("id")]
		if !ok {
			t.Errorf("unexpected stats request for %q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if got := r.URL.Query().Get("stream"); got != "false" {
			t.Errorf("stats request stream = %q, want %q", got, "false")
		}
		_, _ = w.Write([]byte(body))
	}
	startFakeDocker(t, root, dockerMux(jsonHandler(http.StatusOK, list), stats))

	res := mustCollect(t, c)

	items := dockerContainerList(t, res)
	full := mustItem(t, items, "id", "full")
	if got := itemFloat(t, full, "cpu_pct"); got != 40 {
		t.Errorf("container[cpu_pct] = %v, want 40", got)
	}
	if got := itemFloat(t, full, "memory_pct"); got != 50 {
		t.Errorf("container[memory_pct] = %v, want 50", got)
	}
	if got := itemUint(t, full, "memory_used_bytes"); got != 536870912 {
		t.Errorf("container[memory_used_bytes] = %d, want 536870912", got)
	}
	if got := itemUint(t, full, "memory_limit_bytes"); got != 1073741824 {
		t.Errorf("container[memory_limit_bytes] = %d, want 1073741824", got)
	}
	if got := itemUint(t, full, "network_rx_bytes"); got != 1030 {
		t.Errorf("container[network_rx_bytes] = %d, want 1030 (summed across interfaces)", got)
	}
	if got := itemUint(t, full, "network_tx_bytes"); got != 2040 {
		t.Errorf("container[network_tx_bytes] = %d, want 2040 (summed across interfaces)", got)
	}

	noCPU := mustItem(t, items, "id", "nocpu")
	if _, ok := noCPU["cpu_pct"]; ok {
		t.Errorf("container[cpu_pct] = %v with online_cpus 0, want the key to be absent", noCPU["cpu_pct"])
	}
	if _, ok := noCPU["memory_pct"]; ok {
		t.Errorf("container[memory_pct] = %v with a zero memory limit, want the key to be absent", noCPU["memory_pct"])
	}
	if got, _ := noCPU["name"].(string); got != "" {
		t.Errorf("container[name] = %q for an empty Names array, want the empty string", got)
	}

	// A non-running container is never asked for stats.
	stopped := mustItem(t, items, "id", "stopped")
	if _, ok := stopped["memory_used_bytes"]; ok {
		t.Error("a non-running container carries stats keys, want none")
	}
	payload := dockerPayload(t, res)
	if payload["total"] != 3 || payload["running"] != 2 || payload["truncated"] != false {
		t.Errorf("docker summary = total:%v running:%v truncated:%v, want 3/2/false", payload["total"], payload["running"], payload["truncated"])
	}
	wantState(t, res, "host.docker", "ready")
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want %q", res.Payload.Status, "healthy")
	}
}

// ---------------------------------------------------------------------------
// Context handling.
// ---------------------------------------------------------------------------

func TestDocker_CanceledContextNeverReachesTheSocket(t *testing.T) {
	c, root := newDockerCollector(t, true)
	calls := make(chan struct{}, 4)
	startFakeDocker(t, root, dockerMux(func(w http.ResponseWriter, _ *http.Request) {
		calls <- struct{}{}
		_, _ = w.Write([]byte("[]"))
	}, nil))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	res, err := c.Collect(ctx)

	if err == nil {
		t.Fatal("Collect() error = nil for a canceled context, want context.Canceled")
	}
	// An empty Readiness alongside an error means "no information" and must not
	// be reported (collect.Collector contract).
	if len(res.Readiness) != 0 {
		t.Errorf("Readiness = %+v for a canceled context, want empty", res.Readiness)
	}
	if len(calls) != 0 {
		t.Errorf("the fake daemon was contacted %d times, want 0", len(calls))
	}
}

func TestDocker_ContextCanceledMidRequestTakesTheSocketBranch(t *testing.T) {
	c, root := newDockerCollector(t, true)
	entered := make(chan struct{})
	startFakeDocker(t, root, dockerMux(func(_ http.ResponseWriter, r *http.Request) {
		close(entered)
		<-r.Context().Done() // block before writing any header
	}, nil))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	type outcome struct {
		res collect.Result
		err error
	}
	done := make(chan outcome, 1)
	go func() {
		res, err := c.Collect(ctx)
		done <- outcome{res, err}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("the fake daemon never received the container-list request")
	}
	cancel()

	select {
	case got := <-done:
		if got.err != nil {
			t.Fatalf("Collect() error = %v, want nil (the docker fault is reported as readiness)", got.err)
		}
		r := readinessFor(t, got.res, "host.docker")
		if r.State != "unavailable" || !strings.Contains(r.Reason, "open Docker socket") {
			t.Errorf("readiness[host.docker] = %+v, want unavailable with an %q reason", r, "open Docker socket")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Collect() hung after the context was canceled mid-request")
	}
}
