// apps/agent/internal/link/link.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/hostinfo"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
	"circuitbreaker.dev/cb-agent/internal/spool"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

var heartbeatInterval = 20 * time.Second

// stabilityWindow is how long a connection must stay up after an accepted
// hello.ack before Run treats the run as "stable" and resets reconnect
// backoff to its floor. Gating on hello.ack alone isn't enough: a link that
// connects, gets accepted, then drops almost immediately (e.g. a transient
// server-side error one heartbeat tick later) would otherwise reset backoff
// on every cycle, defeating exponential backoff for a flapping link and
// risking a reconnect storm against the server. 30s — 1.5x the default
// heartbeatInterval — is a judgment call (not specified numerically in the
// brief/spec): long enough that a connection which drops shortly after
// accept clearly doesn't qualify, short enough not to meaningfully delay
// backoff recovery for a genuinely healthy link. A var, not a const, so
// tests can shrink it.
var stabilityWindow = 30 * time.Second

// rekeyIntervalEnvOverride is a narrowly-scoped, test-only escape hatch: if
// set to a positive integer number of seconds, it replaces the production
// 15-minute rekeyInterval below. It exists solely so the Docker E2E harness
// (apps/agent/e2e) can exercise a real Noise rekey cycle without waiting out
// 15 real minutes. No production deployment path (the install script,
// systemd unit, or any documented config) ever sets this variable, and when
// it is unset — as in every real deployment — rekeyInterval is byte-for-byte
// the same 15*time.Minute production default it has always been (see
// resolveRekeyInterval's unit test, TestResolveRekeyInterval_UnsetIsInert).
// Global Constraints mandates the 15-minute production default; this
// override changes nothing about that default, it only lets a test ask for
// something shorter.
const rekeyIntervalEnvOverride = "CB_AGENT_TEST_REKEY_INTERVAL_SECONDS"

// resolveRekeyInterval reads rekeyIntervalEnvOverride and returns the
// interval rekeyInterval should start at. Split out from the var
// initializer purely so a unit test can call it directly (via t.Setenv)
// without depending on process-startup timing.
func resolveRekeyInterval() time.Duration {
	if v := os.Getenv(rekeyIntervalEnvOverride); v != "" {
		if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
			return time.Duration(secs) * time.Second
		}
	}
	return 15 * time.Minute
}

// rekeyInterval is how often each side rotates its *own* outbound Noise
// cipher (spec §3.5). The two directions are independent: the agent times its
// agent->server cipher here, the server times its server->agent cipher in
// ws_agents.py's link_stream, and neither waits on the other. A var, not a
// const, so tests can shrink it (either directly, in-process, or — for the
// Docker E2E harness, which runs the compiled binary as a separate process —
// via rekeyIntervalEnvOverride) — production stays at 15 minutes.
var rekeyInterval = resolveRekeyInterval()

// rekeyDirectionOutbound is the only `transport.rekey` direction either side
// ever sends. `direction` is sender-relative (see frame.TransportRekeyPayload),
// so "outbound" means "the cipher I encrypt with", which the receiver matches
// to its own receive cipher. A peer has no way to rekey our send cipher, so an
// inbound frame claiming direction "inbound" is nonsense and gets rejected
// rather than guessed at.
const rekeyDirectionOutbound = "outbound"

// SendUpdateStatus reports one self-update transition (`update.status`,
// Task 24) over the live connection it's called from: version is the update
// target, phase is "started"/"succeeded"/"failed"/"rolled_back", and errMsg
// is only meaningful alongside "failed" (pass "" otherwise). Best-effort — a
// non-nil error means the frame didn't go out (e.g. the connection just
// dropped); callers other than runOnce's own rollback-report check treat that
// as informational, not fatal, since the underlying update outcome already
// happened regardless of whether the server heard about it promptly.
type SendUpdateStatus func(version, phase, errMsg string) error

type Options struct {
	Config            *config.Config
	Key               *enroll.DeviceKey
	AgentVersion      string
	OnCapabilitiesSet func(json.RawMessage) error
	// OnUpdate applies one `update` instruction (download, verify, swap,
	// re-exec). send lets it report its own progress — "started" right after
	// unmarshalling the instruction, "failed" with a message on any
	// download/verify/swap error, or "succeeded" right before re-exec'ing
	// into the new binary (re-exec replaces the process image and never
	// returns to the caller on success, which is why "succeeded" can't
	// instead be sent by runOnce after OnUpdate returns — cmd/cb-agent/
	// main.go's onUpdate is the one place that actually knows the swap
	// landed).
	OnUpdate    func(payload json.RawMessage, send SendUpdateStatus) error
	OnConnected func()
	// OnRejected fires whenever an explicit hello.ack rejection arrives
	// (accepted: false), with the server's stated reason. Unlike
	// OnConnected/OnDisconnected this does not end the connection — the
	// loop keeps reading in case the server later sends an accepted ack —
	// so it may fire more than once per connection.
	OnRejected func(reason string)
	// OnDisconnected fires once per runOnce call that ends other than by ctx
	// cancellation — a dropped socket, a read/decrypt error, a dial failure,
	// or the server requesting disconnect — with the error that ended it.
	// cause is never nil when this fires from Run's reconnect loop.
	OnDisconnected func(cause error)
	// ReportPendingUpdateOutcome, if set, is checked once per connection
	// right after its first accepted hello.ack (same moment OnConnected
	// fires) for an update outcome a *previous* process couldn't report live
	// — today, only the rollback case (see internal/update's
	// WriteRollbackReport doc comment for why). ok is false when there is
	// nothing pending, the overwhelmingly common case.
	ReportPendingUpdateOutcome func() (version string, ok bool)
	// ClearPendingUpdateOutcome is called after ReportPendingUpdateOutcome's
	// report has actually been sent (sendUpdateStatus returned no error), so
	// it isn't repeated on the next reconnect. Never called otherwise — a
	// send that failed (e.g. the connection dropped immediately after
	// hello.ack) leaves the report in place for the next reconnect to retry.
	ClearPendingUpdateOutcome func()

	// Spool durably buffers outbound *data* frames (never heartbeat/control
	// traffic — frame.IsDataFrame draws that line) when a live send fails,
	// and is drained back into the live stream at
	// spool.DrainInterleaveRatio (see dataFrameSender in outbound.go). Nil
	// disables spooling entirely — e.g. Uninstall's one-shot connection has
	// no ongoing data-frame flow to buffer, and today's daemon has no real
	// data frame producer yet either (Global Constraints: "the spool ...
	// stays idle in heartbeat-only Slice 1 operation").
	Spool *spool.Spool

	// DataFrames is where a producer outside this package — a Slice 2+
	// telemetry/probe/discovery collector — sends outbound data frames for
	// this link to transmit. runOnce assigns V/Seq/TS itself before sending,
	// same as it does for heartbeat/rekey frames. A nil channel (Slice 1's
	// default: nothing produces data frames yet) simply never selects, so
	// the whole mechanism stays inert until a real producer exists.
	DataFrames <-chan frame.Frame

	// OnSpoolStats fires after every spool mutation (a live-send failure
	// enqueues, or a drain succeeds or fails-and-re-enqueues) with the
	// spool's resulting depth and size in bytes, so callers can mirror it
	// into e.g. status.Writer.SetSpoolStats. May be nil.
	OnSpoolStats func(depth int, bytes int64)

	// StateDir is where a Task 28 `key.rotate` (kind="server") frame's
	// successor server public key is durably persisted (see
	// config.SaveServerKeyRotation) and where an in-progress rotation
	// advertised on some earlier connection is read back from before dialing
	// (see serverKeyCandidates). Empty disables persistence entirely —
	// candidates then reduce to just opts.Config.ServerStaticPK, and an
	// inbound key.rotate frame is logged and otherwise ignored — which
	// matches every caller in this package's test suite that predates Task 28
	// and never sets this field. cmd/cb-agent/main.go passes config.StateDir().
	StateDir string
}

// Run dials WS /api/agents/link and stays connected until ctx is cancelled,
// reconnecting with exponential backoff + jitter (1s -> 5m cap) on any
// disconnect. It returns ctx.Err() on cancellation. Backoff resets to the
// floor after a run that reached an accepted hello.ack and then stayed up
// for at least stabilityWindow (see backoffState).
func Run(ctx context.Context, opts Options) error {
	if opts.OnCapabilitiesSet == nil {
		opts.OnCapabilitiesSet = func(json.RawMessage) error { return nil }
	}
	if opts.OnUpdate == nil {
		opts.OnUpdate = func(json.RawMessage, SendUpdateStatus) error { return nil }
	}
	if opts.OnConnected == nil {
		opts.OnConnected = func() {}
	}
	if opts.OnRejected == nil {
		opts.OnRejected = func(string) {}
	}
	if opts.ReportPendingUpdateOutcome == nil {
		opts.ReportPendingUpdateOutcome = func() (string, bool) { return "", false }
	}
	if opts.ClearPendingUpdateOutcome == nil {
		opts.ClearPendingUpdateOutcome = func() {}
	}
	if opts.OnDisconnected == nil {
		opts.OnDisconnected = func(error) {}
	}
	var backoff backoffState
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		stable, err := runOnce(ctx, opts)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		delay := backoff.next(stable)
		log.Printf("link: disconnected (%v) — reconnecting in %s", err, delay)
		opts.OnDisconnected(err)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}

// serverKeyCandidates returns the ordered list of server static public keys
// (hex) this connection attempt should be willing to open a Noise IK
// handshake against: cfg.ServerStaticPK first (the fast path for the
// overwhelmingly common no-rotation-in-progress case), then — if a Task 28
// server-key rotation was ever advertised to this agent over some earlier
// connection (see the frame.TypeKeyRotate case in runOnce's frame switch) and
// durably persisted via config.SaveServerKeyRotation — its successor key too.
// Mirrors the server's own accept-either-key-during-the-overlap-window
// behavior (agent_crypto.complete_ik_handshake), just from the initiator's
// side: Noise IK's initiator has to fix one `rs` per handshake attempt, so
// where the server tries multiple *private* keys against one inbound message,
// the agent instead retries the handshake itself against each candidate
// *public* key in turn (see the dial loop in runOnce).
//
// stateDir == "" (Options.StateDir left unset — every pre-Task-28 caller in
// this package's test suite) skips the persisted-rotation lookup entirely
// and returns just cfg.ServerStaticPK, unchanged from this function's
// absence.
func serverKeyCandidates(cfg *config.Config, stateDir string) []string {
	candidates := []string{cfg.ServerStaticPK}
	if stateDir == "" {
		return candidates
	}
	rotation, err := config.LoadServerKeyRotation(stateDir)
	if err != nil {
		log.Printf("link: reading persisted server key rotation: %v", err)
		return candidates
	}
	if rotation != nil && rotation.SuccessorPK != "" && rotation.SuccessorPK != cfg.ServerStaticPK {
		candidates = append(candidates, rotation.SuccessorPK)
	}
	return candidates
}

// dialAndHandshake dials u and completes the Noise IK handshake against
// remotePKHex, returning the live connection and initiator session on
// success. A handshake failure (ReadHandshakeMessage returning an error —
// the signal that remotePKHex was the wrong server key: the derived shared
// secret doesn't match, so msg2's AEAD payload fails to decrypt/verify)
// closes conn itself before returning, so runOnce's candidate loop can
// simply try the next key with no leaked socket. A dial failure never
// reaches that point at all — there's nothing to close.
func dialAndHandshake(
	ctx context.Context, opts Options, u string, remotePKHex string,
) (*websocket.Conn, *noiseconn.Session, error) {
	remotePub, err := hex.DecodeString(remotePKHex)
	if err != nil || len(remotePub) != 32 {
		return nil, nil, fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return nil, nil, fmt.Errorf("link: %w", err)
	}

	conn, _, err := tlsdial.NewDialer(opts.Config.TLSPin).DialContext(ctx, u, nil)
	if err != nil {
		return nil, nil, fmt.Errorf("link: dial: %w", err)
	}

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		conn.Close()
		return nil, nil, fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		conn.Close()
		return nil, nil, fmt.Errorf("link: send handshake: %w", err)
	}
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		conn.Close()
		return nil, nil, fmt.Errorf("link: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		conn.Close()
		return nil, nil, fmt.Errorf("link: %w", err)
	}
	return conn, session, nil
}

// runOnce dials, handshakes, and serves one /link connection until it drops
// or ctx is cancelled. The returned bool reports whether the connection
// reached an accepted hello.ack and then stayed up for at least
// stabilityWindow before the run ended — the signal Run uses to reset
// reconnect backoff to its floor rather than continuing an exponential
// progression from a prior run's failures. An accepted hello.ack alone is
// not sufficient: a connection that drops before the window elapses does
// not count as stable, so a flapping link keeps its backoff progression
// instead of resetting to the floor every cycle.
func runOnce(ctx context.Context, opts Options) (stable bool, err error) {
	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return false, fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	// Task 28: try every currently-trusted server key in turn (current key
	// first) rather than only ever cfg.ServerStaticPK — see
	// serverKeyCandidates' doc comment. The common case (no rotation ever
	// advertised) is exactly one candidate and behaves identically to before
	// this loop existed.
	var conn *websocket.Conn
	var session *noiseconn.Session
	for _, candidate := range serverKeyCandidates(opts.Config, opts.StateDir) {
		c, s, dialErr := dialAndHandshake(ctx, opts, u.String(), candidate)
		if dialErr != nil {
			err = dialErr
			continue
		}
		conn, session = c, s
		break
	}
	if conn == nil {
		return false, err
	}
	defer conn.Close()

	helloPayload := hostinfo.Collect(opts.AgentVersion)
	helloFrame := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC()}
	helloFrame.Payload, err = json.Marshal(helloPayload)
	if err != nil {
		return false, fmt.Errorf("link: encode hello payload: %w", err)
	}
	helloBytes, err := frame.Encode(helloFrame)
	if err != nil {
		return false, fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return false, fmt.Errorf("link: send hello: %w", err)
	}

	// opts.OnConnected fires from the hello.ack case below, once the server
	// has actually accepted this session — not here, right after the bare
	// Noise handshake. A handshake alone doesn't mean the server considers
	// the agent linked (e.g. it could still reject on device-key mismatch
	// or policy), so gating on hello.ack is the correct success signal.

	incoming := make(chan frame.Frame)
	readErrCh := make(chan error, 1)
	go func() {
		var guard inboundSeqGuard
		// inboundRekeyGen counts the server->agent cipher rekeys applied on
		// this connection. It lives in (and is only touched by) this
		// goroutine, alongside session.Decrypt/RekeyRecv — see Session's
		// goroutine-affinity note.
		var inboundRekeyGen uint64
		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				readErrCh <- err
				return
			}
			pt, err := session.Decrypt(ct)
			if err != nil {
				readErrCh <- err
				return
			}
			f, err := frame.Decode(pt)
			if err != nil {
				readErrCh <- err
				return
			}
			if err := guard.validate(f); err != nil {
				// Security-relevant rejection: replayed/decreasing sequence,
				// unsupported version, or a malformed envelope. Drop the
				// frame and keep the connection alive rather than tearing
				// down the whole link over one bad server frame. Note this
				// runs *before* the transport.rekey handling below on
				// purpose: a replayed rekey announcement must not be able to
				// push our receive cipher a generation ahead of the server's
				// send cipher.
				log.Printf("link: rejecting inbound frame: %v", err)
				continue
			}
			if f.Type == frame.TypeTransportRekey {
				// Handled here rather than in the main select loop below
				// because the swap has to happen before the *next*
				// conn.ReadMessage/Decrypt: every frame the server sends
				// after this one is sealed under the new key. Handing it to
				// the main loop would let this goroutine race ahead and
				// decrypt the following frame with the stale key.
				if err := applyInboundRekey(session, f, &inboundRekeyGen); err != nil {
					readErrCh <- err
					return
				}
				continue
			}
			select {
			case incoming <- f:
			case <-ctx.Done():
				return
			}
		}
	}()

	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()
	rekeyTicker := time.NewTicker(rekeyInterval)
	defer rekeyTicker.Stop()
	var seq uint64
	// outboundRekeyGen counts the agent->server cipher rekeys announced on
	// this connection. It resets per connection because each reconnect
	// performs a fresh Noise handshake, giving both sides fresh split keys.
	var outboundRekeyGen uint64
	var connectedFired bool
	// stableC fires once the connection has stayed up for stabilityWindow
	// past its first accepted hello.ack. It starts nil (blocks forever in
	// the select below) until that hello.ack arrives; a nil channel there
	// is safe and never selects.
	var stableC <-chan time.Time

	sendHeartbeat := func() error {
		seq++
		hb := frame.Frame{V: 1, Type: frame.TypeHeartbeat, Seq: seq, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
		data, err := frame.Encode(hb)
		if err != nil {
			return err
		}
		return conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data))
	}

	// sendRekey announces and then applies one agent->server cipher rekey.
	// The announcement must go out under the *old* key — otherwise the server
	// cannot decrypt the frame that tells it to rekey — so the Encrypt call
	// strictly precedes session.RekeySend(). Both run on this goroutine,
	// which is the sole owner of the send cipher.
	sendRekey := func() error {
		outboundRekeyGen++
		payload, err := json.Marshal(frame.TransportRekeyPayload{
			Direction:  rekeyDirectionOutbound,
			Generation: outboundRekeyGen,
		})
		if err != nil {
			return fmt.Errorf("link: encode transport.rekey payload: %w", err)
		}
		seq++
		rekeyFrame := frame.Frame{
			V:       frame.FrameVersion,
			Type:    frame.TypeTransportRekey,
			Seq:     seq,
			TS:      time.Now().UTC(),
			Payload: payload,
		}
		data, err := frame.Encode(rekeyFrame)
		if err != nil {
			return err
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data)); err != nil {
			return fmt.Errorf("link: send transport.rekey: %w", err)
		}
		session.RekeySend()
		// Diagnostic only — no key material, just a generation counter — but
		// deliberately present (not gated behind a debug flag) since it is
		// the only externally-observable signal that a rekey happened at
		// all, which the Docker E2E harness (apps/agent/e2e) greps for.
		log.Printf("link: performed outbound transport.rekey (generation %d)", outboundRekeyGen)
		return nil
	}

	// sendUpdateStatus encodes and sends one `update.status` frame (Task 24)
	// over this connection — see the SendUpdateStatus type doc comment.
	// Passed to opts.OnUpdate (for started/failed/succeeded, all sent while
	// this same connection is still live) and used directly below for the
	// rolled_back report on connect.
	sendUpdateStatus := func(version, phase, errMsg string) error {
		payload, err := json.Marshal(frame.UpdateStatusPayload{
			Version: version, Phase: phase, Error: errMsg,
		})
		if err != nil {
			return fmt.Errorf("link: encode update.status payload: %w", err)
		}
		seq++
		statusFrame := frame.Frame{
			V:       frame.FrameVersion,
			Type:    frame.TypeUpdateStatus,
			Seq:     seq,
			TS:      time.Now().UTC(),
			Payload: payload,
		}
		data, err := frame.Encode(statusFrame)
		if err != nil {
			return err
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data)); err != nil {
			return fmt.Errorf("link: send update.status: %w", err)
		}
		return nil
	}

	// sender wires the spool into this connection's outbound data-frame
	// flow (never heartbeat/control traffic — see Options.Spool/DataFrames
	// and dataFrameSender's doc comment). opts.Spool/OnSpoolStats are nil in
	// today's daemon config (no producer exists yet), which newDataFrameSender
	// and dataFrameSender both handle as "spooling disabled".
	sendDataFrame := func(f frame.Frame) error {
		data, err := frame.Encode(f)
		if err != nil {
			return err
		}
		return conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data))
	}
	sender := newDataFrameSender(opts.Spool, sendDataFrame, opts.OnSpoolStats)

	for {
		select {
		case <-ctx.Done():
			return stable, ctx.Err()
		case err := <-readErrCh:
			return stable, fmt.Errorf("link: connection lost: %w", err)
		case f := <-opts.DataFrames:
			seq++
			f.V = frame.FrameVersion
			f.Seq = seq
			f.TS = time.Now().UTC()
			if err := sender.sendLive(f); err != nil {
				return stable, err
			}
		case f := <-incoming:
			switch f.Type {
			case frame.TypeHelloAck:
				var ack frame.HelloAckPayload
				if err := json.Unmarshal(f.Payload, &ack); err != nil {
					log.Printf("link: malformed hello.ack payload: %v", err)
					continue
				}
				if !ack.Accepted {
					log.Printf("link: hello.ack rejected: %s", ack.Reason)
					opts.OnRejected(ack.Reason)
					continue
				}
				// The server accepted this session — fire OnConnected and
				// start the stability-window timer exactly once per
				// connection, even though the server may re-send hello.ack
				// later (e.g. to push a refreshed capabilities set). stable
				// only flips true if the connection is still up when
				// stableC fires below; a drop before then leaves it false.
				if !connectedFired {
					connectedFired = true
					opts.OnConnected()
					stableC = time.After(stabilityWindow)
					// Task 24: report an update outcome a previous process
					// couldn't send live (the rollback case — see
					// ReportPendingUpdateOutcome's doc comment) now that this
					// connection actually has an accepted hello.ack. Only
					// cleared on a successful send; a failed send (e.g. this
					// connection drops immediately after) leaves it for the
					// next reconnect to retry. Nil-guarded (rather than
					// relying solely on Run's defaulting) since some tests
					// call runOnce directly without going through Run.
					if opts.ReportPendingUpdateOutcome != nil {
						if version, ok := opts.ReportPendingUpdateOutcome(); ok {
							if err := sendUpdateStatus(version, "rolled_back", ""); err != nil {
								log.Printf("link: send rolled_back update.status: %v", err)
							} else if opts.ClearPendingUpdateOutcome != nil {
								opts.ClearPendingUpdateOutcome()
							}
						}
					}
				}
			case frame.TypePing:
				if err := sendHeartbeat(); err != nil {
					return stable, err
				}
			case frame.TypeDisconnect:
				return stable, errors.New("link: server requested disconnect")
			case frame.TypeCapabilitiesSet:
				if err := opts.OnCapabilitiesSet(f.Payload); err != nil {
					log.Printf("link: applying capabilities.set: %v", err)
				}
			case frame.TypeUpdate:
				if err := opts.OnUpdate(f.Payload, sendUpdateStatus); err != nil {
					log.Printf("link: update failed: %v", err)
				}
			case frame.TypeKeyRotate:
				handleKeyRotate(opts, f.Payload)
			}
		case <-ticker.C:
			if err := sendHeartbeat(); err != nil {
				return stable, err
			}
		case <-rekeyTicker.C:
			if err := sendRekey(); err != nil {
				return stable, err
			}
		case <-stableC:
			// The connection has stayed up for stabilityWindow since its
			// first accepted hello.ack — reset backoff to the floor on the
			// next reconnect. stableC only ever fires once (time.After),
			// so no need to clear it back to nil afterward.
			stable = true
		}
	}
}

// handleKeyRotate processes one inbound `key.rotate` frame (Task 28's
// server -> agent direction, kind="server" — see
// frame.KeyRotatePayload's doc comment; kind="device" is Task 27's own
// direction/mechanism and is not something the server ever sends, so it's
// logged and ignored here rather than acted on). Durably persists the
// successor server public key via config.SaveServerKeyRotation so
// serverKeyCandidates picks it up on every future connection attempt,
// including across a restart — from that point on this agent trusts EITHER
// the config file's current ServerStaticPK or this successor key, exactly
// mirroring the server's own accept-either-key-during-the-overlap-window
// behavior. Malformed payloads and persistence failures are logged, never
// fatal to the connection — the same tolerance-of-bad-control-frames stance
// capabilities.set/update already take in the switch above.
func handleKeyRotate(opts Options, payload json.RawMessage) {
	var rotate frame.KeyRotatePayload
	if err := json.Unmarshal(payload, &rotate); err != nil {
		log.Printf("link: malformed key.rotate payload: %v", err)
		return
	}
	if rotate.Kind != "server" {
		log.Printf("link: ignoring key.rotate with unexpected kind %q (server -> agent is kind=server only)", rotate.Kind)
		return
	}
	if opts.StateDir == "" {
		log.Printf("link: received server-key rotation but StateDir is unset — successor key not persisted")
		return
	}
	state := config.ServerKeyRotation{SuccessorPK: rotate.SuccessorPK, Expiry: rotate.Expiry}
	if err := config.SaveServerKeyRotation(opts.StateDir, state); err != nil {
		log.Printf("link: persisting server-key rotation: %v", err)
		return
	}
	log.Printf("link: persisted successor server key from key.rotate — will be trusted alongside the current key on future connections")
}

// applyInboundRekey validates one decrypted server->agent `transport.rekey`
// announcement and, if it checks out, advances the session's receive cipher
// one generation. *gen is the count of rekeys applied so far on this
// connection and is incremented in place on success.
//
// Every failure here is fatal to the connection rather than a dropped frame.
// Once the server has rekeyed its send cipher, ignoring the announcement
// leaves the two ciphers permanently out of step, so nothing after this point
// would decrypt anyway; failing fast turns an undecryptable stream into a
// clean reconnect (which re-handshakes and resynchronizes) instead of a
// confusing decrypt-error cascade.
func applyInboundRekey(session *noiseconn.Session, f frame.Frame, gen *uint64) error {
	var payload frame.TransportRekeyPayload
	if err := json.Unmarshal(f.Payload, &payload); err != nil {
		return fmt.Errorf("link: malformed transport.rekey payload: %w", err)
	}
	if payload.Direction != rekeyDirectionOutbound {
		return fmt.Errorf("link: transport.rekey with unexpected direction %q", payload.Direction)
	}
	// Generations are strictly sequential from 1. A gap or repeat means our
	// view of the server's send cipher has diverged from the server's, which
	// the authenticated, ordered Noise transport otherwise makes impossible.
	if payload.Generation != *gen+1 {
		return fmt.Errorf(
			"link: transport.rekey generation %d, want %d", payload.Generation, *gen+1)
	}
	session.RekeyRecv()
	*gen = payload.Generation
	// Diagnostic only, mirrors sendRekey's own log line — no key material.
	log.Printf("link: applied inbound transport.rekey (generation %d)", *gen)
	return nil
}

// Uninstall performs one short-lived connection: handshake, hello, then an
// uninstall notification. It does not enter the heartbeat loop.
func Uninstall(ctx context.Context, opts Options) error {
	remotePub, err := hex.DecodeString(opts.Config.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}

	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	conn, _, err := tlsdial.NewDialer(opts.Config.TLSPin).DialContext(ctx, u.String(), nil)
	if err != nil {
		return fmt.Errorf("link: dial: %w", err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return fmt.Errorf("link: send handshake: %w", err)
	}
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("link: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return fmt.Errorf("link: %w", err)
	}

	helloPayload := hostinfo.Collect(opts.AgentVersion)
	hello := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC()}
	hello.Payload, err = json.Marshal(helloPayload)
	if err != nil {
		return fmt.Errorf("link: encode hello payload: %w", err)
	}
	helloBytes, err := frame.Encode(hello)
	if err != nil {
		return fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return fmt.Errorf("link: send hello: %w", err)
	}

	uninstallFrame := frame.Frame{V: 1, Type: frame.TypeUninstall, Seq: 1, TS: time.Now().UTC(), Payload: json.RawMessage("{}")}
	uninstallBytes, _ := frame.Encode(uninstallFrame)
	return conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(uninstallBytes))
}
