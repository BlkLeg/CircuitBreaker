package collect

import (
	"context"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

type Result struct {
	Payload   frame.HostTelemetryPayload
	Readiness []frame.Readiness
}

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
			if err == nil {
				originalStatus := result.Payload.Status
				payload, marshalErr := EncodeBounded(&result.Payload)
				if marshalErr == nil {
					if originalStatus != "degraded" && result.Payload.Status == "degraded" {
						result.Readiness = append(result.Readiness, frame.Readiness{Collector: "host.payload", State: "degraded", Reason: "telemetry exceeded the payload limit and optional detail was truncated"})
					}
					if r.OnReadiness != nil {
						r.OnReadiness(result.Readiness)
					}
					select {
					case r.out <- frame.Frame{Type: frame.TypeTelemetryHost, TS: collectedAt, Payload: payload}:
					case <-ctx.Done():
						return
					}
				}
			}
			timer.Reset(interval)
		}
	}
}
