// apps/agent/internal/spool/spool.go
package spool

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

const (
	DefaultCapBytes      int64 = 64 * 1024 * 1024
	DrainInterleaveRatio       = 4 // one spooled frame per four live frames
	queueFilename              = "queue.jsonl"
)

// Spool is a bounded, oldest-dropped, append-only queue for *data* frames
// only — control frames must never be enqueued (spec §4.4). Persisted as
// newline-delimited JSON so an unclean shutdown still recovers everything
// written before the crash.
type Spool struct {
	mu       sync.Mutex
	path     string
	capBytes int64
	entries  []frame.Frame
}

func Open(stateDir string, capBytes int64) (*Spool, error) {
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, fmt.Errorf("spool: create state dir: %w", err)
	}
	path := filepath.Join(stateDir, queueFilename)
	s := &Spool{path: path, capBytes: capBytes}
	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Spool) load() error {
	f, err := os.Open(s.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("spool: open %s: %w", s.path, err)
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		fr, err := frame.Decode(scanner.Bytes())
		if err != nil {
			continue // skip a truncated final line from an unclean shutdown
		}
		s.entries = append(s.entries, fr)
	}
	return scanner.Err()
}

func (s *Spool) persist() error {
	tmp := s.path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("spool: create %s: %w", tmp, err)
	}
	w := bufio.NewWriter(f)
	for _, e := range s.entries {
		data, err := frame.Encode(e)
		if err != nil {
			f.Close()
			return fmt.Errorf("spool: encode: %w", err)
		}
		w.Write(data)
		w.WriteByte('\n')
	}
	if err := w.Flush(); err != nil {
		f.Close()
		return fmt.Errorf("spool: flush: %w", err)
	}
	if err := f.Close(); err != nil {
		return fmt.Errorf("spool: close: %w", err)
	}
	return os.Rename(tmp, s.path)
}

func (s *Spool) sizeBytesLocked() (int64, error) {
	var total int64
	for _, e := range s.entries {
		data, err := frame.Encode(e)
		if err != nil {
			return 0, err
		}
		total += int64(len(data)) + 1
	}
	return total, nil
}

// Enqueue appends f, evicting the oldest entries (FIFO) if the resulting
// queue would exceed capBytes. Only call this for data frames — see the
// package doc comment.
func (s *Spool) Enqueue(f frame.Frame) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.entries = append(s.entries, f)
	for {
		size, err := s.sizeBytesLocked()
		if err != nil {
			return err
		}
		if size <= s.capBytes || len(s.entries) <= 1 {
			break
		}
		s.entries = s.entries[1:]
	}
	return s.persist()
}

func (s *Spool) Drain() (frame.Frame, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if len(s.entries) == 0 {
		return frame.Frame{}, false, nil
	}
	f := s.entries[0]
	s.entries = s.entries[1:]
	if err := s.persist(); err != nil {
		return frame.Frame{}, false, err
	}
	return f, true, nil
}

func (s *Spool) Len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.entries)
}

func (s *Spool) SizeBytes() (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.sizeBytesLocked()
}

func (s *Spool) Close() error {
	return nil // persist() already writes through on every mutation
}
