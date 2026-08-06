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

type Collector struct {
	Root     string
	Config   capability.HostConfig
	Now      func() time.Time
	mu       sync.Mutex
	previous counters
}

func New(config capability.HostConfig) *Collector {
	return &Collector{Root: "/", Config: config, Now: time.Now}
}
func (c *Collector) path(name string) string {
	return filepath.Join(c.Root, strings.TrimPrefix(name, "/"))
}
func ptr[T any](v T) *T { return &v }

func (c *Collector) Collect(ctx context.Context) (collect.Result, error) {
	if err := ctx.Err(); err != nil {
		return collect.Result{}, err
	}
	id, err := collect.SampleID()
	if err != nil {
		return collect.Result{}, err
	}
	now := c.Now()
	p := frame.HostTelemetryPayload{Schema: 1, SampleID: id, Status: "healthy", Filesystems: []map[string]any{}, Disks: []map[string]any{}, Interfaces: []map[string]any{}, Temperatures: []map[string]any{}}
	readiness := []frame.Readiness{}
	c.mu.Lock()
	defer c.mu.Unlock()
	next := counters{at: now, disk: map[string][2]uint64{}, net: map[string][2]uint64{}}
	if err := c.core(&p, &next); err != nil {
		return collect.Result{}, fmt.Errorf("host core: %w", err)
	}
	readiness = append(readiness, frame.Readiness{Collector: "host.core", State: "ready"})
	optional := func(name string, enabled bool, fn func(*frame.HostTelemetryPayload, *counters) error) {
		if !enabled {
			readiness = append(readiness, frame.Readiness{Collector: name, State: "disabled"})
			return
		}
		if err := fn(&p, &next); err != nil {
			p.Status = "degraded"
			readiness = append(readiness, frame.Readiness{Collector: name, State: "unavailable", Reason: err.Error()})
		} else {
			readiness = append(readiness, frame.Readiness{Collector: name, State: "ready"})
		}
	}
	optional("host.filesystems", c.Config.IncludeFilesystems, c.filesystems)
	optional("host.disks", c.Config.IncludeDisks, c.disks)
	optional("host.network", c.Config.IncludeNetwork, c.network)
	if c.Config.IncludeTemperatures {
		if err := c.thermal(&p, &next); err != nil {
			readiness = append(readiness, frame.Readiness{Collector: "host.thermal", State: "unavailable", Reason: err.Error()})
		} else {
			readiness = append(readiness, frame.Readiness{Collector: "host.thermal", State: "ready"})
		}
	} else {
		readiness = append(readiness, frame.Readiness{Collector: "host.thermal", State: "disabled"})
	}
	if c.Config.IncludeDocker {
		if err := c.docker(ctx, &p); err != nil {
			readiness = append(readiness, frame.Readiness{Collector: "host.docker", State: "unavailable", Reason: err.Error(), Remediation: "rerun the installer and verify membership in the docker group"})
			p.Status = "degraded"
		} else {
			readiness = append(readiness, frame.Readiness{Collector: "host.docker", State: "ready"})
		}
	} else {
		readiness = append(readiness, frame.Readiness{Collector: "host.docker", State: "disabled"})
	}
	c.previous = next
	return collect.Result{Payload: p, Readiness: readiness}, nil
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
		var st syscall.Statfs_t
		if err := syscall.Statfs(c.path(x[1]), &st); err != nil {
			continue
		}
		total := st.Blocks * uint64(st.Bsize)
		avail := st.Bavail * uint64(st.Bsize)
		used := total - st.Bfree*uint64(st.Bsize)
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
