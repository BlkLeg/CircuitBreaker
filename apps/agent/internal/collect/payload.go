package collect

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

const MaxPayloadBytes = 256 << 10

func SampleID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func stableSort(items []map[string]any) {
	sort.SliceStable(items, func(i, j int) bool {
		for _, key := range []string{"device", "name", "mountpoint", "interface", "id"} {
			a, aok := items[i][key].(string)
			b, bok := items[j][key].(string)
			if aok || bok {
				return a < b
			}
		}
		return false
	})
}

func EncodeBounded(payload *frame.HostTelemetryPayload) (json.RawMessage, error) {
	if payload.Schema != 1 {
		return nil, errors.New("collect: unsupported host telemetry schema")
	}
	for _, list := range [][]map[string]any{payload.Filesystems, payload.Disks, payload.Interfaces, payload.Temperatures} {
		stableSort(list)
	}
	if len(payload.Filesystems) > 128 {
		payload.Filesystems = payload.Filesystems[:128]
		payload.Status = "degraded"
	}
	if len(payload.Disks) > 128 {
		payload.Disks = payload.Disks[:128]
		payload.Status = "degraded"
	}
	if len(payload.Interfaces) > 128 {
		payload.Interfaces = payload.Interfaces[:128]
		payload.Status = "degraded"
	}
	if len(payload.Temperatures) > 256 {
		payload.Temperatures = payload.Temperatures[:256]
		payload.Status = "degraded"
	}
	for {
		data, err := json.Marshal(payload)
		if err != nil {
			return nil, err
		}
		if len(data) <= MaxPayloadBytes {
			return data, nil
		}
		payload.Status = "degraded"
		dockerContainers, _ := dockerContainers(payload.Docker)
		switch {
		case len(payload.Temperatures) > 0:
			payload.Temperatures = payload.Temperatures[:len(payload.Temperatures)-1]
		case len(payload.Interfaces) > 0:
			payload.Interfaces = payload.Interfaces[:len(payload.Interfaces)-1]
		case len(payload.Disks) > 0:
			payload.Disks = payload.Disks[:len(payload.Disks)-1]
		case len(payload.Filesystems) > 0:
			payload.Filesystems = payload.Filesystems[:len(payload.Filesystems)-1]
		case len(dockerContainers) > 0:
			setDockerContainers(payload.Docker, dockerContainers[:len(dockerContainers)-1])
		default:
			return nil, errors.New("collect: core telemetry exceeds payload limit")
		}
	}
}

func dockerContainers(value any) ([]map[string]any, bool) {
	docker, ok := value.(map[string]any)
	if !ok {
		return nil, false
	}
	containers, ok := docker["containers"].([]map[string]any)
	return containers, ok
}

func setDockerContainers(value any, containers []map[string]any) {
	docker, ok := value.(map[string]any)
	if !ok {
		return
	}
	docker["containers"] = containers
	docker["truncated"] = true
}

func Rate(previous, current uint64, elapsed time.Duration) *float64 {
	if elapsed <= 0 || current < previous {
		return nil
	}
	v := float64(current-previous) / elapsed.Seconds()
	return &v
}
