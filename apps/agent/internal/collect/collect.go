package collect

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

type Result struct {
	Payload   frame.HostTelemetryPayload
	Readiness []frame.Readiness
}

// Collector produces one telemetry sample per call.
//
// Collect must populate Result.Readiness for every collector it owns **even
// when it returns a non-nil error** — readiness is the only channel by which a
// broken probe stops showing as healthy, and a caller that only reports on
// success leaves the backend's rows frozen at their last good state. The one
// exception is context cancellation: an empty Readiness alongside an error
// means "no information" and is not reported, so a shutdown is never recorded
// as an outage. Readiness states are exactly ready | degraded | unavailable |
// disabled (apps/backend/src/app/services/agent_telemetry.py is authoritative).
type Collector interface {
	Collect(context.Context) (Result, error)
}

// Runner executes immediately and then on cadence. At most one collection is
// active; Reset changes cadence live, and Stop cancels an in-flight probe.
type Runner struct {
	collector   Collector
	out         chan<- frame.Frame
	OnReadiness func([]frame.Readiness)
	mu          sync.Mutex
	cancel      context.CancelFunc
}

func NewRunner(collector Collector, out chan<- frame.Frame) *Runner {
	return &Runner{collector: collector, out: out}
}

func (r *Runner) Reset(parent context.Context, interval time.Duration) {
	r.Stop()
	ctx, cancel := context.WithCancel(parent)
	r.mu.Lock()
	r.cancel = cancel
	r.mu.Unlock()
	go r.run(ctx, interval)
}

func (r *Runner) Stop() {
	r.mu.Lock()
	if r.cancel != nil {
		r.cancel()
		r.cancel = nil
	}
	r.mu.Unlock()
}

func (r *Runner) run(ctx context.Context, interval time.Duration) {
	timer := time.NewTimer(0)
	defer timer.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
			collectedAt := time.Now().UTC()
			result, err := r.collector.Collect(ctx)
			if ctx.Err() != nil {
				// A stop is not an outage: nothing this collection produced
				// may be reported.
				return
			}
			var (
				payload json.RawMessage
				encErr  error
			)
			if err == nil {
				originalStatus := result.Payload.Status
				payload, encErr = EncodeBounded(&result.Payload)
				switch {
				case encErr != nil:
					result.Readiness = append(result.Readiness, frame.Readiness{Collector: "host.payload", State: "unavailable", Reason: encErr.Error()})
				case originalStatus != "degraded" && result.Payload.Status == "degraded":
					result.Readiness = append(result.Readiness, frame.Readiness{Collector: "host.payload", State: "degraded", Reason: "telemetry exceeded the payload limit and optional detail was truncated"})
				}
			}
			// Readiness survives both failure paths; only the frame does not.
			if len(result.Readiness) > 0 && r.OnReadiness != nil {
				r.OnReadiness(result.Readiness)
			}
			if err == nil && encErr == nil {
				select {
				case r.out <- frame.Frame{Type: frame.TypeTelemetryHost, TS: collectedAt, Payload: payload}:
				case <-ctx.Done():
					return
				}
			}
			timer.Reset(interval)
		}
	}
}
