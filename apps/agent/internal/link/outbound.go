// apps/agent/internal/link/outbound.go
package link

import (
	"fmt"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// dataFrameSender owns this connection's outbound flow for *data* frames
// only (spec §4.4; internal/spool's package doc: control frames must never
// be enqueued). It does two independent things:
//
//   - sendLive sends one live data frame — host telemetry today, probe and
//     discovery results later — and durably enqueues it to the spool if the
//     send fails, so the frame survives whatever reconnect that error
//     triggers instead of being lost.
//   - drainBurst flushes a bounded slice of the accumulated backlog. It is
//     driven by runOnce's drainTicker, *not* by live traffic: catch-up used
//     to be a side effect of successful live sends (one spooled frame per
//     four live ones), which meant a disabled or failing collector never
//     drained at all and an hour-long outage took hours to clear even when
//     it did. Pacing it on a timer instead makes catch-up bounded and
//     independent of what any producer happens to be doing.
//
// Delivery is at-least-once by construction: frames are peeked, sent, and
// only then committed, so a connection that dies mid-burst re-sends rather
// than loses. The backend dedupes on (agent_id, sample_id, collected_at).
//
// Heartbeat and control frames never go through this type at all — link.go's
// sendHeartbeat/sendRekey write directly to the connection, bypassing
// dataFrameSender entirely. sendLive's panic-on-non-data-frame guard exists
// as a defense against this package's own wiring regressing, not because a
// heartbeat is expected to reach it in normal operation.
type dataFrameSender struct {
	spool        *spool.Spool            // nil disables spooling entirely (e.g. Uninstall's one-shot connection)
	send         func(frame.Frame) error // encode + encrypt + write one frame over the live connection
	onSpoolStats func(depth int, bytes int64)
}

// newDataFrameSender constructs a dataFrameSender. onSpoolStats may be nil.
func newDataFrameSender(sp *spool.Spool, send func(frame.Frame) error, onSpoolStats func(depth int, bytes int64)) *dataFrameSender {
	if onSpoolStats == nil {
		onSpoolStats = func(int, int64) {}
	}
	return &dataFrameSender{spool: sp, send: send, onSpoolStats: onSpoolStats}
}

// assertDataFrame panics if f is not a data frame per frame.IsDataFrame. This
// guards a programming invariant, not a runtime condition: the only caller
// that feeds sendLive is link.go's DataFrames select case, which should only
// ever carry what a data-frame producer hands it. A heartbeat or control
// frame arriving here would mean this package's own wiring is broken —
// mirroring noiseconn.Session.Encrypt's precedent of panicking on an
// invariant violation rather than silently proceeding.
func assertDataFrame(f frame.Frame) {
	if !frame.IsDataFrame(f.Type) {
		panic(fmt.Sprintf(
			"link: refusing to spool-wire non-data frame type %q — heartbeat/control frames must never reach the spool",
			f.Type))
	}
}

// sendLive sends one live data frame. On failure — with a spool configured —
// it durably enqueues f before returning the original send error. On success
// it does nothing else: draining the backlog is drainBurst's job, on its own
// schedule.
func (d *dataFrameSender) sendLive(f frame.Frame) error {
	assertDataFrame(f)

	if sendErr := d.send(f); sendErr != nil {
		if d.spool == nil {
			return sendErr
		}
		if err := d.spool.Enqueue(f); err != nil {
			return fmt.Errorf("link: live send failed (%w) and spool enqueue also failed: %v", sendErr, err)
		}
		d.reportStats()
		return sendErr
	}
	return nil
}

// hasBacklog reports whether there is anything to catch up on. Nil-safe: a
// nil spool is the normal case for most callers (Uninstall's one-shot
// connection, and every link.Options in this package's tests bar the
// catch-up ones), and runOnce's drain ticker fires against all of them.
func (d *dataFrameSender) hasBacklog() bool {
	return d.spool != nil && d.spool.Len() > 0
}

// drainBurst sends up to maxFrames spooled frames (at most maxBytes of
// encoded payload) from the head of the backlog, oldest first, and commits
// exactly the ones that reached the wire.
//
// On the first send error it commits the successes and returns that error —
// which ends the connection, same as a failed live send. The uncommitted
// remainder stays at the *head* of the spool in its original order. That is
// the whole point of the peek/commit split: the previous implementation
// re-enqueued a failed frame at the tail, so the oldest frame became the
// newest and cap eviction dropped its neighbours before it.
func (d *dataFrameSender) drainBurst(maxFrames int, maxBytes int64) error {
	if d.spool == nil {
		return nil
	}
	batch := d.spool.Peek(maxFrames, maxBytes)
	if len(batch) == 0 {
		return nil
	}

	var sendErr error
	sent := 0
	for _, f := range batch {
		if err := d.send(f); err != nil {
			sendErr = err
			break
		}
		sent++
	}

	if sent > 0 {
		if err := d.spool.Commit(sent); err != nil {
			if sendErr != nil {
				return fmt.Errorf("link: spooled resend failed (%w) and commit also failed: %v", sendErr, err)
			}
			return fmt.Errorf("link: spool commit: %w", err)
		}
	}
	// One report per burst, not per frame: the depth a caller cares about is
	// the one at the end of the tick.
	d.reportStats()
	return sendErr
}

// reportStats forwards the spool's current depth/size to onSpoolStats. A nil
// spool reports nothing — there is nothing to report.
func (d *dataFrameSender) reportStats() {
	if d.spool == nil {
		return
	}
	depth := d.spool.Len()
	size, err := d.spool.SizeBytes()
	if err != nil {
		return
	}
	d.onSpoolStats(depth, size)
}
