package host

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/collect"
	"circuitbreaker.dev/cb-agent/internal/frame"
)

type counters struct {
	at                time.Time
	cpuIdle, cpuTotal uint64
	disk              map[string][2]uint64
	net               map[string][2]uint64
}

// FSUsage is a filesystem-space snapshot in bytes. It is the injectable form of
// the syscall.Statfs_t fields the filesystems probe consumes, so tests can pin
// byte math without depending on whatever backs the test's temp directory.
type FSUsage struct {
	TotalBytes uint64
	FreeBytes  uint64
	AvailBytes uint64
}

// statfsUsage is the production Usage implementation.
func statfsUsage(path string) (FSUsage, error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return FSUsage{}, err
	}
	blockSize := uint64(st.Bsize)
	return FSUsage{TotalBytes: st.Blocks * blockSize, FreeBytes: st.Bfree * blockSize, AvailBytes: st.Bavail * blockSize}, nil
}

// Collector reads host telemetry out of /proc and /sys. Root, Now and Usage are
// the only three seams into the outside world: every file read is rooted at
// Root, the sample clock comes from Now, and filesystem space comes from Usage.
// All three fall back to the real implementations when left nil, so a struct
// literal is usable without wiring.
type Collector struct {
	Root     string
	Config   capability.HostConfig
	Now      func() time.Time
	Usage    func(path string) (FSUsage, error)
	mu       sync.Mutex
	previous counters
}

// CollectorNames is every collector this package reports readiness for, in the
// order Collect emits them. It is exported so the capability-disable path can
// publish a "disabled" row for each one without re-deriving the list: a probe
// added to Collect but not to CollectorNames would leave a row that is never
// flipped, which is the stale-"Live" defect in a different coat.
var CollectorNames = []string{"host.core", "host.filesystems", "host.disks", "host.network", "host.thermal", "host.docker"}

func New(config capability.HostConfig) *Collector {
	return &Collector{Root: "/", Config: config, Now: time.Now, Usage: statfsUsage}
}
func (c *Collector) path(name string) string {
	return filepath.Join(c.Root, strings.TrimPrefix(name, "/"))
}
func (c *Collector) now() time.Time {
	if c.Now == nil {
		return time.Now()
	}
	return c.Now()
}
func (c *Collector) usage(path string) (FSUsage, error) {
	if c.Usage == nil {
		return statfsUsage(path)
	}
	return c.Usage(path)
}
func ptr[T any](v T) *T { return &v }

// Collect gathers one host telemetry sample. Per the collect.Collector
// contract it populates Result.Readiness for every name in CollectorNames even
// when it returns an error, so an outage in one probe — or in core telemetry
// itself — reaches the backend instead of leaving stale rows behind. The one
// exception is a canceled context: an empty Readiness alongside an error means
// "no information", and a shutdown must not be reported as an outage.
func (c *Collector) Collect(ctx context.Context) (collect.Result, error) {
	if err := ctx.Err(); err != nil {
		return collect.Result{}, err
	}
	// States are keyed by collector name and emitted in CollectorNames order.
	// Nothing recorded is ever dropped: a name the exported list does not know
	// about is appended after them, so drift is visible rather than silent.
	states := make(map[string]frame.Readiness, len(CollectorNames))
	record := func(r frame.Readiness) { states[r.Collector] = r }
	readiness := func() []frame.Readiness {
		out := make([]frame.Readiness, 0, len(states))
		listed := make(map[string]struct{}, len(CollectorNames))
		for _, name := range CollectorNames {
			listed[name] = struct{}{}
			if r, ok := states[name]; ok {
				out = append(out, r)
			}
		}
		// A collector recorded under a name absent from CollectorNames is
		// drift: Task 11's disable path iterates CollectorNames, so that row
		// would never be flipped to "disabled". Dropping it here would be
		// worse — its readiness would never reach the backend at all, which is
		// the stale-"Live" defect one layer down — so emit it, out of the
		// declared order, where the coverage tests fail loudly on it.
		if len(out) != len(states) {
			extra := make([]string, 0, len(states)-len(out))
			for name := range states {
				if _, ok := listed[name]; !ok {
					extra = append(extra, name)
				}
			}
			sort.Strings(extra)
			for _, name := range extra {
				out = append(out, states[name])
			}
		}
		return out
	}
	id, err := collect.SampleID()
	if err != nil {
		record(frame.Readiness{Collector: "host.core", State: "unavailable", Reason: "could not generate sample id"})
		return collect.Result{Readiness: readiness()}, err
	}
	now := c.now()
	p := frame.HostTelemetryPayload{Schema: 1, SampleID: id, Status: "healthy", Filesystems: []map[string]any{}, Disks: []map[string]any{}, Interfaces: []map[string]any{}, Temperatures: []map[string]any{}}
	c.mu.Lock()
	defer c.mu.Unlock()
	next := counters{at: now, disk: map[string][2]uint64{}, net: map[string][2]uint64{}}
	coreErr := c.core(&p, &next)
	if coreErr != nil {
		record(frame.Readiness{Collector: "host.core", State: "unavailable", Reason: coreErr.Error(), Remediation: "verify /proc is mounted and readable by the cb-agent user"})
		p.Status = "unavailable"
	} else {
		record(frame.Readiness{Collector: "host.core", State: "ready"})
	}
	// The optional probes read files independent of core telemetry, so they are
	// evaluated even after a core failure: a few extra reads on a broken host
	// buys honest per-probe rows instead of six frozen ones.
	optional := func(name string, enabled bool, fn func(*frame.HostTelemetryPayload, *counters) error) {
		if !enabled {
			record(frame.Readiness{Collector: name, State: "disabled"})
			return
		}
		if err := fn(&p, &next); err != nil {
			p.Status = "degraded"
			record(frame.Readiness{Collector: name, State: "unavailable", Reason: err.Error()})
		} else {
			record(frame.Readiness{Collector: name, State: "ready"})
		}
	}
	optional("host.filesystems", c.Config.IncludeFilesystems, c.filesystems)
	optional("host.disks", c.Config.IncludeDisks, c.disks)
	optional("host.network", c.Config.IncludeNetwork, c.network)
	if c.Config.IncludeTemperatures {
		if err := c.thermal(&p, &next); err != nil {
			record(frame.Readiness{Collector: "host.thermal", State: "unavailable", Reason: err.Error()})
		} else {
			record(frame.Readiness{Collector: "host.thermal", State: "ready"})
		}
	} else {
		record(frame.Readiness{Collector: "host.thermal", State: "disabled"})
	}
	if c.Config.IncludeDocker {
		if err := c.docker(ctx, &p); err != nil {
			record(frame.Readiness{Collector: "host.docker", State: "unavailable", Reason: err.Error(), Remediation: "rerun the installer and verify membership in the docker group"})
			p.Status = "degraded"
		} else {
			record(frame.Readiness{Collector: "host.docker", State: "ready"})
		}
	} else {
		record(frame.Readiness{Collector: "host.docker", State: "disabled"})
	}
	if coreErr != nil {
		// The counter snapshot is partial, so it must not become the baseline
		// the next run computes rates against; and there is no payload worth
		// sending without core telemetry.
		return collect.Result{Readiness: readiness()}, fmt.Errorf("host core: %w", coreErr)
	}
	c.previous = next
	return collect.Result{Payload: p, Readiness: readiness()}, nil
}

func fields(path string) ([]string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return strings.Fields(string(b)), nil
}
func percent(used, total uint64) *float64 {
	if total == 0 {
		return nil
	}
	return ptr(float64(used) * 100 / float64(total))
}

func (c *Collector) core(p *frame.HostTelemetryPayload, next *counters) error {
	f, err := os.Open(c.path("/proc/stat"))
	if err != nil {
		return err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	if !s.Scan() {
		return fmt.Errorf("missing aggregate cpu line")
	}
	parts := strings.Fields(s.Text())
	if len(parts) < 5 || parts[0] != "cpu" {
		return fmt.Errorf("invalid aggregate cpu line")
	}
	for i, value := range parts[1:] {
		n, e := strconv.ParseUint(value, 10, 64)
		if e != nil {
			return e
		}
		next.cpuTotal += n
		if i == 3 || i == 4 {
			next.cpuIdle += n
		}
	}
	logicalCPUs := 0
	for s.Scan() {
		line := strings.Fields(s.Text())
		if len(line) > 0 && strings.HasPrefix(line[0], "cpu") && len(line[0]) > 3 {
			logicalCPUs++
		}
		if len(line) == 2 && line[0] == "btime" {
			if value, parseErr := strconv.ParseUint(line[1], 10, 64); parseErr == nil {
				p.Summary.BootTimeUnixS = &value
			}
			break
		}
	}
	if logicalCPUs > 0 {
		p.Summary.LogicalCPUs = ptr(logicalCPUs)
	}
	if c.previous.cpuTotal > 0 && next.cpuTotal >= c.previous.cpuTotal && next.cpuIdle >= c.previous.cpuIdle {
		total := next.cpuTotal - c.previous.cpuTotal
		idle := next.cpuIdle - c.previous.cpuIdle
		if total > 0 {
			p.Summary.CPUPct = ptr(float64(total-idle) * 100 / float64(total))
		}
	}
	if loads, e := fields(c.path("/proc/loadavg")); e == nil && len(loads) >= 3 {
		a, _ := strconv.ParseFloat(loads[0], 64)
		b, _ := strconv.ParseFloat(loads[1], 64)
		d, _ := strconv.ParseFloat(loads[2], 64)
		p.Summary.Load1 = &a
		p.Summary.Load5 = &b
		p.Summary.Load15 = &d
	}
	mem, err := os.Open(c.path("/proc/meminfo"))
	if err != nil {
		return err
	}
	defer mem.Close()
	values := map[string]uint64{}
	s = bufio.NewScanner(mem)
	for s.Scan() {
		x := strings.Fields(s.Text())
		if len(x) >= 2 {
			n, _ := strconv.ParseUint(x[1], 10, 64)
			values[strings.TrimSuffix(x[0], ":")] = n * 1024
		}
	}
	total, avail := values["MemTotal"], values["MemAvailable"]
	if total == 0 {
		return fmt.Errorf("MemTotal unavailable")
	}
	used := total - avail
	p.Summary.MemTotalBytes = &total
	p.Summary.MemAvailableBytes = &avail
	p.Summary.MemUsedBytes = &used
	p.Summary.MemPct = percent(used, total)
	swapTotal, swapFree := values["SwapTotal"], values["SwapFree"]
	swapUsed := swapTotal - swapFree
	p.Summary.SwapTotalBytes = &swapTotal
	p.Summary.SwapUsedBytes = &swapUsed
	p.Summary.SwapPct = percent(swapUsed, swapTotal)
	if up, e := fields(c.path("/proc/uptime")); e == nil && len(up) > 0 {
		v, _ := strconv.ParseFloat(up[0], 64)
		p.Summary.UptimeS = &v
	}
	return nil
}

var pseudoFS = map[string]bool{"proc": true, "sysfs": true, "devtmpfs": true, "devpts": true, "tmpfs": true, "cgroup": true, "cgroup2": true, "overlay": true, "squashfs": true, "tracefs": true, "debugfs": true, "securityfs": true, "pstore": true, "configfs": true, "fusectl": true, "mqueue": true}

func (c *Collector) filesystems(p *frame.HostTelemetryPayload, _ *counters) error {
	f, err := os.Open(c.path("/proc/self/mounts"))
	if err != nil {
		return err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	for s.Scan() {
		x := strings.Fields(s.Text())
		if len(x) < 4 || pseudoFS[x[2]] {
			continue
		}
		u, usageErr := c.usage(c.path(x[1]))
		if usageErr != nil {
			continue
		}
		total := u.TotalBytes
		avail := u.AvailBytes
		used := total - u.FreeBytes
		item := map[string]any{"device": x[0], "mountpoint": x[1], "fs_type": x[2], "total_bytes": total, "used_bytes": used, "available_bytes": avail, "read_only": strings.Contains(","+x[3]+",", ",ro,")}
		if pct := percent(used, total); pct != nil {
			item["used_pct"] = *pct
			if x[1] == "/" {
				p.Summary.RootDiskPct = pct
			}
		}
		p.Filesystems = append(p.Filesystems, item)
	}
	return s.Err()
}

func virtualDevice(name string) bool {
	return strings.HasPrefix(name, "loop") || strings.HasPrefix(name, "ram") || strings.HasPrefix(name, "dm-")
}
func (c *Collector) disks(p *frame.HostTelemetryPayload, next *counters) error {
	f, err := os.Open(c.path("/proc/diskstats"))
	if err != nil {
		return err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	elapsed := next.at.Sub(c.previous.at)
	for s.Scan() {
		x := strings.Fields(s.Text())
		if len(x) < 14 {
			continue
		}
		name := x[2]
		if !c.Config.IncludeVirtual && virtualDevice(name) {
			continue
		}
		reads, _ := strconv.ParseUint(x[5], 10, 64)
		writes, _ := strconv.ParseUint(x[9], 10, 64)
		reads *= 512
		writes *= 512
		next.disk[name] = [2]uint64{reads, writes}
		item := map[string]any{"device": name, "read_bytes": reads, "write_bytes": writes}
		if old, ok := c.previous.disk[name]; ok {
			if r := collect.Rate(old[0], reads, elapsed); r != nil {
				item["read_bps"] = *r
			}
			if r := collect.Rate(old[1], writes, elapsed); r != nil {
				item["write_bps"] = *r
			}
		}
		p.Disks = append(p.Disks, item)
	}
	return s.Err()
}

func (c *Collector) network(p *frame.HostTelemetryPayload, next *counters) error {
	f, err := os.Open(c.path("/proc/net/dev"))
	if err != nil {
		return err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	elapsed := next.at.Sub(c.previous.at)
	var rxRate, txRate float64
	for s.Scan() {
		line := strings.TrimSpace(s.Text())
		if !strings.Contains(line, ":") {
			continue
		}
		halves := strings.SplitN(line, ":", 2)
		name := strings.TrimSpace(halves[0])
		if name == "lo" || (!c.Config.IncludeVirtual && (strings.HasPrefix(name, "veth") || strings.HasPrefix(name, "docker") || strings.HasPrefix(name, "br-"))) {
			continue
		}
		state, _ := os.ReadFile(c.path("/sys/class/net/" + name + "/operstate"))
		up := strings.TrimSpace(string(state))
		if up == "down" {
			continue
		}
		x := strings.Fields(halves[1])
		if len(x) < 16 {
			continue
		}
		rx, _ := strconv.ParseUint(x[0], 10, 64)
		tx, _ := strconv.ParseUint(x[8], 10, 64)
		next.net[name] = [2]uint64{rx, tx}
		item := map[string]any{"name": name, "state": up, "rx_bytes": rx, "tx_bytes": tx, "rx_errors": parse(x[2]), "tx_errors": parse(x[10])}
		if speed, readErr := os.ReadFile(c.path("/sys/class/net/" + name + "/speed")); readErr == nil {
			if mbps, parseErr := strconv.ParseUint(strings.TrimSpace(string(speed)), 10, 64); parseErr == nil {
				item["speed_mbps"] = mbps
			}
		}
		if old, ok := c.previous.net[name]; ok {
			if r := collect.Rate(old[0], rx, elapsed); r != nil {
				item["rx_bps"] = *r
				rxRate += *r
			}
			if r := collect.Rate(old[1], tx, elapsed); r != nil {
				item["tx_bps"] = *r
				txRate += *r
			}
		}
		p.Interfaces = append(p.Interfaces, item)
	}
	if c.previous.at.IsZero() == false {
		p.Summary.NetRXBPS = &rxRate
		p.Summary.NetTXBPS = &txRate
	}
	return s.Err()
}
func parse(v string) uint64 { n, _ := strconv.ParseUint(v, 10, 64); return n }

func (c *Collector) thermal(p *frame.HostTelemetryPayload, _ *counters) error {
	paths, _ := filepath.Glob(c.path("/sys/class/thermal/thermal_zone*/temp"))
	hw, _ := filepath.Glob(c.path("/sys/class/hwmon/hwmon*/temp*_input"))
	paths = append(paths, hw...)
	sort.Strings(paths)
	var max *float64
	for _, path := range paths {
		b, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		milli, err := strconv.ParseFloat(strings.TrimSpace(string(b)), 64)
		if err != nil {
			continue
		}
		v := milli / 1000
		name := filepath.Base(filepath.Dir(path)) + "/" + strings.TrimSuffix(filepath.Base(path), "_input")
		item := map[string]any{"name": name, "temp_c": v}
		if strings.HasSuffix(path, "_input") {
			base := strings.TrimSuffix(path, "_input")
			for file, key := range map[string]string{"_max": "warning_c", "_crit": "critical_c"} {
				if threshold, readErr := os.ReadFile(base + file); readErr == nil {
					if parsed, parseErr := strconv.ParseFloat(strings.TrimSpace(string(threshold)), 64); parseErr == nil {
						item[key] = parsed / 1000
					}
				}
			}
		}
		p.Temperatures = append(p.Temperatures, item)
		if max == nil || v > *max {
			max = ptr(v)
		}
	}
	if len(p.Temperatures) == 0 {
		return fmt.Errorf("no temperature sensors found")
	}
	p.Summary.MaxTempC = max
	return nil
}
