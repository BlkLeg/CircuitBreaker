// apps/agent/internal/link/outbound.go
package link

import (
	"fmt"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// The in-flight window: how much may be on the wire, unacknowledged, at once.
//
// The paced drain budget is drainFramesPerTick frames per drainTickInterval —
// 4 per 100ms, i.e. 40 frames/s — so 64 frames covers ~1.6s of round trip
// before ack latency, rather than the budget, becomes the throughput limit.
// That preserves the catch-up timings docs/agent.md promises (a one-hour
// outage in ~3s, 24 hours in ~72s, a completely full 64 MiB spool in under
// three minutes) for any RTT under ~1.6s, which is every homelab and most
// things worse than one.
//
// It bounds the other direction too: a connection that dies with a full
// window re-sends at most 64 frames the server may already hold, and the
// backend dedupes those on (agent_id, sample_id, collected_at).
//
// 4 MiB is the same bound expressed in bytes, so 64 unusually fat frames
// cannot put an unbounded amount of memory (or socket buffer) in flight.
//
// Both are thresholds rather than hard ceilings: spool.PeekAt always
// returns its first frame regardless of the byte budget, so that one frame
// larger than a whole tick's budget cannot wedge the queue forever. The
// window can therefore overshoot maxInflightBytes by at most one frame, which
// is the deliberate trade — a bounded overshoot beats a backlog that can
// never drain.
const (
	maxInflightFrames       = 64
	maxInflightBytes  int64 = 4 << 20
)

// ackStallTimeout is how long the agent will keep frames in flight with no
// acknowledgement advancing the watermark before it gives up on the
// connection.
//
// 45s sits deliberately below the 60s readTimeout: a server that is reading
// the socket — so the read deadline keeps being refreshed by its pings — but
// is not acknowledging anything is a different fault from a silent peer, and
// diagnosing it as itself rather than as silence is the whole point of a
// distinct error. Reaching it ends the connection with nothing committed, so
// every frame in flight is still at the spool head for the next one.
//
// A var, not a const, so tests can shrink it; production never changes it.
var ackStallTimeout = 45 * time.Second

// inflightFrame is one data frame written to the socket and not yet
// acknowledged: the sequence number this connection assigned it, the encoded
// size it occupies in the window, and where it sits in the spool.
type inflightFrame struct {
	seq   uint64
	bytes int64
	// pos is the frame's *absolute* position in the spool's stream, not its
	// index in the live backlog. The two differ the moment the drop-oldest
	// cap policy runs, and under commit-on-ack the frames at the head of the
	// backlog are exactly these — so an eviction between a send and its
	// acknowledgement shifts every live index underneath this window. A
	// positional commit then discarded that many never-sent frames on top of
	// the ones eviction had already destroyed. See spool.Spool's `origin`.
	pos int64
}

// dataFrameSender owns this connection's outbound flow for *data* frames
// only (spec §4.4; internal/spool's package doc: control frames must never
// be enqueued).
//
// Its contract is peek -> send -> await ack -> commit. A data frame is
// fsync'd to the spool by Run's enqueue goroutine *before* it can reach a
// socket, drainBurst hands a bounded window of the backlog to the wire
// without consuming it, and only onDataAck — driven by a `data.ack` frame
// the server sends once it has terminally handled those sequence numbers —
// discards them.
//
// That ordering is the entire fix. The previous implementation advanced the
// spool head the instant conn.WriteMessage returned nil and called those
// frames delivered, but a successful write only means the local kernel
// accepted the bytes: a server restarting mid-drain, or the up-to-60s window
// before a black-holed socket is noticed, destroyed everything written into
// it. The documented guarantee was at-least-once; the real one was
// at-least-once onto a socket, which is not a guarantee about data at all.
//
// Two paths remain that do not wait for an ack, both deliberate:
//
//   - Negotiation failure. A server that does not answer hello with
//     `data_ack` cannot ack anything, so drainBurst falls back to
//     commit-on-write — today's behaviour, degraded but functional, and the
//     agent says so in its log once per connection.
//   - sendLive, which exists only for the degenerate `Spool == nil` case
//     (Uninstall's one-shot connection, and tests that build link.Options
//     without a spool). It carries no durability guarantee whatsoever; the
//     daemon always configures a spool.
//
// Heartbeat and control frames never go through this type at all — link.go's
// sendHeartbeat/sendRekey write directly to the connection. sendLive's
// panic-on-non-data-frame guard exists as a defense against this package's
// own wiring regressing, not because a heartbeat is expected to reach it in
// normal operation.
type dataFrameSender struct {
	spool *spool.Spool // nil disables spooling entirely (e.g. Uninstall's one-shot connection)
	// send encodes, encrypts and writes one frame over the live connection,
	// returning the sequence number it assigned and the encoded size it put
	// on the wire — the two things the in-flight window is tracked in.
	send         func(frame.Frame) (uint64, int64, error)
	onSpoolStats func(depth int, bytes int64)

	// ackData reports whether this connection negotiated `data.ack`. False
	// until hello.ack settles it, which is safe because draining is already
	// gated on an accepted session, so no frame goes out before the mode is
	// known.
	ackData bool
	// inflight is every frame written and not yet acknowledged, in send
	// order. Sequence numbers increase monotonically within a connection and
	// frames go out in spool order, so an ack watermark always releases a
	// leading prefix of this slice and never a hole in the middle.
	inflight      []inflightFrame
	inflightBytes int64
	// unackedSince starts the current unacknowledged stretch: the moment this
	// connection last had frames in flight with no acknowledgement having
	// released any of them since. Zero when there is no such stretch.
	//
	// It measures the *stretch*, deliberately, and not any particular frame's
	// wait. Only two things touch it: it starts when the window goes from
	// empty to in-flight with no stretch already running, and it restarts
	// when an ack actually releases something, which is the only progress
	// there is. Cap eviction is not progress and moves it not at all — the
	// frames it destroys were never delivered either, and a deadline that
	// eviction can push forward is a deadline that stops existing at the cap,
	// where every producer enqueue evicts from the head. Two commits got this
	// wrong in two different ways: one restarted the clock on eviction, and
	// one measured from the oldest *surviving* frame's send time, which a
	// producer above roughly 1.5 frames/s evades simply by replacing the
	// whole window inside the deadline.
	unackedSince time.Time
}

// newDataFrameSender constructs a dataFrameSender. onSpoolStats may be nil.
func newDataFrameSender(
	sp *spool.Spool,
	send func(frame.Frame) (uint64, int64, error),
	onSpoolStats func(depth int, bytes int64),
) *dataFrameSender {
	if onSpoolStats == nil {
		onSpoolStats = func(int, int64) {}
	}
	return &dataFrameSender{spool: sp, send: send, onSpoolStats: onSpoolStats}
}

// negotiateAck records what this connection's hello.ack settled: whether the
// server will send `data.ack` frames. Called exactly once per connection,
// from the first accepted hello.ack, before any drain tick can fire (the
// drain arm is gated on that same acceptance).
func (d *dataFrameSender) negotiateAck(enabled bool) {
	d.ackData = enabled
}

// assertDataFrame panics if f is not a data frame per frame.IsDataFrame. This
// guards a programming invariant, not a runtime condition: the only callers
// that reach the spool's write path are Run's enqueue goroutine and sendLive,
// both of which should only ever carry what a data-frame producer hands them.
// A heartbeat or control frame arriving here would mean this package's own
// wiring is broken — mirroring noiseconn.Session.Encrypt's precedent of
// panicking on an invariant violation rather than silently proceeding.
func assertDataFrame(f frame.Frame) {
	if !frame.IsDataFrame(f.Type) {
		panic(fmt.Sprintf(
			"link: refusing to spool-wire non-data frame type %q — heartbeat/control frames must never reach the spool",
			f.Type))
	}
}

// stampObserved fixes a data frame's observation timestamp if the producer
// left it zero.
//
// It runs at enqueue, not at send: the instant an observation was taken is a
// fact about the host, and letting it be decided by when the network happened
// to be available would date a sample from an hour-old backlog to the moment
// the link came back. Exported to Run's enqueue goroutine and to sendLive,
// the only two places a frame enters this package's outbound path.
func stampObserved(f frame.Frame) frame.Frame {
	if f.TS.IsZero() {
		f.TS = time.Now().UTC()
	}
	return f
}

// sendLive sends one live data frame, with no durability guarantee at all:
// it is committed the moment the socket accepts it, and a socket that accepts
// bytes the server never reads loses them.
//
// It survives only for the degenerate `Spool == nil` case — Uninstall's
// one-shot connection, and this package's tests that build link.Options
// without a spool. The daemon always configures a spool, and Run routes every
// data frame through it (fsync first, ack later) rather than here.
//
// With a spool configured it keeps its original fallback behaviour — enqueue
// on send failure — so a caller that drives runOnce directly still cannot
// lose a frame to a returned error.
func (d *dataFrameSender) sendLive(f frame.Frame) error {
	assertDataFrame(f)
	f = stampObserved(f)

	if _, _, sendErr := d.send(f); sendErr != nil {
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

// hasBacklog reports whether there is anything to catch up on, or anything in
// flight still waiting to be acknowledged.
//
// The second clause is tested explicitly rather than inferred from the first.
// An unacknowledged frame is normally still in the spool, so Len() > 0 usually
// covers it — but cap eviction can destroy an in-flight frame, and then the
// window is non-empty while the backlog is not. Leaning on the usual case
// would skip the tick that prunes those entries and the ack-stall check with
// it, which is how a window closed by frames that no longer exist would stay
// closed. Nil-safe: a nil spool is the normal case for several callers
// (Uninstall's one-shot connection, and this package's non-spool tests), and
// runOnce's drain ticker fires against all of them.
func (d *dataFrameSender) hasBacklog() bool {
	if d.spool == nil {
		return false
	}
	return len(d.inflight) > 0 || d.spool.Len() > 0
}

// drainBurst advances this connection's catch-up by one tick.
//
// With `data.ack` negotiated it sends up to maxFrames frames (and at most
// maxBytes of them) starting at the first *absolute position* it has not sent
// yet, and commits nothing. Commits happen in onDataAck.
//
// A position, not "len(inflight) frames past the head": the head moves when
// the cap evicts, so a head-relative skip would step over frames that were
// never sent at all. See spool.Spool's `origin`. The window is additionally capped at
// maxInflightFrames/maxInflightBytes, so a server that stops acking stops the
// flow rather than letting it run away.
//
// Without `data.ack` — an older server — it falls back to the previous
// commit-on-write behaviour: send, then commit exactly the ones the socket
// accepted. Degraded and honest: the agent has already logged that this
// connection cannot promise more.
//
// A send error ends the connection either way. Under commit-on-ack nothing
// has been committed at all, so every frame written on this connection is
// still at the spool head, in order, for the next one.
func (d *dataFrameSender) drainBurst(maxFrames int, maxBytes int64) error {
	if d.spool == nil {
		return nil
	}
	if !d.ackData {
		return d.drainCommitOnWrite(maxFrames, maxBytes)
	}

	// Before anything else: the cap may have destroyed frames this window is
	// still waiting on, and an entry for a frame that no longer exists can
	// never be acknowledged. Left in place it would hold the window closed
	// and run the stall clock down against nothing.
	d.dropEvicted(d.spool.Origin())

	if err := d.ackStallError(); err != nil {
		return err
	}

	budgetFrames := min(maxFrames, maxInflightFrames-len(d.inflight))
	budgetBytes := min(maxBytes, maxInflightBytes-d.inflightBytes)
	if budgetFrames <= 0 || budgetBytes <= 0 {
		// The window is full: the server has frames it has not acknowledged
		// yet. Waiting is correct — the alternative is sending more of what
		// may already be lost.
		return nil
	}

	// Asked for by position, not by "skip the ones I already sent": eviction
	// can have moved the head past some of them, and a head-relative skip
	// would then step over frames that were never sent at all.
	res := d.spool.PeekAt(d.nextSendPos(), budgetFrames, budgetBytes)
	if len(res.Frames) == 0 {
		return nil
	}
	for i, f := range res.Frames {
		seq, size, err := d.send(f)
		if err != nil {
			return err
		}
		d.inflight = append(d.inflight, inflightFrame{seq: seq, bytes: size, pos: res.Start + int64(i)})
		d.inflightBytes += size
		// Starts a stretch only when there is not one already running. A
		// stretch the cap emptied by destroying every frame in it has not
		// ended — nothing was acknowledged — so refilling the window
		// continues it rather than starting over.
		if d.unackedSince.IsZero() {
			d.unackedSince = time.Now()
		}
	}
	// One report per burst, not per frame: the depth a caller cares about is
	// the one at the end of the tick. Nothing was committed, so the depth has
	// not moved — but the callback is the daemon's only spool-state signal
	// and staying silent through an active drain would read as a stall.
	d.reportStats()
	return nil
}

// drainCommitOnWrite is the pre-acknowledgement drain, kept for connections
// to a server that does not support `data.ack`.
//
// It sends up to maxFrames spooled frames (at most maxBytes of encoded
// payload) from the head of the backlog, oldest first, and commits exactly
// the ones the socket accepted. On the first send error it commits the
// successes and returns that error, which ends the connection; the
// uncommitted remainder stays at the *head* of the spool in its original
// order.
//
// What it cannot do — and the reason the acknowledged path exists — is tell a
// frame the server stored from one written into a socket the server never
// read. Both make WriteMessage return nil.
func (d *dataFrameSender) drainCommitOnWrite(maxFrames int, maxBytes int64) error {
	res := d.spool.PeekAt(spool.FromHead, maxFrames, maxBytes)
	if len(res.Frames) == 0 {
		return nil
	}

	var sendErr error
	sent := 0
	for _, f := range res.Frames {
		if _, _, err := d.send(f); err != nil {
			sendErr = err
			break
		}
		sent++
	}

	if sent > 0 {
		// By position here too, even though this path commits within
		// microseconds of the peek. The window is narrow, not closed: the
		// producer enqueues from another goroutine and can evict inside it,
		// and a count would then discard never-sent frames exactly as it did
		// on the acknowledged path. A narrow silent loss is still a silent
		// loss.
		if err := d.spool.CommitThrough(res.Start + int64(sent) - 1); err != nil {
			if sendErr != nil {
				return fmt.Errorf("link: spooled resend failed (%w) and commit also failed: %v", sendErr, err)
			}
			return fmt.Errorf("link: spool commit: %w", err)
		}
	}
	d.reportStats()
	return sendErr
}

// onDataAck applies one server `data.ack` watermark: every frame this
// connection sent with seq <= watermark has been terminally handled —
// ingested, deduped, or deliberately refused and audited — and may now be
// discarded from the spool.
//
// It pops the *leading* run of in-flight entries at or below the watermark
// and commits exactly that many. A leading prefix is the right shape and not
// merely a convenient one: sequence numbers increase monotonically within a
// connection and frames leave the spool in order, so "everything up to N" and
// "the first k frames of the backlog" are the same set.
//
// A watermark that releases nothing (a coalesced ack the agent has already
// acted on, or one covering only heartbeat traffic) is a no-op rather than an
// error, and deliberately does *not* reset the stall clock: an ack that frees
// no data frame is not evidence that data frames are being handled.
func (d *dataFrameSender) onDataAck(watermark uint64) error {
	if d.spool == nil || !d.ackData {
		return nil
	}
	released := 0
	var releasedBytes int64
	through := int64(-1)
	for _, f := range d.inflight {
		if f.seq > watermark {
			break
		}
		released++
		releasedBytes += f.bytes
		through = f.pos
	}
	if released == 0 {
		return nil
	}
	d.inflight = append(d.inflight[:0], d.inflight[released:]...)
	d.inflightBytes -= releasedBytes
	// Real progress, and the only thing that is. The stretch restarts for
	// whatever is still outstanding, and ends outright when this released the
	// last of it — an idle link is not a stalled one.
	if len(d.inflight) == 0 {
		d.unackedSince = time.Time{}
	} else {
		d.unackedSince = time.Now()
	}

	// By position, never by count. If the cap destroyed some of these while
	// they were in flight, a count would discard that many *unsent* frames
	// from behind them — a silent loss on top of one the eviction record at
	// least reports. CommitThrough discards exactly the acknowledged frames
	// that are still there and nothing else.
	if err := d.spool.CommitThrough(through); err != nil {
		return fmt.Errorf("link: committing %d acknowledged frame(s): %w", released, err)
	}
	d.reportStats()
	return nil
}

// nextSendPos is the absolute spool position the next drain tick should start
// from: one past the newest frame in flight, or the head of the backlog when
// nothing is.
func (d *dataFrameSender) nextSendPos() int64 {
	if n := len(d.inflight); n > 0 {
		return d.inflight[n-1].pos + 1
	}
	return spool.FromHead
}

// dropEvicted forgets in-flight entries whose frames the spool's cap policy
// has already destroyed — everything positioned below the live backlog's
// current head.
//
// Those frames are gone and will never be acknowledged, so their entries can
// only do harm: they occupy the in-flight window, and they keep the ack-stall
// clock running against observations that no longer exist. The loss itself is
// already counted and logged by the eviction that caused it (see
// spool.EvictionStats), so nothing is reported here — this is bookkeeping,
// not a second loss.
//
// Evicted entries are always a leading prefix: entries are appended in
// increasing position order and eviction only ever removes from the head.
func (d *dataFrameSender) dropEvicted(origin int64) {
	dropped := 0
	var droppedBytes int64
	for _, f := range d.inflight {
		if f.pos >= origin {
			break
		}
		dropped++
		droppedBytes += f.bytes
	}
	if dropped == 0 {
		return
	}
	d.inflight = append(d.inflight[:0], d.inflight[dropped:]...)
	d.inflightBytes -= droppedBytes
	// Deliberately touches d.unackedSince not at all, including when it
	// empties the window: destroying an unacknowledged frame is not the
	// server acknowledging it, so the stretch continues into whatever the
	// next drain sends. Anything else — restarting the clock here, or
	// deriving it from the surviving entries — hands a never-acking server an
	// indefinite reprieve at the cap, which is the one state the detector
	// exists for.
	//
	// The window cannot stay empty here: eviction only happens at the cap, so
	// there is a backlog behind these frames and the same tick refills from
	// it.
}

// ackStallError reports the connection dead when the current unacknowledged
// stretch has run for ackStallTimeout.
//
// It asks unackedSince and nothing else. An idle link is still never faulted,
// because a stretch only exists while frames are outstanding and only an
// acknowledgement ends one — but "are there frames outstanding *right now*"
// is not the question, and asking it was the fourth version of one bug.
// drainBurst prunes frames the cap destroyed before this runs and refills
// after, so a producer evicting at least drainFramesPerTick frames between
// ticks left the window empty at every single check. An emptiness guard here
// returned nil each time while the clock behind it sat correct, unread, and
// arbitrarily stale.
func (d *dataFrameSender) ackStallError() error {
	if d.unackedSince.IsZero() {
		return nil
	}
	if time.Since(d.unackedSince) < ackStallTimeout {
		return nil
	}
	if len(d.inflight) == 0 {
		// Reported separately because it is a different and worse fact than
		// frames waiting: the server acknowledged nothing for the whole
		// stretch, and the cap has already destroyed everything it was
		// waiting on.
		return fmt.Errorf("%w (nothing acknowledged for %s; the spool's cap destroyed every frame "+
			"that was waiting)", errAckStall, ackStallTimeout)
	}
	return fmt.Errorf("%w (%d frame(s) unacknowledged for %s)",
		errAckStall, len(d.inflight), ackStallTimeout)
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
