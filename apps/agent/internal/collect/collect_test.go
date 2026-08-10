package collect

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// ---------------------------------------------------------------------------
// Harness.
// ---------------------------------------------------------------------------

// fakeCollector is the shared Collector double for the Runner tests: it can
// return a canned Result, return an error, stall until its context is done, and
// it records call ordinals, entry timestamps and peak concurrency through
// atomics so the tests stay race-detector clean.
//
// Task 9 (readiness on the failure paths) consumes this type — extend it here
// rather than declaring a second double in this package.
type fakeCollector struct {
	// result and err are returned when fn is nil.
	result Result
	err    error
	// delay holds Collect for that long, or until the context is done —
	// whichever comes first. A delay well past the test's lifetime is how a
	// collector that "blocks on ctx.Done" is expressed.
	delay time.Duration
	// fn, when set, replaces the canned behaviour entirely. n is the 1-based
	// call ordinal so a test can vary the outcome per collection.
	fn func(ctx context.Context, n int) (Result, error)

	calls     atomic.Int64
	active    atomic.Int64
	maxActive atomic.Int64
	// entered receives the wall clock at each Collect entry; buffered, so a
	// test that stops reading never wedges the runner.
	entered chan time.Time
	// returned receives the error each Collect returned with.
	returned chan error
}

func newFakeCollector() *fakeCollector {
	return &fakeCollector{result: okResult(), entered: make(chan time.Time, 64), returned: make(chan error, 64)}
}

func (f *fakeCollector) Collect(ctx context.Context) (Result, error) {
	n := int(f.calls.Add(1))
	active := f.active.Add(1)
	for {
		peak := f.maxActive.Load()
		if active <= peak || f.maxActive.CompareAndSwap(peak, active) {
			break
		}
	}
	defer f.active.Add(-1)
	select {
	case f.entered <- time.Now().UTC():
	default:
	}
	if f.delay > 0 {
		timer := time.NewTimer(f.delay)
		defer timer.Stop()
		select {
		case <-timer.C:
		case <-ctx.Done():
			f.report(ctx.Err())
			return Result{}, ctx.Err()
		}
	}
	var (
		res Result
		err error
	)
	if f.fn != nil {
		res, err = f.fn(ctx, n)
	} else {
		res, err = f.result, f.err
	}
	f.report(err)
	return res, err
}

func (f *fakeCollector) report(err error) {
	select {
	case f.returned <- err:
	default:
	}
}

// okResult is the smallest Result EncodeBounded accepts.
func okResult() Result {
	return Result{
		Payload:   frame.HostTelemetryPayload{Schema: 1, SampleID: "0123456789abcdef0123456789abcdef", Status: "healthy", Filesystems: []map[string]any{}, Disks: []map[string]any{}, Interfaces: []map[string]any{}, Temperatures: []map[string]any{}},
		Readiness: []frame.Readiness{{Collector: "host.core", State: "ready"}},
	}
}

// startRunner wires a runner to a buffered frame channel and guarantees Stop.
func startRunner(t *testing.T, collector Collector, interval time.Duration) (*Runner, chan frame.Frame) {
	t.Helper()
	out := make(chan frame.Frame, 64)
	runner := NewRunner(collector, out)
	t.Cleanup(runner.Stop)
	runner.Reset(context.Background(), interval)
	return runner, out
}

// startRunnerWithReadiness is startRunner plus a buffered OnReadiness sink, for
// the tests that assert what the runner reports rather than what it sends.
func startRunnerWithReadiness(t *testing.T, collector Collector, interval time.Duration) (*Runner, chan frame.Frame, chan []frame.Readiness) {
	t.Helper()
	out := make(chan frame.Frame, 64)
	reported := make(chan []frame.Readiness, 64)
	runner := NewRunner(collector, out)
	runner.OnReadiness = func(r []frame.Readiness) { reported <- r }
	t.Cleanup(runner.Stop)
	runner.Reset(context.Background(), interval)
	return runner, out, reported
}

func recvReadiness(t *testing.T, reported <-chan []frame.Readiness, within time.Duration) []frame.Readiness {
	t.Helper()
	select {
	case r := <-reported:
		return r
	case <-time.After(within):
		t.Fatalf("OnReadiness was not called within %s", within)
		return nil
	}
}

func wantNoReadiness(t *testing.T, reported <-chan []frame.Readiness, quiet time.Duration) {
	t.Helper()
	select {
	case r := <-reported:
		t.Fatalf("OnReadiness called with %+v, want no report at all", r)
	case <-time.After(quiet):
	}
}

func recvFrame(t *testing.T, out <-chan frame.Frame, within time.Duration) frame.Frame {
	t.Helper()
	select {
	case f := <-out:
		return f
	case <-time.After(within):
		t.Fatalf("no frame within %s", within)
		return frame.Frame{}
	}
}

func wantNoFrame(t *testing.T, out <-chan frame.Frame, quiet time.Duration) {
	t.Helper()
	select {
	case f := <-out:
		t.Fatalf("frame %+v emitted, want none", f)
	case <-time.After(quiet):
	}
}

func decodePayload(t *testing.T, f frame.Frame) frame.HostTelemetryPayload {
	t.Helper()
	var payload frame.HostTelemetryPayload
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		t.Fatalf("Unmarshal(frame payload) error = %v", err)
	}
	return payload
}

// ---------------------------------------------------------------------------
// Scheduling.
// ---------------------------------------------------------------------------

func TestRunner_FirstCollectionIsImmediate(t *testing.T) {
	collector := newFakeCollector()
	start := time.Now()

	_, out := startRunner(t, collector, time.Hour)

	f := recvFrame(t, out, 2*time.Second)
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Errorf("first frame took %s with a 1h interval, want an immediate first tick", elapsed)
	}
	if f.Type != frame.TypeTelemetryHost {
		t.Errorf("frame.Type = %q, want %q", f.Type, frame.TypeTelemetryHost)
	}
	if got := decodePayload(t, f).SampleID; got != okResult().Payload.SampleID {
		t.Errorf("frame payload sample_id = %q, want the collector's result", got)
	}
}

// TestRunner_EmittedFrameCarriesCollectionTimestamp pins frame.TS to the clock
// read *before* Collect runs, not to send time. The backend's collected_at
// window check (services/agent_telemetry.py) and the whole spool catch-up story
// depend on this: a frame that sits in the spool for an hour must still report
// when it was sampled.
func TestRunner_EmittedFrameCarriesCollectionTimestamp(t *testing.T) {
	const work = 300 * time.Millisecond
	collector := newFakeCollector()
	collector.delay = work
	before := time.Now().UTC()

	_, out := startRunner(t, collector, time.Hour)

	f := recvFrame(t, out, 5*time.Second)
	received := time.Now().UTC()
	var enteredAt time.Time
	select {
	case enteredAt = <-collector.entered:
	default:
		t.Fatal("the collector recorded no entry time")
	}
	if f.TS.Before(before) {
		t.Errorf("frame.TS = %s, want it at or after the runner start %s", f.TS, before)
	}
	if f.TS.After(enteredAt) {
		t.Errorf("frame.TS = %s, want it at or before Collect entry %s (captured before the collection)", f.TS, enteredAt)
	}
	// Send time is at least `work` later than collection time, so a TS stamped
	// at send would land outside this bound.
	if gap := received.Sub(f.TS); gap < work {
		t.Errorf("send time - frame.TS = %s, want >= %s; frame.TS looks like send time, not collection time", gap, work)
	}
	if f.TS.Location() != time.UTC {
		t.Errorf("frame.TS location = %v, want UTC", f.TS.Location())
	}
}

func TestRunner_ResetWithNewIntervalStopsPriorGoroutine(t *testing.T) {
	collector := newFakeCollector()
	runner, out := startRunner(t, collector, 25*time.Millisecond)

	// Let the fast cadence prove itself.
	recvFrame(t, out, 2*time.Second)
	recvFrame(t, out, 2*time.Second)

	runner.Reset(context.Background(), time.Hour)
	// Drain whatever the fast goroutine had already queued plus the new
	// goroutine's immediate first tick.
	deadline := time.After(500 * time.Millisecond)
drain:
	for {
		select {
		case <-out:
		case <-deadline:
			break drain
		}
	}

	// If the 25ms goroutine had survived the Reset it would emit ~20 more
	// frames in the window below.
	wantNoFrame(t, out, 500*time.Millisecond)
}

func TestRunner_DoesNotOverlapCollections(t *testing.T) {
	collector := newFakeCollector()
	collector.delay = 120 * time.Millisecond // far slower than the cadence

	runner, out := startRunner(t, collector, 10*time.Millisecond)

	// Three collections' worth of wall clock at the collector's real pace.
	for i := 0; i < 3; i++ {
		recvFrame(t, out, 5*time.Second)
	}
	runner.Stop()

	if peak := collector.maxActive.Load(); peak != 1 {
		t.Errorf("peak concurrent collections = %d, want 1 (a slow collector skips ticks, it does not queue them)", peak)
	}
}

func TestRunner_StopCancelsInFlightCollect(t *testing.T) {
	collector := newFakeCollector()
	collector.delay = time.Hour // blocks until its context is done

	runner, out := startRunner(t, collector, time.Hour)

	select {
	case <-collector.entered:
	case <-time.After(2 * time.Second):
		t.Fatal("Collect was never entered")
	}
	runner.Stop()

	select {
	case err := <-collector.returned:
		if err == nil {
			t.Errorf("in-flight Collect returned err = nil, want the canceled context error")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Stop() did not cancel the in-flight Collect")
	}
	wantNoFrame(t, out, 200*time.Millisecond)
}

// TestRunner_StopAbandonsAFrameBlockedOnAFullChannel covers run()'s last
// uncovered statement: the ctx.Done arm of the *send* select. Every other test
// hands the runner a buffered channel, so the send always completes and that
// arm is never taken — but in production `out` is the link's frame channel and
// a stalled link backs it up, which is exactly when a Stop must still return
// rather than park forever holding a collection.
//
// The unbuffered channel with no reader is what forces the block. Readiness is
// reported immediately before the send, so receiving it proves the goroutine
// has reached the send and is parked there; wantNoFrame afterwards is the
// discriminator — its receive is a reader, so a runner still parked on the send
// would hand it the frame. Silence means the send was abandoned.
func TestRunner_StopAbandonsAFrameBlockedOnAFullChannel(t *testing.T) {
	collector := newFakeCollector()
	out := make(chan frame.Frame) // unbuffered and unread: the send blocks
	reported := make(chan []frame.Readiness, 4)
	runner := NewRunner(collector, out)
	runner.OnReadiness = func(r []frame.Readiness) { reported <- r }
	t.Cleanup(runner.Stop)
	runner.Reset(context.Background(), time.Hour)

	recvReadiness(t, reported, 2*time.Second)
	runner.Stop()

	wantNoFrame(t, out, 500*time.Millisecond)
}

func TestRunner_NilOnReadinessDoesNotPanic(t *testing.T) {
	collector := newFakeCollector()
	out := make(chan frame.Frame, 4)
	runner := NewRunner(collector, out)
	t.Cleanup(runner.Stop)
	if runner.OnReadiness != nil {
		t.Fatal("NewRunner() set OnReadiness, want nil by default")
	}

	runner.Reset(context.Background(), time.Hour)

	recvFrame(t, out, 2*time.Second)
}

// ---------------------------------------------------------------------------
// Readiness pass-through and the payload-truncation signal.
// ---------------------------------------------------------------------------

func TestRunner_TruncationAppendsDegradedPayloadReadiness(t *testing.T) {
	result := okResult()
	// 200 filesystem entries: EncodeBounded truncates to 128 and degrades.
	result.Payload.Filesystems = make([]map[string]any, 200)
	for i := range result.Payload.Filesystems {
		result.Payload.Filesystems[i] = map[string]any{"mountpoint": "/mnt/x", "device": "/dev/sd", "total_bytes": uint64(i)}
	}
	collector := newFakeCollector()
	collector.result = result

	out := make(chan frame.Frame, 4)
	runner := NewRunner(collector, out)
	t.Cleanup(runner.Stop)
	reported := make(chan []frame.Readiness, 4)
	runner.OnReadiness = func(r []frame.Readiness) { reported <- r }

	runner.Reset(context.Background(), time.Hour)

	f := recvFrame(t, out, 2*time.Second)
	var got []frame.Readiness
	select {
	case got = <-reported:
	case <-time.After(2 * time.Second):
		t.Fatal("OnReadiness was never called")
	}
	var payloadEntry *frame.Readiness
	for i := range got {
		if got[i].Collector == "host.payload" {
			payloadEntry = &got[i]
		}
	}
	if payloadEntry == nil {
		t.Fatalf("readiness = %+v, want a host.payload entry after truncation", got)
	}
	if payloadEntry.State != "degraded" {
		t.Errorf("readiness[host.payload].State = %q, want %q", payloadEntry.State, "degraded")
	}
	if payloadEntry.Reason == "" {
		t.Error("readiness[host.payload].Reason is empty, want the truncation explanation")
	}
	if got[0].Collector != "host.core" {
		t.Errorf("readiness[0].Collector = %q, want the collector's own entries to come first", got[0].Collector)
	}
	if payload := decodePayload(t, f); payload.Status != "degraded" || len(payload.Filesystems) != 128 {
		t.Errorf("frame payload status = %q with %d filesystems, want degraded with 128", payload.Status, len(payload.Filesystems))
	}
}

func TestRunner_HealthyPayloadReportsReadinessUnchanged(t *testing.T) {
	collector := newFakeCollector()
	out := make(chan frame.Frame, 4)
	runner := NewRunner(collector, out)
	t.Cleanup(runner.Stop)
	reported := make(chan []frame.Readiness, 4)
	runner.OnReadiness = func(r []frame.Readiness) { reported <- r }

	runner.Reset(context.Background(), time.Hour)

	recvFrame(t, out, 2*time.Second)
	select {
	case got := <-reported:
		if len(got) != 1 || got[0].Collector != "host.core" || got[0].State != "ready" {
			t.Errorf("readiness = %+v, want exactly the collector's own entries with no host.payload row", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("OnReadiness was never called")
	}
}

// ---------------------------------------------------------------------------
// Failure paths.
//
// A failed Collect or a failed EncodeBounded still has to report readiness:
// that is the only channel by which a host whose /proc went unreadable stops
// showing "Live" in the UI. The frame channel stays silent on both paths.
// ---------------------------------------------------------------------------

// TestRunner_SchemaZeroEncodeFailureEmitsNoFrame covers payload.go's schema
// guard on the frame channel; the readiness half is asserted below.
func TestRunner_SchemaZeroEncodeFailureEmitsNoFrame(t *testing.T) {
	result := okResult()
	result.Payload.Schema = 0
	collector := newFakeCollector()
	collector.result = result

	_, out := startRunner(t, collector, 50*time.Millisecond)

	wantNoFrame(t, out, 500*time.Millisecond)
	if collector.calls.Load() < 2 {
		t.Errorf("Collect calls = %d, want the runner to keep ticking after an encode failure", collector.calls.Load())
	}
}

// TestRunner_EmitsReadinessWhenCollectFails is the collector half of the
// stale-"Live" defect: a collector that fails still knows which of its probes
// broke, and the runner must forward that even though there is no payload to
// send.
func TestRunner_EmitsReadinessWhenCollectFails(t *testing.T) {
	collector := newFakeCollector()
	collector.result = Result{Readiness: []frame.Readiness{{Collector: "host.core", State: "unavailable", Reason: "open /proc/stat: no such file or directory"}}}
	collector.err = errors.New("boom")

	_, out, reported := startRunnerWithReadiness(t, collector, 50*time.Millisecond)

	got := recvReadiness(t, reported, 2*time.Second)
	if len(got) != 1 || got[0].Collector != "host.core" || got[0].State != "unavailable" {
		t.Errorf("readiness = %+v, want the collector's own host.core/unavailable entry", got)
	}
	if got[0].Reason == "" {
		t.Error("readiness[host.core].Reason is empty, want the collector's reason preserved")
	}
	wantNoFrame(t, out, 300*time.Millisecond)
}

// TestRunner_EmptyReadinessOnAFailedCollectIsNotReported pins the other half of
// the Collector contract: an empty Readiness alongside an error means "no
// information" and must not overwrite server-side rows.
func TestRunner_EmptyReadinessOnAFailedCollectIsNotReported(t *testing.T) {
	collector := newFakeCollector()
	collector.result = Result{}
	collector.err = errors.New("boom")

	_, out, reported := startRunnerWithReadiness(t, collector, 50*time.Millisecond)

	wantNoReadiness(t, reported, 500*time.Millisecond)
	wantNoFrame(t, out, 100*time.Millisecond)
	if collector.calls.Load() < 2 {
		t.Errorf("Collect calls = %d, want the runner to keep ticking after a failed collection", collector.calls.Load())
	}
}

// TestRunner_EmitsReadinessWhenEncodeFails covers the second broken guard: a
// payload that cannot be encoded (schema mismatch here, core telemetry over the
// 256 KiB limit in production) is a host.payload outage, not silence.
func TestRunner_EmitsReadinessWhenEncodeFails(t *testing.T) {
	result := okResult()
	result.Payload.Schema = 0
	collector := newFakeCollector()
	collector.result = result

	_, out, reported := startRunnerWithReadiness(t, collector, 50*time.Millisecond)

	got := recvReadiness(t, reported, 2*time.Second)
	if len(got) != 2 || got[0].Collector != "host.core" {
		t.Fatalf("readiness = %+v, want the collector's entries followed by a host.payload entry", got)
	}
	payloadEntry := got[1]
	if payloadEntry.Collector != "host.payload" || payloadEntry.State != "unavailable" {
		t.Errorf("readiness[1] = %+v, want host.payload/unavailable", payloadEntry)
	}
	if !strings.Contains(payloadEntry.Reason, "unsupported host telemetry schema") {
		t.Errorf("readiness[host.payload].Reason = %q, want the encoder's error", payloadEntry.Reason)
	}
	wantNoFrame(t, out, 300*time.Millisecond)
}

// TestRunner_ContextCancellationEmitsNoReadiness guards the fix against the
// opposite failure: a shutdown is not an outage. Even a collector that hands
// back readiness on cancellation must not have it reported.
func TestRunner_ContextCancellationEmitsNoReadiness(t *testing.T) {
	collector := newFakeCollector()
	collector.fn = func(ctx context.Context, _ int) (Result, error) {
		<-ctx.Done()
		return Result{Readiness: []frame.Readiness{{Collector: "host.core", State: "unavailable", Reason: "should never be reported"}}}, ctx.Err()
	}

	runner, out, reported := startRunnerWithReadiness(t, collector, time.Hour)

	select {
	case <-collector.entered:
	case <-time.After(2 * time.Second):
		t.Fatal("Collect was never entered")
	}
	runner.Stop()

	wantNoReadiness(t, reported, 500*time.Millisecond)
	wantNoFrame(t, out, 100*time.Millisecond)
}
