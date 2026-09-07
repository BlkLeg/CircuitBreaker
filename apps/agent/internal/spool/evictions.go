// apps/agent/internal/spool/evictions.go
package spool

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/logging"
)

// evictedFilename records, cumulatively and for the life of the state
// directory, what the drop-oldest policy has destroyed. It is a separate
// file from queue.jsonl for the same reason queue.head is: the queue is
// rewritten by compaction and truncated by delivery, and a record of
// permanently lost history must outlive both.
const evictedFilename = "queue.evicted"

// EvictionStats is the permanent record of observations this spool destroyed
// to stay inside its byte cap.
//
// The policy itself is unchanged and deliberate — when the disk buffer fills
// during a long outage, recent observations matter more than old ones, so the
// oldest go. What this type exists for is that the policy used to run
// *silently*: no counter, no log line, no event, and the only externally
// visible symptom was that the reported spool depth stopped rising. An
// operator watching the documented signal could not tell a drained backlog
// from a destroyed one.
//
// A bare count would not be enough either. The trust-relevant fact is which
// *window* of history is gone, so the two timestamps are widened from the
// dropped frames' own Frame.TS — the instant each observation describes — and
// never from wall-clock now. LastEvictedAt is the one wall-clock field, and it
// answers a different question: when the destruction last happened.
//
// Cumulative and never reset by the agent. A counter the producer can zero is
// a counter an operator cannot trust; the only thing that clears it is
// deleting the state directory, and the server treats a decrease as exactly
// that (see agent_registry.record_spool_evictions).
type EvictionStats struct {
	Frames          int64     `json:"frames"`
	Bytes           int64     `json:"bytes"`
	OldestDroppedTS time.Time `json:"oldest_dropped_ts"`
	NewestDroppedTS time.Time `json:"newest_dropped_ts"`
	LastEvictedAt   time.Time `json:"last_evicted_at"`
	// LastDestroyedReason names what destroyed data most recently. The two
	// causes fold into one counter on purpose — "this host's history has a
	// hole in it" is the same fact either way — but their remedies are
	// opposite, and without this the status output can only list both and
	// send the operator to the log. Added alongside the existing fields
	// rather than replacing any, and omitted when empty, so a record written
	// by an older agent still loads.
	LastDestroyedReason string `json:"last_destroyed_reason,omitempty"`
}

// CapEvictionReason is what the drop-oldest policy records itself as in
// EvictionStats.LastDestroyedReason. Exported because `cb-agent status` has
// to tell it apart from a refused write to print the right remedy. Phrased
// for an operator reading that output, not as an error code.
const CapEvictionReason = "the spool hit its size cap during an outage"

// widen folds one dropped frame's own timestamp into the destroyed window.
// A zero ts (a frame that carried none) is ignored rather than dragging the
// window back to year 1 — the frame is still counted, only its instant is
// unknown.
func (e *EvictionStats) widen(ts time.Time) {
	if ts.IsZero() {
		return
	}
	if e.OldestDroppedTS.IsZero() || ts.Before(e.OldestDroppedTS) {
		e.OldestDroppedTS = ts
	}
	if e.NewestDroppedTS.IsZero() || ts.After(e.NewestDroppedTS) {
		e.NewestDroppedTS = ts
	}
}

// destroyedReportInterval bounds how often RecordDestroyed writes a log line.
//
// The line only. The condition driving these losses is by nature sustained —
// a full disk stays full — so an unthrottled line per sample would be a log
// storm layered on top of a storage failure, and the first loss in a window
// always reports immediately, so an isolated failure is never silent.
//
// The record itself is written through on every call. Batching that too was a
// real defect: the argument for it was that `EvictionStats` reads the
// in-memory record, so hello, heartbeat and the status file are always
// current — which is true, and irrelevant. What it missed is the restart. A
// full disk usually ends with an operator freeing it and restarting the
// agent, and a persist batched behind a one-minute window loses up to a
// minute of losses *outright* at that point, not late. The permanent record
// then goes down, and the server reads any decrease as the state directory
// having been recreated and writes an audit event saying so — a confidently
// wrong claim about data loss, on top of real data loss, which is the exact
// failure this whole mechanism exists to end.
//
// The cost of write-through is one failing write syscall per destroyed
// observation on a disk that is already refusing writes. That is a cheap
// price for a counter that is true across a restart.
const destroyedReportInterval = time.Minute

// RecordDestroyed folds one observation this spool could not buffer at all
// into the same permanent loss record cap eviction writes to, and says so at
// error level.
//
// The cap is the dominant reason a spool destroys an observation, but it is
// not the only one: a full disk, a read-only /var, or a state directory that
// vanished all make Enqueue fail, and since every data frame is now spooled
// *before* it can reach a socket, a refused write is the end of that
// observation. Counting it here rather than inventing a second counter is
// deliberate — the operator-facing fact is identical ("this host's history
// has a hole in it, and nothing will backfill it"), the fleet view and the
// Telemetry tab already read this record, and a loss that is real but
// invisible is the exact failure this whole effort exists to end. `reason`
// separates the causes in the log, which is where an operator goes next.
//
// Callers must already know the frame is gone: this records a loss, it does
// not cause one.
func (s *Spool) RecordDestroyed(f frame.Frame, reason string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := frame.Encode(f)
	size := int64(0)
	if err == nil {
		size = int64(len(data)) + 1
	}
	s.evicted.Frames++
	s.evicted.Bytes += size
	s.evicted.widen(f.TS)
	s.evicted.LastEvictedAt = time.Now().UTC()
	s.evicted.LastDestroyedReason = reason

	s.destroyedPending.Frames++
	s.destroyedPending.Bytes += size
	s.destroyedPending.widen(f.TS)

	// Written through, never batched — see destroyedReportInterval. The error
	// is held rather than logged here so a sustained failure does not emit a
	// line per sample; it is reported with the batched loss line below, which
	// is the same line an operator is already being pointed at.
	persistErr := s.persistEvictionsLocked()

	if !s.lastDestroyedReport.IsZero() &&
		time.Since(s.lastDestroyedReport) < destroyedReportInterval {
		return
	}
	pending := s.destroyedPending
	s.destroyedPending = EvictionStats{}
	s.lastDestroyedReport = time.Now()

	// Errorf, not Warnf: cap eviction is a policy working as designed, while
	// this is the spool failing to do its job at all — and unlike eviction it
	// will keep happening, silently, for as long as the underlying condition
	// lasts.
	//
	// Both ends of the window, oldest first. Printing the triggering frame's
	// timestamp — the newest of the batch — followed by ".." told an operator
	// the hole started where it in fact ended.
	logging.Errorf(
		"cb-agent: spool: WARNING permanently lost %d observation(s) (%d bytes) covering %s..%s that "+
			"could not be buffered (%s) — there is no other copy; cumulative loss for this agent is "+
			"%d observation(s) / %d bytes.",
		pending.Frames, pending.Bytes,
		formatEvictedTS(pending.OldestDroppedTS), formatEvictedTS(pending.NewestDroppedTS),
		reason, s.evicted.Frames, s.evicted.Bytes,
	)
	if persistErr != nil {
		// A record that could not be written is a loss the next restart will
		// not be able to report at all.
		logging.Errorf("cb-agent: spool: could not persist the eviction record: %v", persistErr)
	}
}

// EvictionStats returns a snapshot of what this spool has permanently
// destroyed since its state directory was created.
func (s *Spool) EvictionStats() EvictionStats {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.evicted
}

// loadEvictions reads the persisted record. A missing file means "nothing has
// ever been evicted", which is the honest reading for a fresh state
// directory. A corrupt one is reported as an error rather than silently reset
// to zero: this file is the audit trail for destroyed data, and quietly
// starting it over is the precise failure this whole mechanism exists to
// prevent.
func (s *Spool) loadEvictions() error {
	data, err := os.ReadFile(s.evictedPath)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("spool: read %s: %w", s.evictedPath, err)
	}
	var stats EvictionStats
	if err := json.Unmarshal(data, &stats); err != nil {
		return fmt.Errorf("spool: decode %s: %w", s.evictedPath, err)
	}
	s.evicted = stats
	return nil
}

// persistEvictionsLocked writes the record atomically — temp file at 0600,
// then rename over the destination — exactly as writeHeadMarker does, so a
// concurrent reader (or a restart mid-write) sees either the previous
// complete record or the new one. A torn eviction record must never be
// readable: it would understate the loss, which is worse than no record at
// all because it looks authoritative.
func (s *Spool) persistEvictionsLocked() error {
	data, err := json.Marshal(s.evicted)
	if err != nil {
		return fmt.Errorf("spool: encode evictions: %w", err)
	}
	tmp := s.evictedPath + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return fmt.Errorf("spool: write %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, s.evictedPath); err != nil {
		return fmt.Errorf("spool: rename %s: %w", tmp, err)
	}
	return nil
}
