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
}

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

	// Errorf, not Warnf: cap eviction is a policy working as designed, while
	// this is the spool failing to do its job at all — and unlike eviction it
	// will keep happening, silently, for as long as the underlying condition
	// lasts.
	logging.Errorf(
		"cb-agent: spool: WARNING permanently lost one observation from %s (%s) — it could not be "+
			"buffered and there is no other copy; cumulative loss for this agent is %d observation(s) / %d bytes.",
		formatEvictedTS(f.TS), reason, s.evicted.Frames, s.evicted.Bytes,
	)
	if err := s.persistEvictionsLocked(); err != nil {
		logging.Errorf("cb-agent: spool: could not persist the eviction record: %v", err)
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
