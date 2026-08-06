package host

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

type dockerContainer struct {
	ID     string   `json:"Id"`
	Names  []string `json:"Names"`
	Image  string   `json:"Image"`
	State  string   `json:"State"`
	Status string   `json:"Status"`
}

type dockerStats struct {
	CPUStats struct {
		CPUUsage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		System uint64 `json:"system_cpu_usage"`
		Online int    `json:"online_cpus"`
	} `json:"cpu_stats"`
	PreCPUStats struct {
		CPUUsage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		System uint64 `json:"system_cpu_usage"`
	} `json:"precpu_stats"`
	Memory struct {
		Usage uint64 `json:"usage"`
		Limit uint64 `json:"limit"`
	} `json:"memory_stats"`
	Networks map[string]struct {
		RX uint64 `json:"rx_bytes"`
		TX uint64 `json:"tx_bytes"`
	} `json:"networks"`
}

func dockerStatsSummary(ctx context.Context, client *http.Client, id string) map[string]any {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://docker/v1.41/containers/"+id+"/stats?stream=false", nil)
	if err != nil {
		return nil
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil
	}
	var stats dockerStats
	if json.NewDecoder(io.LimitReader(resp.Body, 2<<20)).Decode(&stats) != nil {
		return nil
	}
	out := map[string]any{"memory_used_bytes": stats.Memory.Usage, "memory_limit_bytes": stats.Memory.Limit}
	if stats.Memory.Limit > 0 {
		out["memory_pct"] = float64(stats.Memory.Usage) * 100 / float64(stats.Memory.Limit)
	}
	if stats.CPUStats.CPUUsage.Total >= stats.PreCPUStats.CPUUsage.Total && stats.CPUStats.System > stats.PreCPUStats.System && stats.CPUStats.Online > 0 {
		out["cpu_pct"] = float64(stats.CPUStats.CPUUsage.Total-stats.PreCPUStats.CPUUsage.Total) * float64(stats.CPUStats.Online) * 100 / float64(stats.CPUStats.System-stats.PreCPUStats.System)
	}
	var rx, tx uint64
	for _, network := range stats.Networks {
		rx += network.RX
		tx += network.TX
	}
	out["network_rx_bytes"], out["network_tx_bytes"] = rx, tx
	return out
}

func (c *Collector) docker(ctx context.Context, p *frame.HostTelemetryPayload) error {
	socket := c.path("/var/run/docker.sock")
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "unix", socket)
	}}
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	statsCtx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://docker/v1.41/containers/json?all=1", nil)
	if err != nil {
		return err
	}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("open Docker socket: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("Docker API returned %s", response.Status)
	}
	var containers []dockerContainer
	if err := json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(&containers); err != nil {
		return fmt.Errorf("decode Docker response: %w", err)
	}
	truncated := len(containers) > 100
	if truncated {
		containers = containers[:100]
	}
	items := make([]map[string]any, 0, len(containers))
	running := 0
	for _, item := range containers {
		name := ""
		if len(item.Names) > 0 {
			name = item.Names[0]
		}
		summary := map[string]any{"id": item.ID, "name": name, "image": item.Image, "state": item.State, "status": item.Status}
		if item.State == "running" {
			running++
			for key, value := range dockerStatsSummary(statsCtx, client, item.ID) {
				summary[key] = value
			}
		}
		items = append(items, summary)
	}
	p.Docker = map[string]any{"containers": items, "total": len(items), "running": running, "truncated": truncated}
	if truncated {
		p.Status = "degraded"
	}
	return nil
}
