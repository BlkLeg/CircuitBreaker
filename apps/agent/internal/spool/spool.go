// apps/agent/internal/spool/spool.go
package spool

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/logging"
)

const (
	DefaultCapBytes int64 = 64 * 1024 * 1024
	queueFilename         = "queue.jsonl"
	// headFilename marks how many leading queue.jsonl lines have already
	// been delivered. It is a separate file rather than a rewrite of
	// queue.jsonl so committing a catch-up burst costs one small atomic
	// write instead of rewriting the whole (up to capBytes) queue.
	headFilename = "queue.head"
	// compactHeadThreshold is how many consumed entries may accumulate
	// before Commit rewrites queue.jsonl without them. 512 is ~2 minutes of
	// catch-up at the link's paced drain budget (4 frames per 100ms tick),
	// so compaction runs rarely enough to stay off the hot path and often
	// enough that the consumed prefix never dominates the file.
	compactHeadThreshold = 512
)

// Spool is a bounded, oldest-dropped, append-only queue for *data* frames
// only — control frames must never be enqueued (spec §4.4). Persisted as
// newline-delimited JSON so an unclean shutdown still recovers every line
// that was fully written before the crash; a torn final line is dropped and
// rewritten away by load() before anything is appended after it.
//
// Delivery is two-phase and at-least-once: Peek hands out frames without
// consuming them and only Commit — called after the frames have actually
// been written to the wire — discards them. A crash mid-burst therefore
// re-sends rather than loses, which is safe because the backend dedupes
// ingested samples on (agent_id, sample_id, collected_at).
//
// On-disk layout is a consumed prefix plus a live remainder: queue.jsonl
// holds every line ever appended since the last compaction and queue.head
// records how many leading lines are already delivered. Len/SizeBytes
// describe the *undelivered* remainder — the backlog a caller can still
// send — so queue.jsonl on disk may be larger than SizeBytes reports until
// the next compaction.
type Spool struct {
	mu       sync.Mutex
	path     string
	headPath string
	capBytes int64
	entries  []entry
	// head is the consumed prefix: entries[:head] have been delivered and
	// are pending compaction, entries[head:] are the live backlog.
	head int
	// origin is the absolute position of entries[head] — how many frames
	// have left the live backlog since this Spool was opened, whether by
	// Commit or by cap eviction.
	//
	// It exists because positional bookkeeping is not safe for a caller that
	// holds frames across a round trip. `Commit(n)` and a head-relative peek
	// both describe "the first n live frames", and the drop-oldest policy in
	// Enqueue advances head underneath them — from another goroutine, since
	// the producer enqueues while the link drains. For a caller that commits
	// immediately after writing (drainCommitOnWrite) the window is a few
	// microseconds wide; for one that commits only when the *server*
	// acknowledges, it is a whole ack round trip, and the frames at the head
	// are precisely the ones in flight. An eviction in that window made
	// Commit discard that many never-sent frames on top of the ones eviction
	// had already destroyed — a silent, uncounted loss of roughly twice the
	// evicted amount.
	//
	// Positions are stable across both eviction and commit, so PeekAt and
	// CommitThrough let such a caller name exactly the frames it means. They
	// are per-Spool-instance and deliberately not persisted: the only caller
	// that needs them holds them for the life of one connection, which cannot
	// outlive the process.
	origin int64
	// bytes is the encoded size (including newlines) of entries[head:],
	// maintained incrementally on load/enqueue/commit/compact so SizeBytes
	// is O(1) instead of re-encoding the whole queue.
	bytes int64
	// evictedPath / evicted are the permanent record of what the
	// drop-oldest policy has destroyed — see evictions.go. Cumulative for
	// the life of the state directory and never reset by this package.
	evictedPath string
	evicted     EvictionStats
}

// entry is one queued frame plus the encoded length (including its trailing
// newline) it occupies in queue.jsonl. Only the length is cached, not the
// encoding itself — a full 64MiB spool would otherwise be held twice in
// memory, and re-encoding happens only on the rare compaction path.
type entry struct {
	f frame.Frame
	n int64
}

func Open(stateDir string, capBytes int64) (*Spool, error) {
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("spool: create state dir: %w", err)
	}
	s := &Spool{
		path:        filepath.Join(stateDir, queueFilename),
		headPath:    filepath.Join(stateDir, headFilename),
		evictedPath: filepath.Join(stateDir, evictedFilename),
		capBytes:    capBytes,
	}
	// Before load(): the eviction record describes history this state
	// directory has already destroyed, and an agent restart must not be able
	// to zero it. A read failure is fatal to Open for the same reason —
	// continuing with a blank record would silently under-report the loss.
	if err := s.loadEvictions(); err != nil {
		return nil, err
	}
	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

// load reads the head marker first, then queue.jsonl, drops the consumed
// prefix and compacts immediately so a restart never re-reads a prefix it
// has already delivered. It also compacts when any line failed to decode —
// an unclean shutdown can leave a torn final line, and the append-only write
// path would otherwise fuse the next enqueued frame onto it and lose both.
// A missing or garbage marker means head=0: every surviving line is re-sent,
// which is safe (delivery is at-least-once and the backend dedupes) and
// strictly better than losing frames.
func (s *Spool) load() error {
	persistedHead, markerPresent := s.readHeadMarker()

	f, err := os.Open(s.path)
	if os.IsNotExist(err) {
		if markerPresent {
			return s.removeHeadMarker()
		}
		return nil
	}
	if err != nil {
		return fmt.Errorf("spool: open %s: %w", s.path, err)
	}

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	torn := false
	for scanner.Scan() {
		line := scanner.Bytes()
		fr, decodeErr := frame.Decode(line)
		if decodeErr != nil {
			// A truncated final line from an unclean shutdown. Only the last
			// line can be torn (every earlier one was fsync'd whole), so
			// skipping it cannot shift the head marker's line alignment.
			// Skipping is not enough on its own: Enqueue appends with
			// O_APPEND, so the next frame would be written straight onto the
			// torn bytes and both would decode as nothing. Record it and heal
			// the file below.
			torn = true
			continue
		}
		s.entries = append(s.entries, entry{f: fr, n: int64(len(line)) + 1})
	}
	closeErr := f.Close()
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("spool: read %s: %w", s.path, err)
	}
	if closeErr != nil {
		return fmt.Errorf("spool: close %s: %w", s.path, closeErr)
	}

	s.head = persistedHead
	if s.head > len(s.entries) {
		s.head = len(s.entries)
	}
	s.recountBytesLocked()

	if s.head > 0 || torn {
		return s.compactLocked()
	}
	if markerPresent {
		return s.removeHeadMarker()
	}
	return nil
}

// readHeadMarker returns the persisted consumed-prefix length and whether a
// marker file exists at all. Any unreadable or non-numeric marker reports
// head=0 (present, so it still gets cleaned up).
func (s *Spool) readHeadMarker() (int, bool) {
	data, err := os.ReadFile(s.headPath)
	if err != nil {
		return 0, false
	}
	n, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || n < 0 {
		return 0, true
	}
	return n, true
}

// writeHeadMarker persists s.head atomically — temp file at 0600, then
// rename over the destination — mirroring status.Writer.persistLocked, so a
// reader (or a restart) sees either the previous complete value or the new
// one, never a partial write.
func (s *Spool) writeHeadMarker() error {
	tmp := s.headPath + ".tmp"
	if err := os.WriteFile(tmp, []byte(strconv.Itoa(s.head)+"\n"), 0o600); err != nil {
		return fmt.Errorf("spool: write %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, s.headPath); err != nil {
		return fmt.Errorf("spool: rename %s: %w", tmp, err)
	}
	return nil
}

func (s *Spool) removeHeadMarker() error {
	if err := os.Remove(s.headPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("spool: remove %s: %w", s.headPath, err)
	}
	return nil
}

func (s *Spool) recountBytesLocked() {
	s.bytes = 0
	for _, e := range s.entries[s.head:] {
		s.bytes += e.n
	}
}

// compactLocked rewrites queue.jsonl from the live remainder only, resets
// head to zero and removes the marker. Called from load(), from Commit once
// the consumed prefix crosses a threshold, and from the eviction path.
func (s *Spool) compactLocked() error {
	live := s.entries[s.head:]
	tmp := s.path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("spool: create %s: %w", tmp, err)
	}
	w := bufio.NewWriter(f)
	kept := make([]entry, 0, len(live))
	var total int64
	for _, e := range live {
		data, encodeErr := frame.Encode(e.f)
		if encodeErr != nil {
			f.Close()
			return fmt.Errorf("spool: encode: %w", encodeErr)
		}
		w.Write(data)
		w.WriteByte('\n')
		n := int64(len(data)) + 1
		kept = append(kept, entry{f: e.f, n: n})
		total += n
	}
	if err := w.Flush(); err != nil {
		f.Close()
		return fmt.Errorf("spool: flush: %w", err)
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return fmt.Errorf("spool: sync %s: %w", tmp, err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("spool: close: %w", err)
	}
	if err := os.Rename(tmp, s.path); err != nil {
		return fmt.Errorf("spool: rename %s: %w", tmp, err)
	}
	s.entries = kept
	s.head = 0
	s.bytes = total
	return s.removeHeadMarker()
}

// Enqueue appends f, evicting the oldest entries (FIFO) if the resulting
// queue would exceed capBytes. Only call this for data frames — see the
// package doc comment.
//
// The common path appends exactly one line to queue.jsonl; the whole file is
// only rewritten when eviction actually drops something. A whole-file
// rewrite per enqueue would be O(n²) in I/O — hundreds of gigabytes to fill
// one 64MiB spool.
func (s *Spool) Enqueue(f frame.Frame) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := frame.Encode(f)
	if err != nil {
		return fmt.Errorf("spool: encode: %w", err)
	}
	if err := s.appendLine(data); err != nil {
		return err
	}
	s.entries = append(s.entries, entry{f: f, n: int64(len(data)) + 1})
	s.bytes += int64(len(data)) + 1

	// Eviction is the drop-oldest policy the spool has always had. What is
	// new is that it is recorded and said out loud: `batch` accumulates this
	// one Enqueue's losses so the log line below fires once per batch rather
	// than once per destroyed frame, and s.evicted accumulates them for the
	// life of the state directory.
	var batch EvictionStats
	for s.bytes > s.capBytes && len(s.entries)-s.head > 1 {
		dropped := s.entries[s.head]
		s.bytes -= dropped.n
		s.head++
		s.origin++
		batch.Frames++
		batch.Bytes += dropped.n
		// The dropped frame's own TS, not time.Now(): the fact worth
		// recording is which observations were lost, not when the eviction
		// ran. LastEvictedAt below is the wall-clock half.
		batch.widen(dropped.f.TS)
	}
	if batch.Frames == 0 {
		return nil
	}

	s.evicted.Frames += batch.Frames
	s.evicted.Bytes += batch.Bytes
	s.evicted.widen(batch.OldestDroppedTS)
	s.evicted.widen(batch.NewestDroppedTS)
	s.evicted.LastEvictedAt = time.Now().UTC()

	// logging.Warnf, not log.Printf. internal/logging.Configure points the
	// standard log package at a gate that forwards only while Info is
	// enabled, so a log.Printf line — whatever word it contains — disappears
	// entirely at `log_level = "warn"`. That is precisely the setting an
	// operator reduces noise with on a homelab box, and losing the one signal
	// that data was destroyed to a noise-reduction setting would reproduce
	// this task's whole defect one layer down.
	logging.Warnf(
		"cb-agent: spool: WARNING permanently discarded %d buffered observation(s) (%d bytes) covering %s..%s "+
			"to stay under the %d-byte cap; cumulative loss for this agent is %d observation(s) / %d bytes. "+
			"This data is gone and cannot be recovered — raise spool_cap_bytes in agent.toml if the outage window matters.",
		batch.Frames, batch.Bytes,
		formatEvictedTS(batch.OldestDroppedTS), formatEvictedTS(batch.NewestDroppedTS),
		s.capBytes, s.evicted.Frames, s.evicted.Bytes,
	)

	// Persisted before the compaction that actually rewrites the queue, so a
	// crash between the two leaves the record over-stating nothing and
	// under-stating nothing: the frames are already gone from s.entries.
	// A write failure is loud but not fatal to Enqueue — the frame the caller
	// handed us *is* spooled, and returning an error here would tell it
	// otherwise and invite a double-handle.
	if err := s.persistEvictionsLocked(); err != nil {
		// Errorf, a level above the eviction line itself: the loss has
		// happened either way, but a record that could not be written is a
		// loss the next restart will not be able to report at all.
		logging.Errorf("cb-agent: spool: could not persist the eviction record: %v", err)
	}
	return s.compactLocked()
}

// formatEvictedTS renders one end of a destroyed window for the log line.
// A frame that carried no timestamp leaves the bound unknown, and saying so
// is better than printing year 1 as though it were a real observation time.
func formatEvictedTS(ts time.Time) string {
	if ts.IsZero() {
		return "unknown"
	}
	return ts.UTC().Format(time.RFC3339)
}

func (s *Spool) appendLine(data []byte) error {
	f, err := os.OpenFile(s.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("spool: open %s: %w", s.path, err)
	}
	if _, err := f.Write(append(data, '\n')); err != nil {
		f.Close()
		return fmt.Errorf("spool: append %s: %w", s.path, err)
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return fmt.Errorf("spool: sync %s: %w", s.path, err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("spool: close %s: %w", s.path, err)
	}
	return nil
}

// Peek returns up to maxFrames undelivered frames from the head, in FIFO
// order, stopping once their encoded size would exceed maxBytes. It mutates
// nothing: the caller sends them and then calls Commit with the number that
// actually made it onto the wire.
//
// The first frame is always returned regardless of maxBytes, so a frame
// larger than one tick's byte budget cannot wedge the queue forever.
func (s *Spool) Peek(maxFrames int, maxBytes int64) []frame.Frame {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.peekLocked(0, maxFrames, maxBytes)
}

// FromHead asks PeekAt to start at the head of the live backlog, whatever
// absolute position that currently is.
const FromHead int64 = -1

// PeekResult is one PeekAt answer, positioned in the spool's absolute stream
// so the caller can hold it across a round trip. See Spool.origin.
type PeekResult struct {
	Frames []frame.Frame
	// Start is the absolute position of Frames[0]. Meaningless when Frames
	// is empty. It can be *greater* than the `from` the caller asked for:
	// cap eviction may have destroyed everything between the two, and the
	// gap is the caller's evidence of exactly that.
	Start int64
	// Origin is the absolute position of the live backlog's head at the
	// moment of this peek. Everything below it has left the spool — some
	// committed, some destroyed by the cap — and is reported in the same
	// call so a caller cannot race between reading one and the other.
	Origin int64
}

// PeekAt returns up to maxFrames live frames starting at absolute position
// `from` (FromHead for the oldest undelivered frame), stopping once their
// encoded size would exceed maxBytes. It mutates nothing.
//
// This is the peek half of position-based delivery — see Spool.origin for why
// a head-relative index is not safe to hold across a round trip. A `from`
// below the current head is not an error: the frames it named are gone, and
// the result's Start and Origin say so.
//
// The first frame is always returned regardless of maxBytes, so a frame
// larger than one tick's byte budget cannot wedge the queue forever.
func (s *Spool) PeekAt(from int64, maxFrames int, maxBytes int64) PeekResult {
	s.mu.Lock()
	defer s.mu.Unlock()

	skip := 0
	if from > s.origin {
		skip = int(from - s.origin)
	}
	return PeekResult{
		Frames: s.peekLocked(skip, maxFrames, maxBytes),
		Start:  s.origin + int64(skip),
		Origin: s.origin,
	}
}

// Origin is the absolute position of the oldest undelivered frame. It only
// ever increases, and a caller holding positions below it is holding frames
// that have left the spool.
func (s *Spool) Origin() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.origin
}

// peekLocked is the shared body of Peek and PeekAt, so the byte budget and
// the always-return-the-first-frame rule cannot drift between them.
func (s *Spool) peekLocked(skip, maxFrames int, maxBytes int64) []frame.Frame {
	if maxFrames <= 0 || skip < 0 {
		return nil
	}
	live := s.entries[s.head:]
	if skip >= len(live) {
		return nil
	}
	live = live[skip:]
	out := make([]frame.Frame, 0, min(maxFrames, len(live)))
	var total int64
	for _, e := range live {
		if len(out) == maxFrames {
			break
		}
		if len(out) > 0 && total+e.n > maxBytes {
			break
		}
		out = append(out, e.f)
		total += e.n
	}
	return out
}

// Commit discards the first n undelivered frames. n is clamped to what is
// available, so committing more than was peeked (or committing an empty
// spool) is a no-op rather than an error. Nothing is discarded before this
// call, which is what makes a crash mid-burst re-send rather than lose.
//
// It is the count-based primitive CommitThrough is built on, and it is only
// safe for a caller that can be certain the head has not moved since it chose
// n — which, with a producer enqueueing from another goroutine and a
// drop-oldest cap policy, no caller holding frames across a send can be. Use
// CommitThrough instead: it names frames by position and cannot be fooled by
// an eviction.
func (s *Spool) Commit(n int) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.commitLocked(n)
}

// CommitThrough discards every live frame whose absolute position is at or
// below pos — the commit half of position-based delivery.
//
// A pos already below the head is a no-op rather than an error, and that is
// the whole point: those frames left the spool while the caller was waiting
// for its acknowledgement, either because the caller itself committed them or
// because cap eviction destroyed them. A positional Commit could not tell the
// difference and would discard that many *unsent* frames instead. Eviction
// already counted what it destroyed (see EvictionStats), so nothing here is
// lost silently.
func (s *Spool) CommitThrough(pos int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if pos < s.origin {
		return nil
	}
	return s.commitLocked(int(pos - s.origin + 1))
}

func (s *Spool) commitLocked(n int) error {
	if n <= 0 {
		return nil
	}
	if available := len(s.entries) - s.head; n > available {
		n = available
	}
	if n == 0 {
		return nil
	}
	var consumed int64
	for _, e := range s.entries[s.head : s.head+n] {
		consumed += e.n
	}
	s.head += n
	s.origin += int64(n)
	s.bytes -= consumed

	if s.head >= compactHeadThreshold || s.consumedBytesLocked() > s.capBytes/4 {
		return s.compactLocked()
	}
	return s.writeHeadMarker()
}

func (s *Spool) consumedBytesLocked() int64 {
	var total int64
	for _, e := range s.entries[:s.head] {
		total += e.n
	}
	return total
}

// Len reports the number of *undelivered* frames — the backlog still to be
// sent, not the number of lines in queue.jsonl.
func (s *Spool) Len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.entries) - s.head
}

// SizeBytes reports the encoded size of the undelivered backlog. It is O(1):
// the counter is maintained on every mutation rather than re-encoding the
// queue. The error return is retained for API compatibility and is always
// nil.
func (s *Spool) SizeBytes() (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.bytes, nil
}

func (s *Spool) Close() error {
	return nil // every mutation already writes through
}
