// apps/agent/internal/status/status.go

// Package status persists the daemon's runtime state to
// <state-dir>/status.json, the source of truth `cb-agent status` reads from
// (specs/2026-07-26-cb-agent-design.md §4.7: "link state, grants, collector
// readiness, spool depth"). Before this package existed, `cb-agent status`
// had no daemon state to read and instead called
// enroll.LoadOrCreateDeviceKey — generating a device identity as a side
// effect of an inspection command. This package exists so that bug has a
// real fix: the CLI reads a file the daemon writes, and never touches
// device.key itself.
package status

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

const filename = "status.json"

// LinkState is the daemon's last-known outcome of its link attempt.
type LinkState string

const (
	// LinkDisconnected is both the initial state (before any link attempt has
	// completed) and the state after a previously-up connection drops.
	LinkDisconnected LinkState = "disconnected"
	// LinkAccepted means the most recent hello.ack accepted this session.
	LinkAccepted LinkState = "accepted"
	// LinkRejected means the most recent hello.ack explicitly refused this
	// session (e.g. device-key mismatch, revoked/deactivated agent).
	LinkRejected LinkState = "rejected"
)

// Status is the full runtime snapshot persisted to <state-dir>/status.json.
// cb-agent status reads this file directly rather than talking to the
// running daemon process, so every field here must be something the daemon
// writes as the corresponding event actually happens — nothing here is
// inferred or reconstructed after the fact.
type Status struct {
	Version     string    `json:"version"`
	Fingerprint string    `json:"fingerprint,omitempty"`
	LinkState   LinkState `json:"link_state"`

	// LastConnected is when the link most recently reached an accepted
	// hello.ack. It is left at its prior value across a disconnect/rejection
	// so status can still answer "when did this last work".
	LastConnected time.Time `json:"last_connected,omitempty"`

	// LastError/LastErrorAt describe the most recent rejection or
	// disconnect. Cleared on the next accepted hello.ack.
	LastError   string    `json:"last_error,omitempty"`
	LastErrorAt time.Time `json:"last_error_at,omitempty"`

	// Grants mirrors the capability gate's current authoritative set (see
	// internal/capability), updated whenever a capabilities.set frame is
	// applied.
	Grants map[string]bool `json:"grants,omitempty"`

	// Readiness mirrors the most recent hello's collector-readiness report
	// (see internal/hostinfo).
	Readiness []frame.Readiness `json:"readiness,omitempty"`

	// SpoolDepth/SpoolBytes report the outbound spool's backlog. Both stay at
	// their zero value until the daemon actually spools data frames — true
	// today (spec: the spool "stays idle in heartbeat-only Slice 1
	// operation"; see internal/spool's daemon wiring).
	SpoolDepth int   `json:"spool_depth"`
	SpoolBytes int64 `json:"spool_bytes"`

	// UpdatedAt is set on every write, independent of which fields changed.
	UpdatedAt time.Time `json:"updated_at"`
}

// Writer persists a Status to <stateDir>/status.json. Every mutation writes
// the whole file atomically — to a temp file in the same directory, then
// renamed into place — so a concurrent reader (cb-agent status, run at any
// time while the daemon is live) never observes a partially-written file.
// Mutations are serialized under a mutex so concurrent callers (link
// accept/reject/disconnect, capability changes, spool depth changes) can't
// interleave a torn write.
type Writer struct {
	mu   sync.Mutex
	path string
	cur  Status
}

// NewWriter starts a fresh Writer for stateDir with the daemon's build
// version and identity fingerprint, and LinkState at its zero-value initial
// state (LinkDisconnected — no link attempt has completed yet). It does not
// write anything to disk; the first mutating call does.
func NewWriter(stateDir, version, fingerprint string) *Writer {
	return &Writer{
		path: filepath.Join(stateDir, filename),
		cur: Status{
			Version:     version,
			Fingerprint: fingerprint,
			LinkState:   LinkDisconnected,
		},
	}
}

// SetAccepted records an accepted hello.ack: link state flips to accepted,
// LastConnected advances to now, and any previously recorded error is
// cleared (a successful link supersedes the last failure).
func (w *Writer) SetAccepted() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.LinkState = LinkAccepted
	w.cur.LastConnected = time.Now().UTC()
	w.cur.LastError = ""
	w.cur.LastErrorAt = time.Time{}
	return w.persistLocked()
}

// SetRejected records a rejected hello.ack with the server's stated reason.
func (w *Writer) SetRejected(reason string) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.LinkState = LinkRejected
	w.cur.LastError = reason
	w.cur.LastErrorAt = time.Now().UTC()
	return w.persistLocked()
}

// SetDisconnected records the end of a connection that was never explicitly
// rejected — a dropped socket, a read error, a dial failure. cause may be
// nil (e.g. a clean, expected teardown); when non-nil its message is
// recorded as the last error.
func (w *Writer) SetDisconnected(cause error) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.LinkState = LinkDisconnected
	if cause != nil {
		w.cur.LastError = cause.Error()
		w.cur.LastErrorAt = time.Now().UTC()
	}
	return w.persistLocked()
}

// SetGrants records the capability gate's current authoritative grant set.
// Callers should pass a snapshot they own (e.g. capability.Gate.Grants()),
// not a map still being mutated elsewhere.
func (w *Writer) SetGrants(grants map[string]bool) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.Grants = grants
	return w.persistLocked()
}

// SetReadiness records the most recent hello's collector-readiness report.
func (w *Writer) SetReadiness(readiness []frame.Readiness) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.Readiness = readiness
	return w.persistLocked()
}

// SetSpoolStats records the outbound spool's current backlog depth (frame
// count) and size in bytes. Called at daemon startup (after spool.Open's
// unclean-shutdown recovery) and on every subsequent spool mutation via
// internal/link's Options.OnSpoolStats — see cmd/cb-agent's openSpool and
// dataFrameSender. Both fields stay at zero in practice today: Slice 1 has
// no data frame producer, so nothing ever enqueues (Global Constraints —
// "the spool ... stays idle in heartbeat-only Slice 1 operation").
func (w *Writer) SetSpoolStats(depth int, bytes int64) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.cur.SpoolDepth = depth
	w.cur.SpoolBytes = bytes
	return w.persistLocked()
}

// persistLocked marshals the current snapshot and writes it to w.path
// atomically: write to a sibling temp file with mode 0600, then rename over
// the destination. Rename is atomic within the same directory on every OS
// this daemon targets, so a reader either sees the previous complete file or
// the new complete one, never a partial write. The temp file's 0600 mode
// carries through the rename, so the destination is also 0600 at creation.
func (w *Writer) persistLocked() error {
	w.cur.UpdatedAt = time.Now().UTC()
	data, err := json.MarshalIndent(w.cur, "", "  ")
	if err != nil {
		return fmt.Errorf("status: marshal: %w", err)
	}
	dir := filepath.Dir(w.path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("status: create state dir: %w", err)
	}
	tmp := w.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return fmt.Errorf("status: write %s: %w", tmp, err)
	}
	// os.WriteFile only applies perm to a newly-created file — if a stale
	// 0644 temp file survived a prior crash, force 0600 explicitly rather
	// than trusting WriteFile's perm argument.
	if err := os.Chmod(tmp, 0o600); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("status: chmod %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, w.path); err != nil {
		return fmt.Errorf("status: rename %s -> %s: %w", tmp, w.path, err)
	}
	return nil
}

// Read loads the status file at <stateDir>/status.json. ok is false with a
// nil error when the file does not exist yet (the daemon has never run, or
// has not persisted a snapshot yet) — callers such as `cb-agent status` must
// report that truthfully rather than treating it as an error.
func Read(stateDir string) (st Status, ok bool, err error) {
	data, err := os.ReadFile(filepath.Join(stateDir, filename))
	if os.IsNotExist(err) {
		return Status{}, false, nil
	}
	if err != nil {
		return Status{}, false, fmt.Errorf("status: read: %w", err)
	}
	if err := json.Unmarshal(data, &st); err != nil {
		return Status{}, false, fmt.Errorf("status: parse: %w", err)
	}
	return st, true, nil
}
