package host

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
	"circuitbreaker.dev/cb-agent/internal/frame"
)

// ---------------------------------------------------------------------------
// Fixtures. Every probe reads through Collector.Root, Collector.Now and
// Collector.Usage, so no test here touches the real /proc, /sys, filesystem
// statistics, the Docker daemon or the network.
// ---------------------------------------------------------------------------

const (
	// cpu totals 600 (100+20+30+400+50), idle 450 (400+50), two logical CPUs.
	baselineProcStat = "cpu  100 20 30 400 50 0 0 0 0 0\n" +
		"cpu0 50 10 15 200 25 0 0 0 0 0\n" +
		"cpu1 50 10 15 200 25 0 0 0 0 0\n" +
		"intr 1\n" +
		"ctxt 1\n" +
		"btime 1750000000\n"
	// cpu totals 1600, idle 950: +1000 total / +500 idle against the baseline => 50%.
	busyProcStat = "cpu  300 50 250 800 150 25 25 0 0 0\n" +
		"cpu0 150 25 125 400 75 12 12 0 0 0\n" +
		"cpu1 150 25 125 400 75 13 13 0 0 0\n" +
		"intr 2\n" +
		"ctxt 2\n" +
		"btime 1750000000\n"
	// totals 50, strictly below the baseline's 600.
	rewoundProcStat = "cpu  10 5 5 20 10 0 0 0 0 0\n" +
		"cpu0 5 2 2 10 5 0 0 0 0 0\n" +
		"cpu1 5 3 3 10 5 0 0 0 0 0\n" +
		"btime 1750000000\n"

	baselineMeminfo = "MemTotal:       16000000 kB\n" +
		"MemFree:         2000000 kB\n" +
		"MemAvailable:    8000000 kB\n" +
		"SwapTotal:       4000000 kB\n" +
		"SwapFree:        3000000 kB\n"

	// Every pseudo-filesystem row carries four fields so the exclusion is proven
	// to come from pseudoFS and not from the arity guard. `badline` is the
	// three-field row that covers the arity guard on its own.
	baselineMounts = "/dev/sda1 / ext4 rw,relatime\n" +
		"proc /proc proc rw,nosuid\n" +
		"sysfs /sys sysfs rw,nosuid\n" +
		"tmpfs /run tmpfs rw,nosuid\n" +
		"overlay /var/lib/docker/o overlay rw,relatime\n" +
		"/dev/sdb1 /mnt/data ext4 ro,relatime\n" +
		"badline / ext4\n"

	// major minor name + 11 stat fields = 14. Sectors read is field 5, sectors
	// written field 9; the collector multiplies both by 512.
	baselineDiskstats = "   8       0 sda 100 0 200 50 300 0 400 60 0 70 80\n" +
		"   8      16 sdb 10 0 20 5 30 0 40 6 0 7 8\n" +
		"   7       0 loop0 1 0 2 1 3 0 4 1 0 1 1\n" +
		"   1       0 ram0 1 0 2 1 3 0 4 1 0 1 1\n" +
		" 253       0 dm-0 1 0 2 1 3 0 4 1 0 1 1\n"
	// sda advanced by 200 read sectors and 200 written sectors; sdb unchanged.
	busyDiskstats = "   8       0 sda 200 0 400 50 300 0 600 60 0 70 80\n" +
		"   8      16 sdb 10 0 20 5 30 0 40 6 0 7 8\n"

	netDevHeader = "Inter-|   Receive                                                |  Transmit\n" +
		" face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
	baselineNetDev = netDevHeader +
		"    eth0: 1000 10 1 0 0 0 0 0 2000 20 2 0 0 0 0 0\n" +
		"      lo: 500 5 0 0 0 0 0 0 500 5 0 0 0 0 0 0\n" +
		"veth1234: 100 1 0 0 0 0 0 0 200 2 0 0 0 0 0 0\n" +
		" docker0: 300 3 0 0 0 0 0 0 400 4 0 0 0 0 0 0\n" +
		"  br-abc: 700 7 0 0 0 0 0 0 800 8 0 0 0 0 0 0\n" +
		"   wlan0: 900 9 0 0 0 0 0 0 1000 10 0 0 0 0 0 0\n"
	// eth0 +2000 rx / +4000 tx; every virtual interface also moves, so a summary
	// that included them would not be 200/400.
	busyNetDev = netDevHeader +
		"    eth0: 3000 30 1 0 0 0 0 0 6000 60 2 0 0 0 0 0\n" +
		"      lo: 9500 95 0 0 0 0 0 0 9500 95 0 0 0 0 0 0\n" +
		"veth1234: 9100 91 0 0 0 0 0 0 9200 92 0 0 0 0 0 0\n" +
		" docker0: 9300 93 0 0 0 0 0 0 9400 94 0 0 0 0 0 0\n" +
		"  br-abc: 9700 97 0 0 0 0 0 0 9800 98 0 0 0 0 0 0\n" +
		"   wlan0: 9900 99 0 0 0 0 0 0 9000 90 0 0 0 0 0 0\n"
	// every counter below its predecessor: a full reset.
	rewoundNetDev = netDevHeader +
		"    eth0: 10 1 1 0 0 0 0 0 20 2 2 0 0 0 0 0\n"
)

func baselineFiles() map[string]string {
	return map[string]string{
		"/proc/stat":                            baselineProcStat,
		"/proc/loadavg":                         "0.50 1.25 2.00 1/234 5678\n",
		"/proc/meminfo":                         baselineMeminfo,
		"/proc/uptime":                          "123456.78 987654.32\n",
		"/proc/self/mounts":                     baselineMounts,
		"/proc/diskstats":                       baselineDiskstats,
		"/proc/net/dev":                         baselineNetDev,
		"/sys/class/net/eth0/operstate":         "up\n",
		"/sys/class/net/eth0/speed":             "1000\n",
		"/sys/class/net/veth1234/operstate":     "up\n",
		"/sys/class/net/docker0/operstate":      "up\n",
		"/sys/class/net/br-abc/operstate":       "up\n",
		"/sys/class/net/wlan0/operstate":        "down\n",
		"/sys/class/thermal/thermal_zone0/temp": "45000\n",
		"/sys/class/hwmon/hwmon0/temp1_input":   "61000\n",
		"/sys/class/hwmon/hwmon0/temp1_max":     "85000\n",
		"/sys/class/hwmon/hwmon0/temp1_crit":    "100000\n",
	}
}

func baselineUsage() map[string]FSUsage {
	return map[string]FSUsage{
		"/":         {TotalBytes: 1000, FreeBytes: 400, AvailBytes: 300},
		"/mnt/data": {TotalBytes: 2000, FreeBytes: 500, AvailBytes: 500},
	}
}

func fullConfig() capability.HostConfig {
	return capability.HostConfig{IntervalS: 30, IncludeFilesystems: true, IncludeDisks: true, IncludeNetwork: true, IncludeTemperatures: true}
}

func onlyConfig(field string) capability.HostConfig {
	cfg := capability.HostConfig{IntervalS: 30}
	switch field {
	case "filesystems":
		cfg.IncludeFilesystems = true
	case "disks":
		cfg.IncludeDisks = true
	case "network":
		cfg.IncludeNetwork = true
	case "thermal":
		cfg.IncludeTemperatures = true
	}
	return cfg
}

// ---------------------------------------------------------------------------
// Harness.
// ---------------------------------------------------------------------------

func writeTree(t *testing.T, root string, files map[string]string) {
	t.Helper()
	for name, content := range files {
		full := filepath.Join(root, strings.TrimPrefix(name, "/"))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatalf("MkdirAll(%s) error = %v", filepath.Dir(full), err)
		}
		if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
			t.Fatalf("WriteFile(%s) error = %v", full, err)
		}
	}
}

// testCollector wires a Collector to a temporary root, a settable clock and a
// map-backed filesystem-usage stub. A mountpoint missing from the map reports
// an error, which is how the statfs-failure path is exercised.
type testCollector struct {
	*Collector
	root  string
	clock time.Time
	usage map[string]FSUsage
}

func newTestCollector(t *testing.T, cfg capability.HostConfig, files map[string]string) *testCollector {
	t.Helper()
	root := t.TempDir()
	writeTree(t, root, files)
	tc := &testCollector{root: root, clock: time.Unix(1750000000, 0).UTC(), usage: baselineUsage()}
	tc.Collector = &Collector{Root: root, Config: cfg}
	tc.Collector.Now = func() time.Time { return tc.clock }
	tc.Collector.Usage = func(path string) (FSUsage, error) {
		mount := tc.mountpoint(path)
		u, ok := tc.usage[mount]
		if !ok {
			return FSUsage{}, fmt.Errorf("statfs %s: stub has no entry", mount)
		}
		return u, nil
	}
	return tc
}

// mountpoint maps a rooted path back to the mountpoint the collector asked about.
func (tc *testCollector) mountpoint(path string) string {
	rel, err := filepath.Rel(tc.root, path)
	if err != nil || rel == "." {
		return "/"
	}
	return "/" + filepath.ToSlash(rel)
}

func (tc *testCollector) advance(d time.Duration) { tc.clock = tc.clock.Add(d) }

func (tc *testCollector) write(t *testing.T, files map[string]string) {
	t.Helper()
	writeTree(t, tc.root, files)
}

func (tc *testCollector) remove(t *testing.T, name string) {
	t.Helper()
	if err := os.Remove(filepath.Join(tc.root, strings.TrimPrefix(name, "/"))); err != nil {
		t.Fatalf("Remove(%s) error = %v", name, err)
	}
}

func (tc *testCollector) collect(t *testing.T) collect.Result {
	t.Helper()
	res, err := tc.Collect(context.Background())
	if err != nil {
		t.Fatalf("Collect() error = %v, want nil", err)
	}
	return res
}

// ---------------------------------------------------------------------------
// Assertion helpers.
// ---------------------------------------------------------------------------

func findItem(items []map[string]any, key, value string) map[string]any {
	for _, item := range items {
		if s, ok := item[key].(string); ok && s == value {
			return item
		}
	}
	return nil
}

func itemNames(items []map[string]any, key string) []string {
	out := make([]string, 0, len(items))
	for _, item := range items {
		s, _ := item[key].(string)
		out = append(out, s)
	}
	return out
}

func mustItem(t *testing.T, items []map[string]any, key, value string) map[string]any {
	t.Helper()
	item := findItem(items, key, value)
	if item == nil {
		t.Fatalf("no entry with %s=%q in %v", key, value, itemNames(items, key))
	}
	return item
}

func itemUint(t *testing.T, item map[string]any, key string) uint64 {
	t.Helper()
	v, ok := item[key]
	if !ok {
		t.Fatalf("entry %v is missing key %q", item, key)
	}
	n, ok := v.(uint64)
	if !ok {
		t.Fatalf("entry[%q] = %T(%v), want uint64", key, v, v)
	}
	return n
}

func itemFloat(t *testing.T, item map[string]any, key string) float64 {
	t.Helper()
	v, ok := item[key]
	if !ok {
		t.Fatalf("entry %v is missing key %q", item, key)
	}
	f, ok := v.(float64)
	if !ok {
		t.Fatalf("entry[%q] = %T(%v), want float64", key, v, v)
	}
	return f
}

func wantFloatPtr(t *testing.T, name string, got *float64, want float64) {
	t.Helper()
	if got == nil {
		t.Fatalf("%s = nil, want %v", name, want)
	}
	if *got != want {
		t.Errorf("%s = %v, want %v", name, *got, want)
	}
}

func wantUintPtr(t *testing.T, name string, got *uint64, want uint64) {
	t.Helper()
	if got == nil {
		t.Fatalf("%s = nil, want %v", name, want)
	}
	if *got != want {
		t.Errorf("%s = %v, want %v", name, *got, want)
	}
}

func readinessFor(t *testing.T, res collect.Result, collector string) frame.Readiness {
	t.Helper()
	for _, r := range res.Readiness {
		if r.Collector == collector {
			return r
		}
	}
	t.Fatalf("no readiness entry for %q in %+v", collector, res.Readiness)
	return frame.Readiness{}
}

func wantState(t *testing.T, res collect.Result, collector, state string) {
	t.Helper()
	if got := readinessFor(t, res, collector); got.State != state {
		t.Errorf("readiness[%s].State = %q (reason %q), want %q", collector, got.State, got.Reason, state)
	}
}

// ---------------------------------------------------------------------------
// host.core
// ---------------------------------------------------------------------------

func TestCore_FirstSampleOmitsCPUPctAndFillsSummary(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	s := tc.collect(t).Payload.Summary

	if s.CPUPct != nil {
		t.Errorf("Summary.CPUPct = %v on the first sample, want nil", *s.CPUPct)
	}
	wantUintPtr(t, "Summary.MemTotalBytes", s.MemTotalBytes, 16000000*1024)
	wantUintPtr(t, "Summary.MemAvailableBytes", s.MemAvailableBytes, 8000000*1024)
	wantUintPtr(t, "Summary.MemUsedBytes", s.MemUsedBytes, 8000000*1024)
	wantFloatPtr(t, "Summary.MemPct", s.MemPct, 50)
	wantUintPtr(t, "Summary.SwapTotalBytes", s.SwapTotalBytes, 4000000*1024)
	wantUintPtr(t, "Summary.SwapUsedBytes", s.SwapUsedBytes, 1000000*1024)
	wantFloatPtr(t, "Summary.SwapPct", s.SwapPct, 25)
	wantFloatPtr(t, "Summary.Load1", s.Load1, 0.5)
	wantFloatPtr(t, "Summary.Load5", s.Load5, 1.25)
	wantFloatPtr(t, "Summary.Load15", s.Load15, 2.0)
	wantFloatPtr(t, "Summary.UptimeS", s.UptimeS, 123456.78)
	wantUintPtr(t, "Summary.BootTimeUnixS", s.BootTimeUnixS, 1750000000)
	if s.LogicalCPUs == nil || *s.LogicalCPUs != 2 {
		t.Errorf("Summary.LogicalCPUs = %v, want 2", s.LogicalCPUs)
	}
}

func TestCore_SecondSampleComputesCPUPct(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/stat": busyProcStat})
	tc.advance(10 * time.Second)

	wantFloatPtr(t, "Summary.CPUPct", tc.collect(t).Payload.Summary.CPUPct, 50)
}

func TestCore_DecreasingTotalsOmitCPUPctWithoutError(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/stat": rewoundProcStat})
	tc.advance(10 * time.Second)

	if got := tc.collect(t).Payload.Summary.CPUPct; got != nil {
		t.Errorf("Summary.CPUPct = %v after a counter rewind, want nil", *got)
	}
}

func TestCore_UnreadableSourcesReturnHostCoreError(t *testing.T) {
	cases := []struct {
		name    string
		mutate  func(t *testing.T, files map[string]string)
		wantMsg string
	}{
		{"missing /proc/stat", func(_ *testing.T, f map[string]string) { delete(f, "/proc/stat") }, "no such file"},
		{"empty /proc/stat", func(_ *testing.T, f map[string]string) { f["/proc/stat"] = "" }, "missing aggregate cpu line"},
		{"malformed cpu line", func(_ *testing.T, f map[string]string) { f["/proc/stat"] = "garbage\n" }, "invalid aggregate cpu line"},
		{"short cpu line", func(_ *testing.T, f map[string]string) { f["/proc/stat"] = "cpu 1 2 3\n" }, "invalid aggregate cpu line"},
		{"non-numeric cpu field", func(_ *testing.T, f map[string]string) { f["/proc/stat"] = "cpu  100 20 x 400 50\n" }, "invalid syntax"},
		{"missing /proc/meminfo", func(_ *testing.T, f map[string]string) { delete(f, "/proc/meminfo") }, "no such file"},
		{"meminfo without MemTotal", func(_ *testing.T, f map[string]string) { f["/proc/meminfo"] = "MemFree: 1 kB\n" }, "MemTotal unavailable"},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			files := baselineFiles()
			tt.mutate(t, files)
			tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, files)

			_, err := tc.Collect(context.Background())

			if err == nil {
				t.Fatal("Collect() error = nil, want a host core error")
			}
			if !strings.Contains(err.Error(), "host core") || !strings.Contains(err.Error(), tt.wantMsg) {
				t.Errorf("Collect() error = %q, want it to wrap \"host core\" and contain %q", err, tt.wantMsg)
			}
		})
	}
}

func TestCore_PermissionDeniedProcStatReturnsHostCoreError(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root bypasses file permissions")
	}
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())
	if err := os.Chmod(filepath.Join(tc.root, "proc/stat"), 0o000); err != nil {
		t.Fatalf("Chmod() error = %v", err)
	}

	_, err := tc.Collect(context.Background())

	if err == nil || !strings.Contains(err.Error(), "host core") || !strings.Contains(err.Error(), "permission denied") {
		t.Errorf("Collect() error = %v, want a host core permission-denied error", err)
	}
}

func TestCore_MissingLoadavgAndUptimeAreNotErrors(t *testing.T) {
	files := baselineFiles()
	delete(files, "/proc/loadavg")
	delete(files, "/proc/uptime")
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, files)

	res := tc.collect(t)

	if res.Payload.Summary.Load1 != nil || res.Payload.Summary.UptimeS != nil {
		t.Errorf("Summary.Load1 = %v, Summary.UptimeS = %v, want both nil", res.Payload.Summary.Load1, res.Payload.Summary.UptimeS)
	}
	wantState(t, res, "host.core", "ready")
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want \"healthy\"", res.Payload.Status)
	}
}

// ---------------------------------------------------------------------------
// host.filesystems
// ---------------------------------------------------------------------------

func TestFilesystems_UsesInjectedUsageForByteMath(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())
	tc.usage["/"] = FSUsage{TotalBytes: 1000, FreeBytes: 400, AvailBytes: 300}

	res := tc.collect(t)

	root := mustItem(t, res.Payload.Filesystems, "mountpoint", "/")
	if got := itemUint(t, root, "total_bytes"); got != 1000 {
		t.Errorf("total_bytes = %d, want 1000", got)
	}
	if got := itemUint(t, root, "available_bytes"); got != 300 {
		t.Errorf("available_bytes = %d, want 300", got)
	}
	if got := itemUint(t, root, "used_bytes"); got != 600 {
		t.Errorf("used_bytes = %d, want 600 (total-free)", got)
	}
	if got := itemFloat(t, root, "used_pct"); got != 60 {
		t.Errorf("used_pct = %v, want 60", got)
	}
	wantFloatPtr(t, "Summary.RootDiskPct", res.Payload.Summary.RootDiskPct, 60)
}

func TestFilesystems_StatfsErrorSkipsOnlyThatMount(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())
	delete(tc.usage, "/mnt/data") // the stub now errors for /mnt/data only

	res := tc.collect(t)

	if findItem(res.Payload.Filesystems, "mountpoint", "/mnt/data") != nil {
		t.Errorf("/mnt/data survived a statfs error: %v", res.Payload.Filesystems)
	}
	if findItem(res.Payload.Filesystems, "mountpoint", "/") == nil {
		t.Errorf("/ was dropped by an unrelated mount's statfs error: %v", res.Payload.Filesystems)
	}
	wantState(t, res, "host.filesystems", "ready")
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want \"healthy\"", res.Payload.Status)
	}
}

func TestFilesystems_ExcludesPseudoTypesNotViaArityGuard(t *testing.T) {
	for _, line := range strings.Split(strings.TrimSpace(baselineMounts), "\n") {
		x := strings.Fields(line)
		if pseudoFS[x[2]] && len(x) < 4 {
			t.Fatalf("fixture line %q has %d fields; a pseudo-FS row must carry 4 so the arity guard cannot mask pseudoFS", line, len(x))
		}
	}
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())
	for _, mount := range []string{"/proc", "/sys", "/run", "/var/lib/docker/o"} {
		tc.usage[mount] = FSUsage{TotalBytes: 500, FreeBytes: 100, AvailBytes: 100}
	}

	res := tc.collect(t)

	for _, mount := range []string{"/proc", "/sys", "/run", "/var/lib/docker/o"} {
		if findItem(res.Payload.Filesystems, "mountpoint", mount) != nil {
			t.Errorf("pseudo filesystem %s was reported: %v", mount, itemNames(res.Payload.Filesystems, "mountpoint"))
		}
	}
	if len(res.Payload.Filesystems) != 2 {
		t.Errorf("Filesystems = %v, want exactly / and /mnt/data", res.Payload.Filesystems)
	}
}

func TestFilesystems_SkipsShortMountLineViaArityGuard(t *testing.T) {
	if got := len(strings.Fields("badline / ext4")); got != 3 {
		t.Fatalf("fixture arity guard row has %d fields, want 3", got)
	}
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())

	res := tc.collect(t)

	if findItem(res.Payload.Filesystems, "device", "badline") != nil {
		t.Errorf("three-field mount row was reported: %v", res.Payload.Filesystems)
	}
	root := mustItem(t, res.Payload.Filesystems, "mountpoint", "/")
	if got, _ := root["device"].(string); got != "/dev/sda1" {
		t.Errorf("/ device = %q, want \"/dev/sda1\"", got)
	}
}

func TestFilesystems_IncludesRealDevicesAndReadOnlyFlag(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())

	res := tc.collect(t)

	root := mustItem(t, res.Payload.Filesystems, "mountpoint", "/")
	data := mustItem(t, res.Payload.Filesystems, "mountpoint", "/mnt/data")
	if got, _ := root["device"].(string); got != "/dev/sda1" {
		t.Errorf("/ device = %q, want \"/dev/sda1\"", got)
	}
	if got, _ := data["device"].(string); got != "/dev/sdb1" {
		t.Errorf("/mnt/data device = %q, want \"/dev/sdb1\"", got)
	}
	if got, _ := root["read_only"].(bool); got {
		t.Errorf("/ read_only = true, want false for rw,relatime")
	}
	if got, _ := data["read_only"].(bool); !got {
		t.Errorf("/mnt/data read_only = false, want true for ro,relatime")
	}
	if got := itemUint(t, data, "used_bytes"); got != 1500 {
		t.Errorf("/mnt/data used_bytes = %d, want 1500", got)
	}
}

func TestFilesystems_ZeroTotalOmitsUsedPctAndRootDiskPct(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("filesystems"), baselineFiles())
	tc.usage["/"] = FSUsage{}

	res := tc.collect(t)

	root := mustItem(t, res.Payload.Filesystems, "mountpoint", "/")
	if _, ok := root["used_pct"]; ok {
		t.Errorf("used_pct = %v for a zero-byte filesystem, want the key omitted", root["used_pct"])
	}
	if res.Payload.Summary.RootDiskPct != nil {
		t.Errorf("Summary.RootDiskPct = %v, want nil", *res.Payload.Summary.RootDiskPct)
	}
}

func TestFilesystems_DuplicateRootMountLastWins(t *testing.T) {
	files := baselineFiles()
	files["/proc/self/mounts"] = "/dev/sda1 / ext4 rw,relatime\n/dev/sdc1 / ext4 ro,relatime\n"
	tc := newTestCollector(t, onlyConfig("filesystems"), files)
	calls := 0
	tc.Collector.Usage = func(string) (FSUsage, error) {
		calls++
		if calls == 1 {
			return FSUsage{TotalBytes: 1000, FreeBytes: 900, AvailBytes: 900}, nil
		}
		return FSUsage{TotalBytes: 1000, FreeBytes: 200, AvailBytes: 200}, nil
	}

	res := tc.collect(t)

	if len(res.Payload.Filesystems) != 2 {
		t.Fatalf("Filesystems = %v, want both / rows retained", res.Payload.Filesystems)
	}
	if got := itemFloat(t, res.Payload.Filesystems[0], "used_pct"); got != 10 {
		t.Errorf("first / used_pct = %v, want 10", got)
	}
	if got := itemFloat(t, res.Payload.Filesystems[1], "used_pct"); got != 80 {
		t.Errorf("second / used_pct = %v, want 80", got)
	}
	wantFloatPtr(t, "Summary.RootDiskPct", res.Payload.Summary.RootDiskPct, 80)
}

func TestFilesystems_MissingMountsIsUnavailableAndDegradesPayload(t *testing.T) {
	files := baselineFiles()
	delete(files, "/proc/self/mounts")
	tc := newTestCollector(t, onlyConfig("filesystems"), files)

	res := tc.collect(t)

	wantState(t, res, "host.filesystems", "unavailable")
	wantState(t, res, "host.core", "ready")
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want \"degraded\"", res.Payload.Status)
	}
	if len(res.Payload.Filesystems) != 0 {
		t.Errorf("Filesystems = %v, want empty", res.Payload.Filesystems)
	}
}

func TestFilesystems_DisabledReportsDisabledWithEmptySlice(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	res := tc.collect(t)

	wantState(t, res, "host.filesystems", "disabled")
	if len(res.Payload.Filesystems) != 0 {
		t.Errorf("Filesystems = %v, want empty", res.Payload.Filesystems)
	}
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want \"healthy\"", res.Payload.Status)
	}
}

// ---------------------------------------------------------------------------
// host.disks
// ---------------------------------------------------------------------------

func TestDisks_FirstSampleEmitsBytesWithoutRates(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("disks"), baselineFiles())

	res := tc.collect(t)

	sda := mustItem(t, res.Payload.Disks, "device", "sda")
	if got := itemUint(t, sda, "read_bytes"); got != 200*512 {
		t.Errorf("sda read_bytes = %d, want %d", got, 200*512)
	}
	if got := itemUint(t, sda, "write_bytes"); got != 400*512 {
		t.Errorf("sda write_bytes = %d, want %d", got, 400*512)
	}
	if _, ok := sda["read_bps"]; ok {
		t.Errorf("sda read_bps = %v on the first sample, want the key omitted", sda["read_bps"])
	}
	if _, ok := sda["write_bps"]; ok {
		t.Errorf("sda write_bps = %v on the first sample, want the key omitted", sda["write_bps"])
	}
}

func TestDisks_SecondSampleEmitsExactRates(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("disks"), baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/diskstats": busyDiskstats})
	tc.advance(10 * time.Second)
	res := tc.collect(t)

	sda := mustItem(t, res.Payload.Disks, "device", "sda")
	if got := itemFloat(t, sda, "read_bps"); got != 10240 {
		t.Errorf("sda read_bps = %v, want 10240", got)
	}
	if got := itemFloat(t, sda, "write_bps"); got != 10240 {
		t.Errorf("sda write_bps = %v, want 10240", got)
	}
	sdb := mustItem(t, res.Payload.Disks, "device", "sdb")
	if got := itemFloat(t, sdb, "read_bps"); got != 0 {
		t.Errorf("sdb read_bps = %v, want 0 for an idle device", got)
	}
}

func TestDisks_VirtualDevicesGatedByIncludeVirtual(t *testing.T) {
	cases := []struct {
		name           string
		includeVirtual bool
		want           []string
	}{
		{"virtual excluded", false, []string{"sda", "sdb"}},
		{"virtual included", true, []string{"sda", "sdb", "loop0", "ram0", "dm-0"}},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			cfg := onlyConfig("disks")
			cfg.IncludeVirtual = tt.includeVirtual
			tc := newTestCollector(t, cfg, baselineFiles())

			got := itemNames(tc.collect(t).Payload.Disks, "device")

			if strings.Join(got, ",") != strings.Join(tt.want, ",") {
				t.Errorf("disks = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestDisks_DeviceDisappearingAndReappearingResetsRates(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("disks"), baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/diskstats": "   8       0 sda 200 0 400 50 300 0 600 60 0 70 80\n"})
	tc.advance(10 * time.Second)
	res := tc.collect(t)
	if findItem(res.Payload.Disks, "device", "sdb") != nil {
		t.Errorf("sdb reported after it disappeared: %v", res.Payload.Disks)
	}

	tc.write(t, map[string]string{"/proc/diskstats": busyDiskstats})
	tc.advance(10 * time.Second)
	sdb := mustItem(t, tc.collect(t).Payload.Disks, "device", "sdb")
	if _, ok := sdb["read_bps"]; ok {
		t.Errorf("sdb read_bps = %v on the sample it reappeared, want the key omitted", sdb["read_bps"])
	}
}

func TestDisks_DecreasingCountersOmitBothRateKeys(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("disks"), baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/diskstats": "   8       0 sda 1 0 2 1 3 0 4 1 0 1 1\n"})
	tc.advance(10 * time.Second)
	sda := mustItem(t, tc.collect(t).Payload.Disks, "device", "sda")

	if _, ok := sda["read_bps"]; ok {
		t.Errorf("sda read_bps = %v after a counter reset, want the key omitted", sda["read_bps"])
	}
	if _, ok := sda["write_bps"]; ok {
		t.Errorf("sda write_bps = %v after a counter reset, want the key omitted", sda["write_bps"])
	}
}

func TestDisks_ShortRowsAreSkipped(t *testing.T) {
	files := baselineFiles()
	files["/proc/diskstats"] = baselineDiskstats + "   8      32 sdz 1 0 2 1 3 0 4 1 0 1\n"
	tc := newTestCollector(t, onlyConfig("disks"), files)

	if findItem(tc.collect(t).Payload.Disks, "device", "sdz") != nil {
		t.Error("a 13-field diskstats row was reported")
	}
}

func TestDisks_MissingDiskstatsIsUnavailableAndDegradesPayload(t *testing.T) {
	files := baselineFiles()
	delete(files, "/proc/diskstats")
	tc := newTestCollector(t, onlyConfig("disks"), files)

	res := tc.collect(t)

	wantState(t, res, "host.disks", "unavailable")
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want \"degraded\"", res.Payload.Status)
	}
}

func TestDisks_DisabledReportsDisabled(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	res := tc.collect(t)

	wantState(t, res, "host.disks", "disabled")
	if len(res.Payload.Disks) != 0 {
		t.Errorf("Disks = %v, want empty", res.Payload.Disks)
	}
}

// ---------------------------------------------------------------------------
// host.network
// ---------------------------------------------------------------------------

func TestNetwork_LoopbackAlwaysExcluded(t *testing.T) {
	for _, includeVirtual := range []bool{false, true} {
		t.Run(fmt.Sprintf("include_virtual=%v", includeVirtual), func(t *testing.T) {
			cfg := onlyConfig("network")
			cfg.IncludeVirtual = includeVirtual
			tc := newTestCollector(t, cfg, baselineFiles())

			if findItem(tc.collect(t).Payload.Interfaces, "name", "lo") != nil {
				t.Error("lo was reported, want it excluded unconditionally")
			}
		})
	}
}

func TestNetwork_VirtualInterfacesGatedByIncludeVirtual(t *testing.T) {
	cases := []struct {
		name           string
		includeVirtual bool
		want           []string
	}{
		{"virtual excluded", false, []string{"eth0"}},
		{"virtual included", true, []string{"eth0", "veth1234", "docker0", "br-abc"}},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			cfg := onlyConfig("network")
			cfg.IncludeVirtual = tt.includeVirtual
			tc := newTestCollector(t, cfg, baselineFiles())

			got := itemNames(tc.collect(t).Payload.Interfaces, "name")

			if strings.Join(got, ",") != strings.Join(tt.want, ",") {
				t.Errorf("interfaces = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestNetwork_DownInterfaceExcludedEntirely(t *testing.T) {
	cfg := onlyConfig("network")
	cfg.IncludeVirtual = true
	tc := newTestCollector(t, cfg, baselineFiles())

	if findItem(tc.collect(t).Payload.Interfaces, "name", "wlan0") != nil {
		t.Error("wlan0 (operstate \"down\") was reported, want it excluded")
	}
}

func TestNetwork_AbsentOperstateIsIncludedWithEmptyState(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("network"), baselineFiles())
	tc.remove(t, "/sys/class/net/eth0/operstate")

	eth0 := mustItem(t, tc.collect(t).Payload.Interfaces, "name", "eth0")

	if got, _ := eth0["state"].(string); got != "" {
		t.Errorf("eth0 state = %q, want \"\" when operstate is unreadable", got)
	}
}

func TestNetwork_SpeedKeyOmittedWhenAbsentOrNegative(t *testing.T) {
	t.Run("present", func(t *testing.T) {
		tc := newTestCollector(t, onlyConfig("network"), baselineFiles())
		eth0 := mustItem(t, tc.collect(t).Payload.Interfaces, "name", "eth0")
		if got := itemUint(t, eth0, "speed_mbps"); got != 1000 {
			t.Errorf("eth0 speed_mbps = %d, want 1000", got)
		}
	})
	t.Run("absent", func(t *testing.T) {
		files := baselineFiles()
		delete(files, "/sys/class/net/eth0/speed")
		tc := newTestCollector(t, onlyConfig("network"), files)
		eth0 := mustItem(t, tc.collect(t).Payload.Interfaces, "name", "eth0")
		if _, ok := eth0["speed_mbps"]; ok {
			t.Errorf("eth0 speed_mbps = %v with no speed file, want the key omitted", eth0["speed_mbps"])
		}
	})
	t.Run("negative", func(t *testing.T) {
		files := baselineFiles()
		files["/sys/class/net/eth0/speed"] = "-1\n"
		tc := newTestCollector(t, onlyConfig("network"), files)
		eth0 := mustItem(t, tc.collect(t).Payload.Interfaces, "name", "eth0")
		if _, ok := eth0["speed_mbps"]; ok {
			t.Errorf("eth0 speed_mbps = %v for speed -1, want the key omitted", eth0["speed_mbps"])
		}
	})
}

func TestNetwork_ErrorCountersComeFromPostColonFields2And10(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("network"), baselineFiles())

	eth0 := mustItem(t, tc.collect(t).Payload.Interfaces, "name", "eth0")

	if got := itemUint(t, eth0, "rx_bytes"); got != 1000 {
		t.Errorf("eth0 rx_bytes = %d, want 1000", got)
	}
	if got := itemUint(t, eth0, "tx_bytes"); got != 2000 {
		t.Errorf("eth0 tx_bytes = %d, want 2000", got)
	}
	if got := itemUint(t, eth0, "rx_errors"); got != 1 {
		t.Errorf("eth0 rx_errors = %d, want 1", got)
	}
	if got := itemUint(t, eth0, "tx_errors"); got != 2 {
		t.Errorf("eth0 tx_errors = %d, want 2", got)
	}
}

func TestNetwork_FirstSampleOmitsPerInterfaceAndSummaryRates(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("network"), baselineFiles())

	res := tc.collect(t)

	eth0 := mustItem(t, res.Payload.Interfaces, "name", "eth0")
	if _, ok := eth0["rx_bps"]; ok {
		t.Errorf("eth0 rx_bps = %v on the first sample, want the key omitted", eth0["rx_bps"])
	}
	if res.Payload.Summary.NetRXBPS != nil || res.Payload.Summary.NetTXBPS != nil {
		t.Errorf("Summary.Net{RX,TX}BPS = %v/%v on the first sample, want nil", res.Payload.Summary.NetRXBPS, res.Payload.Summary.NetTXBPS)
	}
}

func TestNetwork_SecondSampleSumsIncludedInterfacesOnly(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("network"), baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/net/dev": busyNetDev})
	tc.advance(10 * time.Second)
	res := tc.collect(t)

	eth0 := mustItem(t, res.Payload.Interfaces, "name", "eth0")
	if got := itemFloat(t, eth0, "rx_bps"); got != 200 {
		t.Errorf("eth0 rx_bps = %v, want 200", got)
	}
	if got := itemFloat(t, eth0, "tx_bps"); got != 400 {
		t.Errorf("eth0 tx_bps = %v, want 400", got)
	}
	wantFloatPtr(t, "Summary.NetRXBPS", res.Payload.Summary.NetRXBPS, 200)
	wantFloatPtr(t, "Summary.NetTXBPS", res.Payload.Summary.NetTXBPS, 400)
}

func TestNetwork_CounterResetDropsRatesButStillEmitsZeroSummary(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("network"), baselineFiles())
	tc.collect(t)

	tc.write(t, map[string]string{"/proc/net/dev": rewoundNetDev})
	tc.advance(10 * time.Second)
	res := tc.collect(t)

	eth0 := mustItem(t, res.Payload.Interfaces, "name", "eth0")
	if _, ok := eth0["rx_bps"]; ok {
		t.Errorf("eth0 rx_bps = %v after a counter reset, want the key omitted", eth0["rx_bps"])
	}
	if _, ok := eth0["tx_bps"]; ok {
		t.Errorf("eth0 tx_bps = %v after a counter reset, want the key omitted", eth0["tx_bps"])
	}
	wantFloatPtr(t, "Summary.NetRXBPS", res.Payload.Summary.NetRXBPS, 0)
	wantFloatPtr(t, "Summary.NetTXBPS", res.Payload.Summary.NetTXBPS, 0)
}

func TestNetwork_MissingNetDevIsUnavailableAndDegradesPayload(t *testing.T) {
	files := baselineFiles()
	delete(files, "/proc/net/dev")
	tc := newTestCollector(t, onlyConfig("network"), files)

	res := tc.collect(t)

	wantState(t, res, "host.network", "unavailable")
	if res.Payload.Status != "degraded" {
		t.Errorf("Payload.Status = %q, want \"degraded\"", res.Payload.Status)
	}
}

func TestNetwork_DisabledReportsDisabled(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	res := tc.collect(t)

	wantState(t, res, "host.network", "disabled")
	if len(res.Payload.Interfaces) != 0 {
		t.Errorf("Interfaces = %v, want empty", res.Payload.Interfaces)
	}
}

// ---------------------------------------------------------------------------
// host.thermal
// ---------------------------------------------------------------------------

func TestThermal_CollectsBothSensorsWithThresholdsAndMax(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("thermal"), baselineFiles())

	res := tc.collect(t)

	if got := itemNames(res.Payload.Temperatures, "name"); strings.Join(got, ",") != "hwmon0/temp1,thermal_zone0/temp" {
		t.Fatalf("temperatures = %v, want [hwmon0/temp1 thermal_zone0/temp]", got)
	}
	hwmon := mustItem(t, res.Payload.Temperatures, "name", "hwmon0/temp1")
	zone := mustItem(t, res.Payload.Temperatures, "name", "thermal_zone0/temp")
	if got := itemFloat(t, hwmon, "temp_c"); got != 61 {
		t.Errorf("hwmon0/temp1 temp_c = %v, want 61", got)
	}
	if got := itemFloat(t, hwmon, "warning_c"); got != 85 {
		t.Errorf("hwmon0/temp1 warning_c = %v, want 85", got)
	}
	if got := itemFloat(t, hwmon, "critical_c"); got != 100 {
		t.Errorf("hwmon0/temp1 critical_c = %v, want 100", got)
	}
	if got := itemFloat(t, zone, "temp_c"); got != 45 {
		t.Errorf("thermal_zone0/temp temp_c = %v, want 45", got)
	}
	if _, ok := zone["warning_c"]; ok {
		t.Errorf("thermal_zone0/temp warning_c = %v, want the key omitted for a non-hwmon sensor", zone["warning_c"])
	}
	wantFloatPtr(t, "Summary.MaxTempC", res.Payload.Summary.MaxTempC, 61)
	wantState(t, res, "host.thermal", "ready")
}

func TestThermal_NoSensorsIsUnavailableButPayloadStaysHealthy(t *testing.T) {
	files := baselineFiles()
	for name := range files {
		if strings.HasPrefix(name, "/sys/class/thermal") || strings.HasPrefix(name, "/sys/class/hwmon") {
			delete(files, name)
		}
	}
	tc := newTestCollector(t, onlyConfig("thermal"), files)

	res := tc.collect(t)

	got := readinessFor(t, res, "host.thermal")
	if got.State != "unavailable" || got.Reason != "no temperature sensors found" {
		t.Errorf("readiness[host.thermal] = %+v, want {unavailable, \"no temperature sensors found\"}", got)
	}
	if res.Payload.Status != "healthy" {
		t.Errorf("Payload.Status = %q, want \"healthy\" — the thermal branch deliberately does not degrade the payload", res.Payload.Status)
	}
}

func TestThermal_SkipsNonNumericSensorWhileSiblingsCollect(t *testing.T) {
	files := baselineFiles()
	files["/sys/class/thermal/thermal_zone0/temp"] = "not-a-number\n"
	tc := newTestCollector(t, onlyConfig("thermal"), files)

	res := tc.collect(t)

	if got := itemNames(res.Payload.Temperatures, "name"); strings.Join(got, ",") != "hwmon0/temp1" {
		t.Errorf("temperatures = %v, want only hwmon0/temp1", got)
	}
	wantFloatPtr(t, "Summary.MaxTempC", res.Payload.Summary.MaxTempC, 61)
}

func TestThermal_SkipsUnreadableSensorWhileSiblingsCollect(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root bypasses file permissions")
	}
	tc := newTestCollector(t, onlyConfig("thermal"), baselineFiles())
	if err := os.Chmod(filepath.Join(tc.root, "sys/class/hwmon/hwmon0/temp1_input"), 0o000); err != nil {
		t.Fatalf("Chmod() error = %v", err)
	}

	res := tc.collect(t)

	if got := itemNames(res.Payload.Temperatures, "name"); strings.Join(got, ",") != "thermal_zone0/temp" {
		t.Errorf("temperatures = %v, want only thermal_zone0/temp", got)
	}
	wantFloatPtr(t, "Summary.MaxTempC", res.Payload.Summary.MaxTempC, 45)
}

func TestThermal_DisabledReportsDisabledWithNilMax(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	res := tc.collect(t)

	wantState(t, res, "host.thermal", "disabled")
	if res.Payload.Summary.MaxTempC != nil {
		t.Errorf("Summary.MaxTempC = %v, want nil", *res.Payload.Summary.MaxTempC)
	}
	if len(res.Payload.Temperatures) != 0 {
		t.Errorf("Temperatures = %v, want empty", res.Payload.Temperatures)
	}
}

// ---------------------------------------------------------------------------
// Collect-wide invariants
// ---------------------------------------------------------------------------

func TestCollect_ReadinessCoversEveryCollector(t *testing.T) {
	wantOrder := []string{"host.core", "host.filesystems", "host.disks", "host.network", "host.thermal", "host.docker"}
	allowed := map[string]bool{"ready": true, "degraded": true, "unavailable": true, "disabled": true}
	everythingOff := capability.HostConfig{IntervalS: 30}
	everythingOn := fullConfig()
	everythingOn.IncludeVirtual = true
	everythingOn.IncludeDocker = true

	cases := []struct {
		name  string
		cfg   capability.HostConfig
		files map[string]string
	}{
		{"all optional collectors disabled", everythingOff, baselineFiles()},
		{"all optional collectors enabled", everythingOn, baselineFiles()},
		{"every optional source missing", fullConfig(), map[string]string{"/proc/stat": baselineProcStat, "/proc/meminfo": baselineMeminfo}},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			tc := newTestCollector(t, tt.cfg, tt.files)

			res := tc.collect(t)

			got := make([]string, 0, len(res.Readiness))
			for _, r := range res.Readiness {
				got = append(got, r.Collector)
				if !allowed[r.State] {
					t.Errorf("readiness[%s].State = %q, want one of ready/degraded/unavailable/disabled", r.Collector, r.State)
				}
			}
			if strings.Join(got, ",") != strings.Join(wantOrder, ",") {
				t.Errorf("readiness collectors = %v, want exactly %v in order", got, wantOrder)
			}
		})
	}
}

func TestCollect_CanceledContextReturnsBeforeAnyRead(t *testing.T) {
	tc := newTestCollector(t, fullConfig(), baselineFiles())
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	res, err := tc.Collect(ctx)

	if err == nil {
		t.Fatal("Collect() error = nil for a canceled context, want context.Canceled")
	}
	if len(res.Readiness) != 0 {
		t.Errorf("Readiness = %+v for a canceled context, want empty (\"no information\")", res.Readiness)
	}
}

func TestCollector_NilNowAndUsageFallBackToRealImplementations(t *testing.T) {
	c := New(capability.HostConfig{IntervalS: 30})
	if c.Now == nil || c.Usage == nil {
		t.Fatalf("New() left Now=%v Usage=%v, want both populated", c.Now == nil, c.Usage == nil)
	}
	bare := &Collector{Root: t.TempDir(), Config: capability.HostConfig{IntervalS: 30}}
	if bare.now().IsZero() {
		t.Error("now() on a struct-literal Collector returned the zero time, want time.Now()")
	}
	if _, err := bare.usage(bare.Root); err != nil {
		t.Errorf("usage() on a struct-literal Collector error = %v, want the statfs fallback to succeed", err)
	}
}

// ---------------------------------------------------------------------------
// CollectorNames: the collector and Task 11's disable path agree by
// construction, so every readiness slice this package produces is exactly one
// entry per name, in CollectorNames order, on every path that reports at all.
// ---------------------------------------------------------------------------

// readinessNames returns the collectors named in a result, in order.
func readinessNames(res collect.Result) []string {
	out := make([]string, 0, len(res.Readiness))
	for _, r := range res.Readiness {
		out = append(out, r.Collector)
	}
	return out
}

func wantCoversCollectorNames(t *testing.T, res collect.Result) {
	t.Helper()
	if got := readinessNames(res); strings.Join(got, ",") != strings.Join(CollectorNames, ",") {
		t.Errorf("readiness collectors = %v, want exactly %v in order", got, CollectorNames)
	}
}

func TestCollectorNames_MatchesTheSixCollectors(t *testing.T) {
	want := []string{"host.core", "host.filesystems", "host.disks", "host.network", "host.thermal", "host.docker"}
	if strings.Join(CollectorNames, ",") != strings.Join(want, ",") {
		t.Errorf("CollectorNames = %v, want %v", CollectorNames, want)
	}
}

func TestCollector_ReadinessCoversAllSixCollectorsOnASuccessfulRun(t *testing.T) {
	cfg := fullConfig()
	cfg.IncludeVirtual = true
	cfg.IncludeDocker = true
	tc := newTestCollector(t, cfg, baselineFiles())

	res := tc.collect(t)

	wantCoversCollectorNames(t, res)
	for _, name := range []string{"host.core", "host.filesystems", "host.disks", "host.network", "host.thermal"} {
		wantState(t, res, name, "ready")
	}
	// The fixture root has no docker socket, so the dial fails fast.
	wantState(t, res, "host.docker", "unavailable")
}

func TestCollector_DisabledProbesReportDisabledNotMissing(t *testing.T) {
	tc := newTestCollector(t, capability.HostConfig{IntervalS: 30}, baselineFiles())

	res := tc.collect(t)

	wantCoversCollectorNames(t, res)
	wantState(t, res, "host.core", "ready")
	for _, name := range CollectorNames[1:] {
		wantState(t, res, name, "disabled")
		if got := readinessFor(t, res, name); got.Reason != "" {
			t.Errorf("readiness[%s].Reason = %q, want empty for a disabled collector", name, got.Reason)
		}
	}
}

// TestCollector_CoreFailureReportsUnavailableAndStillCoversEveryProbe is the
// collector half of the stale-"Live" defect: /proc/stat going unreadable used
// to discard the whole readiness slice, so the backend kept every row at its
// last good state forever.
func TestCollector_CoreFailureReportsUnavailableAndStillCoversEveryProbe(t *testing.T) {
	files := baselineFiles()
	delete(files, "/proc/stat")
	cfg := fullConfig()
	cfg.IncludeDocker = true
	tc := newTestCollector(t, cfg, files)

	res, err := tc.Collect(context.Background())

	if err == nil {
		t.Fatal("Collect() error = nil with /proc/stat absent, want a host core error")
	}
	if !strings.Contains(err.Error(), "host core") {
		t.Errorf("Collect() error = %q, want it to wrap \"host core\"", err)
	}
	// The payload is deliberately zero: a run without core telemetry has
	// nothing worth sending.
	if !reflect.DeepEqual(res.Payload, frame.HostTelemetryPayload{}) {
		t.Errorf("Payload = %+v, want the zero value on a core failure", res.Payload)
	}
	wantCoversCollectorNames(t, res)
	core := readinessFor(t, res, "host.core")
	if core.State != "unavailable" {
		t.Errorf("readiness[host.core].State = %q, want %q", core.State, "unavailable")
	}
	if core.Reason == "" {
		t.Error("readiness[host.core].Reason is empty, want the underlying file error")
	}
	if want := "verify /proc is mounted and readable by the cb-agent user"; core.Remediation != want {
		t.Errorf("readiness[host.core].Remediation = %q, want %q", core.Remediation, want)
	}
	// The optional probes read independent files and are still evaluated, so
	// the operator sees honest per-probe rows rather than six frozen ones.
	for _, name := range []string{"host.filesystems", "host.disks", "host.network", "host.thermal"} {
		wantState(t, res, name, "ready")
	}
	wantState(t, res, "host.docker", "unavailable")
}

// TestCollector_CoreFailureDoesNotPoisonTheNextRunsRateMath pins the skipped
// c.previous assignment: a run that never produced core telemetry must not
// become the baseline the following run computes rates against.
func TestCollector_CoreFailureDoesNotPoisonTheNextRunsRateMath(t *testing.T) {
	tc := newTestCollector(t, onlyConfig("disks"), baselineFiles())
	tc.collect(t)

	// A run with core broken, ten seconds in. Its counters must be discarded.
	tc.remove(t, "/proc/stat")
	tc.advance(10 * time.Second)
	if _, err := tc.Collect(context.Background()); err == nil {
		t.Fatal("Collect() error = nil with /proc/stat absent, want a host core error")
	}

	tc.write(t, map[string]string{"/proc/stat": baselineProcStat, "/proc/diskstats": busyDiskstats})
	tc.advance(10 * time.Second)
	res := tc.collect(t)

	// +102400 bytes read over the *twenty* seconds since the last good sample.
	sda := mustItem(t, res.Payload.Disks, "device", "sda")
	if got := itemFloat(t, sda, "read_bps"); got != 5120 {
		t.Errorf("sda read_bps = %v, want 5120 (102400 bytes over 20s); 10240 means the failed run became the baseline", got)
	}
}

// TestCollector_ReadinessSurfacesCollectorsMissingFromCollectorNames pins the
// other drift direction: a probe that exists in Collect but was never added to
// CollectorNames. Filtering the readiness slice through CollectorNames would
// discard that probe's row silently — the same stale-"Live" defect this file
// exists to prevent, moved one layer down — so the row must still reach the
// caller, and it must land out of the declared order so
// wantCoversCollectorNames fails loudly instead of passing green.
func TestCollector_ReadinessSurfacesCollectorsMissingFromCollectorNames(t *testing.T) {
	original := CollectorNames
	shortened := append([]string(nil), original[:len(original)-1]...) // drop host.docker
	CollectorNames = shortened
	t.Cleanup(func() { CollectorNames = original })

	cfg := fullConfig()
	cfg.IncludeDocker = true
	tc := newTestCollector(t, cfg, baselineFiles())

	res := tc.collect(t)

	got := readinessNames(res)
	if len(got) != len(original) {
		t.Fatalf("readiness collectors = %v, want %d entries including the unlisted collector", got, len(original))
	}
	if last := got[len(got)-1]; last != "host.docker" {
		t.Errorf("readiness collectors = %v, want the unlisted collector %q appended last", got, "host.docker")
	}
	// The fixture root has no docker socket, so the dial fails fast.
	wantState(t, res, "host.docker", "unavailable")

	// And the coverage guard must reject that slice rather than accept it.
	fake := new(testing.T)
	wantCoversCollectorNames(fake, res)
	if !fake.Failed() {
		t.Error("wantCoversCollectorNames accepted a readiness slice containing a collector absent from CollectorNames; the drift guard is inert")
	}
}
