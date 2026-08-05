// apps/agent/internal/link/outbound.go
package link

import (
	"fmt"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// dataFrameSender owns the interleaved live/spooled outbound flow for *data*
// frames only (spec §4.4; internal/spool's package doc: control frames must
// never be enqueued). A live send that fails durably enqueues the frame to
// the spool instead of losing it, and every spool.DrainInterleaveRatio-th
// successful live send also drains and resends one spooled frame, so a
// backlog built up during an outage gets flushed back out once the link
// recovers rather than sitting forever behind new live traffic.
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
	liveCount    uint64
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
// ever carry what a Slice 2+ data-frame producer hands it. A heartbeat or
// control frame arriving here would mean this package's own wiring is
// broken — mirroring noiseconn.Session.Encrypt's precedent of panicking on
// an invariant violation rather than silently proceeding.
func assertDataFrame(f frame.Frame) {
	if !frame.IsDataFrame(f.Type) {
		panic(fmt.Sprintf(
			"link: refusing to spool-wire non-data frame type %q — heartbeat/control frames must never reach the spool",
			f.Type))
	}
}

// sendLive sends one live data frame. On failure — with a spool configured —
// it durably enqueues f before returning the original send error, so the
// frame survives whatever reconnect that error triggers instead of being
// lost. On success, it counts toward the drain-interleave ratio and may
// trigger one drainOne.
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

	d.liveCount++
	if d.spool != nil && d.liveCount%spool.DrainInterleaveRatio == 0 {
		return d.drainOne()
	}
	return nil
}

// drainOne pulls the oldest spooled frame, if any, and resends it live. A
// resend failure re-enqueues the frame — via Enqueue, not by leaving it
// dropped — so attempting a drain against a dying connection doesn't
// silently lose the frame it pulled.
func (d *dataFrameSender) drainOne() error {
	f, ok, err := d.spool.Drain()
	if err != nil {
		return fmt.Errorf("link: spool drain: %w", err)
	}
	if !ok {
		return nil
	}
	if sendErr := d.send(f); sendErr != nil {
		if err := d.spool.Enqueue(f); err != nil {
			return fmt.Errorf("link: drained-frame resend failed (%w) and re-enqueue also failed: %v", sendErr, err)
		}
		d.reportStats()
		return sendErr
	}
	d.reportStats()
	return nil
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
