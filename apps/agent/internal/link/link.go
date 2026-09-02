// apps/agent/internal/link/link.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
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

// readTimeout is how long an established connection may go without a single
// inbound frame before the agent treats the link as down. It exists because
// a severed network is not always a closed socket: `docker network
// disconnect`, a firewall DROP rule and a stale NAT entry all produce a
// black hole in which no FIN or RST ever arrives, the local send buffer
// keeps accepting writes, and `conn.WriteMessage` keeps returning nil into a
// void. Without a read deadline the agent believed such a link was healthy
// indefinitely — runOnce's select loop kept writing frames that would never
// be delivered, `live` stayed true so Run routed data frames straight into
// the dead socket instead of the spool, and an entire outage's samples were
// lost rather than queued. A silent peer is now a disconnect, which is what
// hands the outage to the spool.
//
// 60s is three missed server pings, and is deliberately the same number as
// the backend's own _LINK_DEAD_SECONDS (ws_agents.py) — the two sides
// declare each other dead on the same schedule. It is safe to be this strict
// because the backend sends an application `ping` every 20s
// (_LINK_PING_INTERVAL_SECONDS) whether or not the agent is saying anything,
// so a healthy connection is never idle for a whole minute; the deadline is
// refreshed per read (see runOnce's reader goroutine), so any inbound frame
// — ping, hello.ack, capabilities.set, transport.rekey — keeps it alive.
//
// A var, not a const, so tests can shrink it; production never changes it.
var readTimeout = 3 * heartbeatInterval

// handshakeTimeout bounds the one read in dialAndHandshake that waits for
// the server's Noise handshake response. Same defect as readTimeout, one
// step earlier: a partition landing between the TCP connect and that
// response left the read blocked forever, and because dialAndHandshake's
// ctx reaches the dialer but not gorilla's blocking ReadMessage, nothing
// recovered from it — not reconnect backoff, not ctx cancellation, not
// shutdown. Run's entire retry loop would sit in that one call. Mirrors the
// server's own _HANDSHAKE_TIMEOUT_SECONDS. A var so tests can shrink it.
var handshakeTimeout = 10 * time.Second

// errReadTimeout is what a tripped readTimeout surfaces as. It is a
// sentinel rather than the raw network error because gorilla replaces
// timeout errors with its own unexported *netError, which does not unwrap
// to os.ErrDeadlineExceeded — so without this there is no reliable way for
// a caller (or a test) to tell "the peer went silent" apart from any other
// dropped connection.
var errReadTimeout = errors.New("link: no frame from server within the read deadline")

// The paced catch-up budget for spooled data frames (D-5). runOnce drains at
// most drainFramesPerTick frames — and at most drainBytesPerTick of them —
// once every drainTickInterval, from the head of the spool, while the
// connection is up and accepted. That is <=40 frames/s and <=2.5 MiB/s: a
// one-hour outage at the default 30s cadence (120 samples) clears in ~3s, a
// 24-hour outage (2,880 samples) in ~72s, and a completely full 64 MiB spool
// in under three minutes — bounded, which is the property draining on
// connect or draining until empty does not have (a fleet reconnecting after
// a backend outage would otherwise deliver up to 64 MiB per agent at once).
//
// Vars, not consts, so tests can shrink the interval; production never
// changes them.
var (
	drainTickInterval        = 100 * time.Millisecond
	drainFramesPerTick       = 4
	drainBytesPerTick  int64 = 256 << 10
)

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
	// OnProbeAssign and OnProbeCancel receive one server -> agent
	// `probe.assign` / `probe.cancel` payload each (Slice 3 §4), raw. Both are
	// called from runOnce's inbound switch, which shares this connection's one
	// goroutine with the websocket writer, the heartbeat ticker, the rekey
	// ticker and the spool-drain ticker — so both handlers must validate and
	// enqueue only. A handler that performed the probe inline would stall
	// heartbeats (20s interval) past the server's 60s dead-link deadline and
	// tear down the very link the result has to travel back over.
	// internal/collect/probe's Runtime.Assign/Runtime.Cancel are that
	// enqueue-only implementation; the returned error is logged and never
	// ends the connection, since a refused assignment is reported to the
	// server as a `probe.result` by the runtime itself.
	OnProbeAssign func(json.RawMessage) error
	OnProbeCancel func(json.RawMessage) error
	// OnDiscoveryRequest and OnDiscoveryCancel are the same contract for the
	// server -> agent `discovery.request` / `discovery.cancel` payloads (Slice
	// 4 §4), and it is the same contract for the same reason: they are called
	// from runOnce's inbound switch, on the one goroutine this connection
	// shares with the websocket writer and the heartbeat, rekey and
	// spool-drain tickers. A handler that scanned inline would stall
	// heartbeats past the server's 60s dead-link deadline and tear down the
	// link every finding has to travel back over — so both must validate and
	// enqueue only. internal/collect/discover's Runtime.Request/Runtime.Cancel
	// are that enqueue-only implementation; the returned error is logged and
	// never ends the connection, since a refused dispatch is reported to the
	// server as a terminal `discovery.finding` summary by the runtime itself,
	// and that summary is what closes the scan job.
	OnDiscoveryRequest func(json.RawMessage) error
	OnDiscoveryCancel  func(json.RawMessage) error
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
	// and is drained back out by runOnce's paced catch-up burst — at most
	// drainFramesPerTick frames per drainTickInterval, oldest first (see
	// dataFrameSender in outbound.go). The daemon has a real data-frame
	// producer today (the host telemetry collector), so this is a live path,
	// not a dormant one. Nil disables spooling entirely — e.g. Uninstall's
	// one-shot connection has no ongoing data-frame flow to buffer — and
	// every drain path is nil-safe for exactly that case.
	Spool *spool.Spool

	// DataFrames is where a producer outside this package — the host
	// telemetry collector today, probe and discovery collectors later —
	// sends outbound data frames for this link to transmit. runOnce assigns
	// V/Seq/TS itself before sending, same as it does for heartbeat/rekey
	// frames (spooled frames included: a resend is re-stamped with this
	// connection's seq). A nil channel simply never selects, which is what
	// the one-shot Uninstall connection and this package's non-data-frame
	// tests rely on.
	DataFrames <-chan frame.Frame
	// ControlFrames carries ephemeral producer control reports such as
	// capability.readiness. They are sent only while connected and never spooled.
	ControlFrames <-chan frame.Frame

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
	if opts.OnProbeAssign == nil {
		opts.OnProbeAssign = func(json.RawMessage) error { return nil }
	}
	if opts.OnProbeCancel == nil {
		opts.OnProbeCancel = func(json.RawMessage) error { return nil }
	}
	if opts.OnDiscoveryRequest == nil {
		opts.OnDiscoveryRequest = func(json.RawMessage) error { return nil }
	}
	if opts.OnDiscoveryCancel == nil {
		opts.OnDiscoveryCancel = func(json.RawMessage) error { return nil }
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
	originalData := opts.DataFrames
	routedData := make(chan frame.Frame, 1)
	var live atomic.Bool
	originalConnected := opts.OnConnected
	opts.OnConnected = func() { live.Store(true); originalConnected() }
	if originalData != nil && opts.Spool != nil {
		opts.DataFrames = routedData
		go func() {
			for {
				select {
				case <-ctx.Done():
					return
				case f := <-originalData:
					routed := false
					for live.Load() {
						select {
						case routedData <- f:
							routed = true
						case <-ctx.Done():
							return
						case <-time.After(10 * time.Millisecond):
						}
						if routed {
							break
						}
					}
					if routed {
						continue
					}
					if opts.Spool != nil && frame.IsDataFrame(f.Type) {
						if err := opts.Spool.Enqueue(f); err != nil {
							log.Printf("link: spool during disconnect: %v", err)
						}
						if opts.OnSpoolStats != nil {
							size, _ := opts.Spool.SizeBytes()
							opts.OnSpoolStats(opts.Spool.Len(), size)
						}
					}
				}
			}
		}()
	}
	var backoff backoffState
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		live.Store(false)
		stable, err := runOnce(ctx, opts)
		live.Store(false)
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

	conn, _, err := tlsdial.NewDialer(ResolveTrust(opts.Config, opts.StateDir)).DialContext(ctx, u, nil)
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
	// Bounded: see handshakeTimeout. Cleared before returning so the
	// steady-state loop's own per-read deadline is the only one in force on
	// an established connection.
	_ = conn.SetReadDeadline(time.Now().Add(handshakeTimeout))
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		conn.Close()
		return nil, nil, fmt.Errorf("link: read handshake response: %w", err)
	}
	_ = conn.SetReadDeadline(time.Time{})
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

	// spoolStats reads the outbound spool's current backlog. It is defined
	// here rather than in internal/hostinfo because the spool is owned by
	// the link (Options.Spool) — hostinfo collects *host* state and has no
	// access to it. Nil-safe: callers that leave Options.Spool nil
	// (Uninstall's one-shot connection, most of this package's tests) have
	// no backlog by definition, and report an explicit 0/0 rather than
	// nothing at all — see frame.HeartbeatPayload's doc comment for why the
	// zeros must be explicit.
	spoolStats := func() (int, int64) {
		if opts.Spool == nil {
			return 0, 0
		}
		size, err := opts.Spool.SizeBytes()
		if err != nil {
			size = 0
		}
		return opts.Spool.Len(), size
	}

	helloPayload := hostinfo.Collect(opts.AgentVersion)
	// The at-connect backlog snapshot (D-12). The heartbeat below reports
	// the same numbers live, which is what lets a server-side catch-up
	// indicator clear without waiting for a reconnect.
	helloPayload.SpoolDepth, _ = spoolStats()
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
			// Refreshed before every read, not set once at connect: any
			// inbound frame proves the path is still carrying traffic, so
			// the deadline measures silence rather than connection age.
			// This goroutine is the connection's sole reader, so it owns
			// the read deadline outright.
			_ = conn.SetReadDeadline(time.Now().Add(readTimeout))
			_, ct, err := conn.ReadMessage()
			if err != nil {
				readErrCh <- classifyReadError(err)
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
	// drainTicker paces spool catch-up. It runs on every connection, spool
	// or no spool — the select arm below is what decides there is nothing to
	// do — so the timing is identical whether or not a backlog exists.
	drainTicker := time.NewTicker(drainTickInterval)
	defer drainTicker.Stop()
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

	// sendHeartbeat emits the 20s liveness frame, carrying the live spool
	// backlog (D-12). The payload used to be a hardcoded `{}`; it now always
	// carries both keys, zeros included, because the backend reserves an
	// empty payload to mean "this agent predates spool reporting" and keeps
	// its columns NULL for it. See frame.HeartbeatPayload.
	sendHeartbeat := func() error {
		depth, bytes := spoolStats()
		payload, err := json.Marshal(frame.HeartbeatPayload{SpoolDepth: depth, SpoolBytes: bytes})
		if err != nil {
			return fmt.Errorf("link: encode heartbeat payload: %w", err)
		}
		seq++
		hb := frame.Frame{V: 1, Type: frame.TypeHeartbeat, Seq: seq, TS: time.Now().UTC(), Payload: payload}
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
	// and dataFrameSender's doc comment). The daemon sets both opts.Spool
	// and opts.OnSpoolStats; callers that leave them nil — Uninstall's
	// one-shot connection, and this package's tests — get "spooling
	// disabled", which newDataFrameSender and every drain path handle
	// explicitly.
	sendDataFrame := func(f frame.Frame) error {
		seq++
		f.V = frame.FrameVersion
		f.Seq = seq
		if f.TS.IsZero() {
			f.TS = time.Now().UTC()
		}
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
			if err := sender.sendLive(f); err != nil {
				return stable, err
			}
		case <-drainTicker.C:
			// Paced catch-up for frames spooled during an outage. This is an
			// arm of *this* select and never a side goroutine: gorilla's
			// websocket forbids concurrent writers and seq above is owned by
			// this loop. Gated on connectedFired because a session the
			// server has not accepted yet must not have frames committed
			// against it. A send error ends the connection exactly as the
			// DataFrames case does; the uncommitted remainder stays at the
			// head of the spool for the next connection.
			if !connectedFired || !sender.hasBacklog() {
				continue
			}
			if err := sender.drainBurst(drainFramesPerTick, drainBytesPerTick); err != nil {
				return stable, err
			}
		case f := <-opts.ControlFrames:
			if !connectedFired {
				continue
			}
			seq++
			f.V = frame.FrameVersion
			f.Seq = seq
			if f.TS.IsZero() {
				f.TS = time.Now().UTC()
			}
			data, encodeErr := frame.Encode(f)
			if encodeErr != nil {
				log.Printf("link: encode control frame: %v", encodeErr)
				continue
			}
			if writeErr := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data)); writeErr != nil {
				return stable, writeErr
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
				if len(ack.Capabilities) > 0 {
					payload, marshalErr := json.Marshal(ack.Capabilities)
					if marshalErr != nil {
						log.Printf("link: encode hello.ack capabilities: %v", marshalErr)
					} else if applyErr := opts.OnCapabilitiesSet(payload); applyErr != nil {
						log.Printf("link: applying hello.ack capabilities: %v", applyErr)
					}
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
			case frame.TypeProbeAssign:
				// Nil-guarded rather than relying solely on Run's defaulting:
				// several tests drive runOnce directly, same as the
				// ReportPendingUpdateOutcome call above.
				if opts.OnProbeAssign != nil {
					if err := opts.OnProbeAssign(f.Payload); err != nil {
						log.Printf("link: probe.assign refused: %v", err)
					}
				}
			case frame.TypeProbeCancel:
				if opts.OnProbeCancel != nil {
					if err := opts.OnProbeCancel(f.Payload); err != nil {
						log.Printf("link: probe.cancel: %v", err)
					}
				}
			case frame.TypeDiscoveryRequest:
				// Nil-guarded and error-logging for the same two reasons as the
				// probe arms above: runOnce is reachable without Run's
				// defaulting, and a refusal is already on its way back to the
				// server as a terminal `rejected` summary, so ending the
				// connection over it would only strand the job it just closed.
				if opts.OnDiscoveryRequest != nil {
					if err := opts.OnDiscoveryRequest(f.Payload); err != nil {
						log.Printf("link: discovery.request refused: %v", err)
					}
				}
			case frame.TypeDiscoveryCancel:
				if opts.OnDiscoveryCancel != nil {
					if err := opts.OnDiscoveryCancel(f.Payload); err != nil {
						log.Printf("link: discovery.cancel: %v", err)
					}
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

	conn, _, err := tlsdial.NewDialer(ResolveTrust(opts.Config, opts.StateDir)).DialContext(ctx, u.String(), nil)
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
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(uninstallBytes)); err != nil {
		return fmt.Errorf("link: send uninstall: %w", err)
	}

	// A bare `defer conn.Close()` firing immediately after the WriteMessage
	// above raced the server's read: WriteMessage returning nil only means
	// this frame was handed to the local TCP send buffer, not that the
	// server has read it — and if this connection's own receive buffer
	// still holds any unread bytes at the moment Close() runs (e.g. the
	// server's hello.ack, which this one-shot connection never reads),
	// Linux answers close() with an RST instead of a graceful FIN. An RST
	// can silently discard data already handed to the kernel, including the
	// uninstall frame just "sent" above — so the server could receive
	// nothing at all despite this function returning success. Sending a
	// real WS close frame and giving the peer a brief window to respond (or
	// to simply finish reading) makes an ordinary graceful close far more
	// likely than an abrupt reset.
	//
	// A single ReadMessage() here only ever drained the *first* of
	// whatever the server had queued — but the real /link server
	// (ws_agents.py's link_stream) unconditionally sends two messages on
	// accept, hello.ack then capabilities.set, before this one-shot
	// connection's close-handshake even begins, and either send caller can
	// add more before the read deadline fires. Draining just one still left
	// the second sitting unread in the local kernel receive buffer at the
	// moment Close() ran, i.e. exactly the RST-triggering condition this
	// close-handshake exists to avoid. drainPending loops until nothing
	// more is available (an error — the peer's own close, or the deadline
	// below) rather than stopping after the first message.
	_ = conn.WriteControl(
		websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
		time.Now().Add(2*time.Second),
	)
	drainPending(conn, time.Now().Add(2*time.Second)) // best-effort; count not meaningful to the caller
	return nil
}

// classifyReadError maps one error from the connection's reader onto
// errReadTimeout when — and only when — it is the readTimeout deadline
// expiring, and passes everything else (a real close, a decrypt failure, a
// reset) through untouched. The remapping exists because gorilla hides
// timeout errors behind its own unexported *netError, which does not unwrap
// to os.ErrDeadlineExceeded; matching on the net.Error interface is the only
// thing that survives that.
func classifyReadError(err error) error {
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return fmt.Errorf("%w (%s of silence): peer unreachable", errReadTimeout, readTimeout)
	}
	return err
}

// drainPending reads and discards inbound WebSocket messages on conn until
// ReadMessage returns an error — the peer's own close frame arriving, the
// given deadline elapsing, or the connection otherwise ending — and returns
// how many messages it discarded. Used by Uninstall's close-handshake (see
// its comment) to empty the local receive buffer of everything the server
// queued before this connection closes, not just the first message.
func drainPending(conn *websocket.Conn, deadline time.Time) int {
	_ = conn.SetReadDeadline(deadline)
	n := 0
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			return n
		}
		n++
	}
}
