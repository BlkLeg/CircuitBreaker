// apps/agent/internal/link/seqguard.go
package link

import (
	"fmt"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// inboundSeqGuard tracks per-session inbound-frame validation state for one
// /link connection: protocol version and strictly increasing sequence
// numbers. It mirrors the server's LinkSessionState/receive_frame in
// apps/backend/src/app/services/agent_link.py, which performs the same
// checks for the agent -> server direction. A zero-value inboundSeqGuard is
// ready to use: hasSeen starts false, so the first frame of a session (any
// non-negative Seq) is accepted and becomes the new baseline.
type inboundSeqGuard struct {
	hasSeen bool
	lastSeq uint64
}

// validate reports whether f is acceptable as the next frame in the
// session. Rejections are: an unsupported protocol version, a malformed
// envelope (empty Type — Decode() already rejects unparseable JSON before
// this is ever called), and a sequence number that is not strictly greater
// than the last one accepted in this session (covers both exact-duplicate
// replays and any decreasing sequence). On acceptance, f.Seq becomes the
// new baseline for the next call.
func (g *inboundSeqGuard) validate(f frame.Frame) error {
	if f.V != frame.FrameVersion {
		return fmt.Errorf("unsupported frame version %d (want %d)", f.V, frame.FrameVersion)
	}
	if f.Type == "" {
		return fmt.Errorf("malformed frame: empty type (seq %d)", f.Seq)
	}
	if g.hasSeen {
		switch {
		case f.Seq == g.lastSeq:
			return fmt.Errorf("duplicate sequence %d", f.Seq)
		case f.Seq < g.lastSeq:
			return fmt.Errorf("decreasing sequence %d (last accepted %d)", f.Seq, g.lastSeq)
		}
	}
	g.hasSeen = true
	g.lastSeq = f.Seq
	return nil
}
