// apps/agent/internal/link/link.go
package link

import (
	"context"
	"crypto/tls"
	"crypto/x509"
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
// inbound frame before the agent treats the link as down. A severed network is
// not always a closed socket — `docker network disconnect`, a firewall DROP
// rule and a stale NAT entry all produce a black hole where no FIN or RST ever
// arrives and `conn.WriteMessage` keeps returning nil — so a silent peer must
// count as a disconnect, which is what hands the outage to the spool.
//
// Must stay equal to the backend's _LINK_DEAD_SECONDS (ws_agents.py) so both
// sides declare each other dead on the same schedule. Safe to be this strict
// because the backend pings every 20s regardless; the deadline is refreshed
// per read. A var, not a const, so tests can shrink it.
var readTimeout = 3 * heartbeatInterval

// handshakeTimeout bounds the one read in dialAndHandshake that waits for the
// server's Noise handshake response. dialAndHandshake's ctx reaches the dialer
// but not gorilla's blocking ReadMessage, so without this deadline a partition
// landing between the TCP connect and that response parks Run's entire retry
// loop in one call — unrecoverable by backoff, cancellation or shutdown.
// Mirrors the server's _HANDSHAKE_TIMEOUT_SECONDS. A var so tests can shrink it.
var handshakeTimeout = 10 * time.Second

// errReadTimeout is what a tripped readTimeout surfaces as. It is a sentinel
// rather than the raw network error because gorilla replaces timeout errors
// with its own unexported *netError, which does not unwrap to
// os.ErrDeadlineExceeded — so there is otherwise no reliable way to tell "the
// peer went silent" apart from any other dropped connection.
var errReadTimeout = errors.New("link: no frame from server within the read deadline")

// The paced catch-up budget for spooled data frames. runOnce drains at most
// drainFramesPerTick frames — and at most drainBytesPerTick of them — once
// every drainTickInterval, oldest first, while the connection is up and
// accepted. Being bounded is the point: draining on connect or until empty
// would let a reconnecting fleet deliver up to 64 MiB per agent at once. At
// <=40 frames/s a 24-hour backlog still clears in ~72s.
//
// Vars, not consts, so tests can shrink the interval.
var (
	drainTickInterval        = 100 * time.Millisecond
	drainFramesPerTick       = 4
	drainBytesPerTick  int64 = 256 << 10
)

// helloAckTimeout bounds the wait between a completed Noise handshake and an
// accepted hello.ack. Without it that wait inherits readTimeout's sixty
// seconds, because the handshake deadline is cleared once Noise completes, so
// a server stalling on a cold connection pool — what a server does in the
// seconds after a restart — costs a full minute and advances the backoff.
//
// 15s rather than the 10s handshake budget: once TLS and Noise are done,
// hello.ack is a handful of queries. A var so tests can shrink it.
var helloAckTimeout = 15 * time.Second

// rekeyIntervalEnvOverride is a test-only escape hatch: set to a positive
// integer number of seconds, it replaces the production 15-minute
// rekeyInterval, so the Docker E2E harness can exercise a real Noise rekey
// cycle without waiting out 15 real minutes. No production deployment path —
// install script, systemd unit, documented config — sets it, and unset it
// leaves the 15-minute default untouched, which is what production requires.
const rekeyIntervalEnvOverride = "CB_AGENT_TEST_REKEY_INTERVAL_SECONDS"

// resolveRekeyInterval reads rekeyIntervalEnvOverride and returns the interval
// rekeyInterval should start at. Split out from the var initializer so a unit
// test can call it directly (via t.Setenv) without depending on process-startup
// timing.
func resolveRekeyInterval() time.Duration {
	if v := os.Getenv(rekeyIntervalEnvOverride); v != "" {
		if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
			return time.Duration(secs) * time.Second
		}
	}
	return 15 * time.Minute
}

// rekeyInterval is how often each side rotates its *own* outbound Noise cipher.
// The two directions are independent: the agent times its agent->server cipher
// here, the server times its server->agent cipher in ws_agents.py's
// link_stream, and neither waits on the other. A var so tests can shrink it,
// in-process or via rekeyIntervalEnvOverride; production stays at 15 minutes.
var rekeyInterval = resolveRekeyInterval()

// rekeyDirectionOutbound is the only `transport.rekey` direction either side
// ever sends. `direction` is sender-relative (see frame.TransportRekeyPayload),
// so "outbound" means "the cipher I encrypt with", which the receiver matches
// to its own receive cipher. A peer has no way to rekey our send cipher, so an
// inbound frame claiming direction "inbound" is nonsense and gets rejected
// rather than guessed at.
const rekeyDirectionOutbound = "outbound"

// UpdateStatusEvent is one self-update transition (`update.status`) queued by
// the daemon's update worker for the event loop to transmit. ErrMsg is only
// meaningful alongside phase "failed".
//
// A channel value rather than a callback, so the producer stays decoupled from
// the connection that sends it: a callback would hand the worker a websocket
// writer it is forbidden to touch (see Options.UpdateStatusFrames).
type UpdateStatusEvent struct {
	Version string
	Phase   string
	ErrMsg  string
}

type Options struct {
	Config            *config.Config
	Key               *enroll.DeviceKey
	AgentVersion      string
	OnCapabilitiesSet func(json.RawMessage) error
	// Every On* handler below is called from runOnce's inbound switch, which
	// shares this connection's one goroutine with the websocket writer and the
	// heartbeat, rekey and spool-drain tickers. They must therefore validate and
	// enqueue only: work performed inline stalls heartbeats past the server's
	// 60s dead-link deadline and tears down the very link the result has to
	// travel back over. A returned error is logged and never ends the
	// connection, because each runtime reports its own refusal to the server.

	// OnProbeAssign and OnProbeCancel receive one raw server -> agent
	// `probe.assign` / `probe.cancel` payload each.
	// internal/collect/probe's Runtime.Assign/Runtime.Cancel are the
	// enqueue-only implementation; a refused assignment comes back to the
	// server as a `probe.result` from the runtime itself.
	OnProbeAssign func(json.RawMessage) error
	OnProbeCancel func(json.RawMessage) error
	// OnDiscoveryRequest and OnDiscoveryCancel are the same contract for the
	// `discovery.request` / `discovery.cancel` payloads.
	// internal/collect/discover's Runtime.Request/Runtime.Cancel are the
	// enqueue-only implementation; a refused dispatch comes back as a terminal
	// `discovery.finding` summary, and that summary is what closes the scan job.
	OnDiscoveryRequest func(json.RawMessage) error
	OnDiscoveryCancel  func(json.RawMessage) error
	// OnUpdate validates one `update` instruction and enqueues it for the
	// daemon's serialized update worker. Inline execution is especially
	// forbidden here: a download takes up to downloadTimeout — two minutes —
	// and would also stop the reader consuming the socket.
	//
	// A non-nil return means the instruction was not accepted — malformed
	// payload, queue full because an update is already queued or running, or
	// the worker shutting down — and runOnce reports that to the server as an
	// explicit failed `update.status` so a refusal is never silently dropped.
	OnUpdate func(payload json.RawMessage) error
	// UpdateStatusFrames carries the update worker's `update.status` reports to
	// whatever runOnce is currently serving. The worker sends; the event loop is
	// the sole receiver and sole websocket writer, which is what keeps gorilla's
	// one-writer invariant and sequence-number ownership intact.
	//
	// Delivery is best-effort by design — durability comes from the worker
	// persisting a pending-outcome record for the next process to replay
	// (internal/update's WritePendingOutcome), so a lost event costs promptness,
	// never correctness. The daemon's buffer (updateStatusQueueDepth) fits one
	// update's started+terminal pair so the worker never blocks. A nil channel
	// never selects, which the one-shot Uninstall connection relies on.
	UpdateStatusFrames <-chan UpdateStatusEvent
	OnConnected        func()
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
	// fires) for an update outcome a *previous* process couldn't report live:
	// a rollback (internal/update's WriteRollbackReport), or a succeeded
	// update whose live send was lost to a connection drop immediately before
	// re-exec (internal/update's WritePendingOutcome). phase is whichever
	// terminal phase that record carries, "rolled_back" or "succeeded". ok is
	// false when there is nothing pending, the overwhelmingly common case.
	ReportPendingUpdateOutcome func() (version, phase string, ok bool)
	// ClearPendingUpdateOutcome is called after ReportPendingUpdateOutcome's
	// report has actually been sent (sendUpdateStatus returned no error), so
	// it isn't repeated on the next reconnect. Never called otherwise — a
	// send that failed (e.g. the connection dropped immediately after
	// hello.ack) leaves the report in place for the next reconnect to retry.
	ClearPendingUpdateOutcome func()

	// Spool durably buffers outbound *data* frames (never heartbeat/control
	// traffic — frame.IsDataFrame draws that line). Every data frame is fsync'd
	// here before it can reach a socket and leaves only when the server
	// acknowledges it (see dataFrameSender in outbound.go).
	//
	// Nil disables spooling and every drain path is nil-safe for that case, but it
	// also means no durability guarantee at all: the daemon always configures one.
	Spool *spool.Spool

	// DataFrames is where producers outside this package — the host telemetry,
	// probe and discovery collectors — send outbound data frames to transmit.
	//
	// With a Spool configured, Run consumes this channel on its own goroutine and
	// enqueues everything; runOnce never reads it and the drain ticker is the sole
	// outbound path. Without one, runOnce reads it and sends live (sendLive).
	//
	// runOnce assigns V/Seq before sending, so a resend is re-stamped with this
	// connection's seq. TS is deliberately not assigned there — an observation's
	// timestamp is fixed at enqueue, so a sample recovered from an hours-old
	// backlog keeps the instant it was taken.
	//
	// A nil channel never selects, which the one-shot Uninstall connection relies on.
	DataFrames <-chan frame.Frame
	// ControlFrames carries ephemeral producer control reports such as
	// capability.readiness. They are sent only while connected and never spooled.
	ControlFrames <-chan frame.Frame

	// OnSpoolStats fires after every spool mutation (a live-send failure
	// enqueues, or a drain succeeds or fails-and-re-enqueues) with the
	// spool's resulting depth and size in bytes, so callers can mirror it
	// into e.g. status.Writer.SetSpoolStats. May be nil.
	OnSpoolStats func(depth int, bytes int64)

	// StateDir is where a `key.rotate` (kind="server") frame's successor server
	// public key is durably persisted (see config.SaveServerKeyRotation) and
	// where an in-progress rotation advertised on an earlier connection is read
	// back from before dialing (see serverKeyCandidates). Empty disables
	// persistence entirely — candidates reduce to just
	// opts.Config.ServerStaticPK and an inbound key.rotate frame is logged and
	// ignored — which is what this package's tests rely on.
	// cmd/cb-agent/main.go passes config.StateDir().
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
		opts.OnUpdate = func(json.RawMessage) error { return nil }
	}
	if opts.OnConnected == nil {
		opts.OnConnected = func() {}
	}
	if opts.OnRejected == nil {
		opts.OnRejected = func(string) {}
	}
	if opts.ReportPendingUpdateOutcome == nil {
		opts.ReportPendingUpdateOutcome = func() (string, string, bool) { return "", "", false }
	}
	if opts.ClearPendingUpdateOutcome == nil {
		opts.ClearPendingUpdateOutcome = func() {}
	}
	if opts.OnDisconnected == nil {
		opts.OnDisconnected = func(error) {}
	}
	// Every data frame is durably spooled *before* it can reach a socket, and
	// leaves the spool only when the server acknowledges it. There must be no
	// second, "live" route past the disk: `conn.WriteMessage` returning nil
	// means the local kernel took the bytes, not that the server read them, so
	// anything handed straight to a socket is lost outright if that socket
	// turns out to be black-holed.
	//
	// The cost is one drain tick — at most 100ms — on a 30s telemetry cadence,
	// and during a backlog the newest sample queues behind it rather than
	// jumping it. That ordering is the honest one: a fresh sample landing in
	// the middle of an hours-long hole reads as current while the history is
	// still missing.
	originalData := opts.DataFrames
	if originalData != nil && opts.Spool != nil {
		// runOnce's DataFrames arm never selects on a nil channel, which is
		// how the drain ticker becomes the only outbound data path for every
		// link that has a spool — i.e. every link the daemon builds.
		opts.DataFrames = nil
		go func() {
			for {
				select {
				case <-ctx.Done():
					return
				case f := <-originalData:
					if !frame.IsDataFrame(f.Type) {
						// Same invariant sendLive panics on, but this
						// goroutine outlives any one connection and must not
						// take the process down with it.
						log.Printf("link: refusing to spool non-data frame type %q", f.Type)
						continue
					}
					stamped := stampObserved(f)
					if err := opts.Spool.Enqueue(stamped); err != nil {
						// The observation is gone: the spool is the only
						// route to the wire, so a refused write — full
						// disk, read-only /var, a vanished state directory
						// — is the end of it.
						//
						// Deliberately not sent live as a fallback. A live
						// send would jump the backlog and commit the moment
						// the socket took it, making the delivery guarantee
						// conditional on a state nothing else can observe.
						// It is counted instead, into the same permanent
						// record eviction writes to, which the fleet view
						// and the Telemetry tab already read. A loss that
						// is real but invisible is what this design forbids.
						log.Printf("link: spooling outbound data frame: %v", err)
						// The error, not just "write failed": this string is
						// what `cb-agent status` prints back as the cause,
						// and "read-only file system" or "no space left on
						// device" is the whole answer an operator needs.
						opts.Spool.RecordDestroyed(stamped, fmt.Sprintf("spool write failed: %v", err))
						if opts.OnSpoolStats != nil {
							size, _ := opts.Spool.SizeBytes()
							opts.OnSpoolStats(opts.Spool.Len(), size)
						}
						continue
					}
					if opts.OnSpoolStats != nil {
						size, _ := opts.Spool.SizeBytes()
						opts.OnSpoolStats(opts.Spool.Len(), size)
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
		outcome, err := runOnce(ctx, opts)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		// runOnce only sets the class for a refusal it recognised; everything
		// else is classified here, from the one error it returned. That error
		// is the sole product of every dial, read and write path, so one call
		// covers them all.
		if outcome.class != classRefused {
			outcome.class = classifyFailure(err, outcome.reachedHelloAck)
			// A host we were talking to seconds ago is, on the balance of
			// evidence, the same host coming back — whatever the errno says.
			// Costs one 250ms attempt; the next consecutive failure falls back
			// to the real class, so it cannot become a storm. This is what
			// catches the mono image's dominant restart signature, which is
			// connection-refused rather than a clean close.
			if outcome.reachedHelloAck && outcome.class == classUnreachable {
				outcome.class = classComingBack
			}
		}
		delay := backoff.next(outcome)
		log.Printf("link: disconnected (%v) [%s] — reconnecting in %s", err, outcome.class, delay)
		opts.OnDisconnected(err)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
}

// serverKeyCandidates returns the ordered list of server static public keys
// (hex) this connection attempt should be willing to open a Noise IK handshake
// against: cfg.ServerStaticPK first (the fast path when no rotation is in
// progress), then the successor key if a server-key rotation was advertised on
// an earlier connection and persisted via config.SaveServerKeyRotation.
//
// Mirrors the server's accept-either-key-during-the-overlap-window behavior
// (agent_crypto.complete_ik_handshake) from the initiator's side. Noise IK's
// initiator has to fix one `rs` per handshake attempt, so where the server
// tries multiple *private* keys against one inbound message, the agent retries
// the handshake against each candidate *public* key in turn (see runOnce's dial
// loop).
//
// stateDir == "" skips the persisted-rotation lookup and returns just
// cfg.ServerStaticPK.
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

// peerLeafCertificate returns the leaf certificate the server presented on
// conn, or nil for a plain ws:// connection with no TLS to inspect.
//
// Read from the connection, never from the dial's *http.Response, and that
// distinction is load-bearing: gorilla builds that response by reading the
// handshake reply off the socket itself rather than going through net/http's
// transport, so `resp.TLS` is nil however the dial was made — including over
// wss. Keying promotion on it silently disables promotion entirely.
func peerLeafCertificate(conn *websocket.Conn) *x509.Certificate {
	tlsConn, ok := conn.NetConn().(*tls.Conn)
	if !ok {
		return nil
	}
	state := tlsConn.ConnectionState()
	if len(state.PeerCertificates) == 0 {
		return nil
	}
	return state.PeerCertificates[0]
}

// dialWithTrust dials u under cfg's currently resolved TLS trust policy and
// returns a promote func the caller invokes only after the peer is
// authenticated.
//
// It must not promote a successor trust policy itself: TLS success proves only
// that the peer presented an acceptable certificate, not that it is the right
// server, and PromoteTrust permanently clears the persisted rotation. The
// matched candidate is still resolved here because TLS time is the only point
// with access to the negotiated certificate.
//
// When the first dial fails it retries once under the persisted rotation, but
// only when successorRetryTrust says a cross-mode cutover was advertised — see
// its doc for why that cannot be triggered by an attacker merely causing dials
// to fail. StateDir == "" skips the retry rather than falling back to
// LoadTLSPinRotation's process-relative path, since a retry is where reading an
// attacker-planted file would matter most.
//
// On failure the returned error is always the original current-policy dial's,
// since that is what describes what the operator has to fix.
func dialWithTrust(ctx context.Context, opts Options, u string) (*websocket.Conn, func() (string, error), error) {
	trust := ResolveTrust(opts.Config, opts.StateDir)
	conn, _, dialErr := tlsdial.NewDialer(trust).DialContext(ctx, u, nil)
	if dialErr == nil {
		if leaf := peerLeafCertificate(conn); leaf != nil {
			if idx, ok := trust.Matches(leaf); ok {
				return conn, func() (string, error) {
					return PromoteTrust(opts.Config, opts.StateDir, idx)
				}, nil
			}
		}
		return conn, nil, nil
	}

	if opts.StateDir == "" {
		return nil, nil, fmt.Errorf("link: dial: %w", dialErr)
	}
	rotation, rotErr := config.LoadTLSPinRotation(opts.StateDir)
	if rotErr != nil {
		log.Printf("link: reading persisted tls pin rotation for cutover retry: %v", rotErr)
		return nil, nil, fmt.Errorf("link: dial: %w", dialErr)
	}
	retryTrust, ok := successorRetryTrust(trust, rotation)
	if !ok {
		return nil, nil, fmt.Errorf("link: dial: %w", dialErr)
	}
	retryConn, _, retryErr := tlsdial.NewDialer(retryTrust).DialContext(ctx, u, nil)
	if retryErr != nil {
		return nil, nil, fmt.Errorf("link: dial: %w", dialErr)
	}
	return retryConn, func() (string, error) {
		return PromoteTrust(opts.Config, opts.StateDir, successorRetryIndex)
	}, nil
}

// dialAndHandshake dials u and completes the Noise IK handshake against
// remotePKHex, returning the live connection, initiator session, and the
// tls_pin_kind the dial matched.
//
// It is the only caller of dialWithTrust's promote func, and invokes it only
// after ReadHandshakeMessage succeeds — promoting on TLS success and then
// failing the handshake would destroy the only record of the successor policy
// while leaving the agent unauthenticated against whatever presented that
// certificate, with the pinned update download leaving no remote path back.
//
// A handshake failure means remotePKHex was the wrong server key, so msg2's
// AEAD payload fails to verify. It closes conn before returning, letting
// runOnce's candidate loop try the next key with no leaked socket.
func dialAndHandshake(
	ctx context.Context, opts Options, u string, remotePKHex string,
) (*websocket.Conn, *noiseconn.Session, string, error) {
	remotePub, err := hex.DecodeString(remotePKHex)
	if err != nil || len(remotePub) != 32 {
		return nil, nil, "", fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return nil, nil, "", fmt.Errorf("link: %w", err)
	}

	conn, promote, err := dialWithTrust(ctx, opts, u)
	if err != nil {
		return nil, nil, "", err
	}

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		conn.Close()
		return nil, nil, "", fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		conn.Close()
		return nil, nil, "", fmt.Errorf("link: send handshake: %w", err)
	}
	// Bounded: see handshakeTimeout. Cleared before returning so the
	// steady-state loop's own per-read deadline is the only one in force on
	// an established connection.
	_ = conn.SetReadDeadline(time.Now().Add(handshakeTimeout))
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		conn.Close()
		return nil, nil, "", fmt.Errorf("link: read handshake response: %w", err)
	}
	_ = conn.SetReadDeadline(time.Time{})
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		conn.Close()
		return nil, nil, "", fmt.Errorf("link: %w", err)
	}

	tlsPinKind := ""
	if promote != nil {
		kind, promoteErr := promote()
		if promoteErr != nil {
			log.Printf("link: promoting tls trust: %v", promoteErr)
		}
		tlsPinKind = kind
	}
	// Which TLS trust policy this connection actually verified against.
	// Logged on every connection because it is the one fact an operator
	// needs while watching a certificate rotation and cannot otherwise see
	// from the agent side: "current" throughout the overlap, then
	// "successor" on the first dial after the cutover.
	log.Printf("link: tls trust matched policy %q", tlsPinKind)
	return conn, session, tlsPinKind, nil
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
func runOnce(ctx context.Context, opts Options) (outcome runOutcome, err error) {
	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return outcome, fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	// Try every currently-trusted server key in turn (current key first)
	// rather than only cfg.ServerStaticPK — see serverKeyCandidates. With no
	// rotation advertised this is exactly one candidate.
	var conn *websocket.Conn
	var session *noiseconn.Session
	var tlsPinKind string
	for _, candidate := range serverKeyCandidates(opts.Config, opts.StateDir) {
		c, s, kind, dialErr := dialAndHandshake(ctx, opts, u.String(), candidate)
		if dialErr != nil {
			err = dialErr
			continue
		}
		conn, session, tlsPinKind = c, s, kind
		break
	}
	if conn == nil {
		return outcome, err
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

	// spoolEvictions reads what the spool has permanently destroyed, in the
	// four-field wire form both hello and heartbeat carry. Nil-safe on the
	// same terms as spoolStats: a link with no spool has destroyed nothing,
	// and reports an explicit zero with null bounds rather than staying
	// silent — silence is reserved to mean "this agent predates the field".
	spoolEvictions := func() (int64, int64, *time.Time, *time.Time) {
		if opts.Spool == nil {
			return 0, 0, nil, nil
		}
		stats := opts.Spool.EvictionStats()
		return stats.Frames, stats.Bytes, optionalTime(stats.OldestDroppedTS), optionalTime(stats.NewestDroppedTS)
	}

	helloPayload := hostinfo.Collect(opts.AgentVersion, opts.Config.ServerURL)
	// The at-connect backlog snapshot. The heartbeat below reports the same
	// numbers live, which is what lets a server-side catch-up indicator clear
	// without waiting for a reconnect.
	helloPayload.SpoolDepth, _ = spoolStats()
	// What this agent has permanently destroyed while it was away. Reported
	// at connect as well as on every heartbeat because eviction happens
	// during the outage, so the reconnect is the earliest the server can
	// learn of it.
	helloPayload.SpoolEvictedFrames, helloPayload.SpoolEvictedBytes,
		helloPayload.SpoolEvictedOldestTS, helloPayload.SpoolEvictedNewestTS = spoolEvictions()
	// Which TLS trust policy this connection's own handshake matched (F4) —
	// "current", "successor", or "" for a plain ws:// dial with no
	// certificate to classify (dev/test). Reported so the server can show an
	// operator how much of the fleet has converged on an advertised
	// successor.
	helloPayload.TLSPinKind = tlsPinKind
	// Whether this agent already holds an advertised successor, which is
	// what the server's convergence view and certificate-activation gate
	// read — see SuccessorReady on why the matched kind above cannot answer
	// that before the cutover.
	helloPayload.TLSPinSuccessorReady = SuccessorReady(opts.StateDir)
	helloPayload.TLSPinSuccessorFingerprint = SuccessorFingerprint(opts.StateDir)
	// Ask this server to acknowledge data frames. It answers in
	// HelloAckPayload.DataAck, and only if it says yes does this connection
	// switch from commit-on-write to commit-on-ack — see the hello.ack arm
	// below, and dataFrameSender's doc comment for what each mode promises.
	helloPayload.AckData = true
	helloFrame := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC()}
	helloFrame.Payload, err = json.Marshal(helloPayload)
	if err != nil {
		return outcome, fmt.Errorf("link: encode hello payload: %w", err)
	}
	helloBytes, err := frame.Encode(helloFrame)
	if err != nil {
		return outcome, fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return outcome, fmt.Errorf("link: send hello: %w", err)
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
	// acceptedAt is when this connection's first accepted hello.ack arrived.
	// The retry loop uses it to measure how long the run lasted after being
	// accepted, which is what distinguishes an honest reconnect from a link
	// that is flapping. Zero until that hello.ack arrives.
	var acceptedAt time.Time
	// Measured on every exit path rather than at each return: runOnce leaves
	// through a dozen of them, and a duration that is only right on some of
	// them would make the flap floor fire arbitrarily.
	defer func() {
		if !acceptedAt.IsZero() {
			outcome.upFor = time.Since(acceptedAt)
		}
	}()

	// sendHeartbeat emits the 20s liveness frame, carrying the live spool
	// backlog. The payload must always carry both keys, zeros included: the
	// backend reserves an empty payload to mean "this agent predates spool
	// reporting" and keeps its columns NULL for it. See frame.HeartbeatPayload.
	sendHeartbeat := func() error {
		depth, bytes := spoolStats()
		evictedFrames, evictedBytes, evictedOldest, evictedNewest := spoolEvictions()
		payload, err := json.Marshal(frame.HeartbeatPayload{
			SpoolDepth: depth,
			SpoolBytes: bytes,
			// Re-asserted every interval for the same durability reason the
			// TLS pin flags below are: a single frame announcing destroyed
			// history could be lost with nothing to retry it, and the one
			// thing this record must be is trustworthy.
			SpoolEvictedFrames:   evictedFrames,
			SpoolEvictedBytes:    evictedBytes,
			SpoolEvictedOldestTS: evictedOldest,
			SpoolEvictedNewestTS: evictedNewest,
			// Re-asserted every interval so a rotation applied on a live
			// socket reaches the server without waiting for a reconnect —
			// see the field's own doc comment.
			TLSPinSuccessorReady:       SuccessorReady(opts.StateDir),
			TLSPinSuccessorFingerprint: SuccessorFingerprint(opts.StateDir),
		})
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

	// sendUpdateStatus encodes and sends one `update.status` frame over this
	// connection. Called from this goroutine only — the TypeUpdate refusal arm,
	// the UpdateStatusFrames drain arm, and the pending-outcome report on the
	// first accepted hello.ack — which is the whole one-writer story: the update
	// worker never touches the socket, it queues UpdateStatusEvent values and
	// this loop writes them. The sequence number is assigned here for the same
	// reason.
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

	// sender wires the spool into this connection's outbound data-frame flow
	// (never heartbeat/control traffic). Callers that leave opts.Spool and
	// opts.OnSpoolStats nil — Uninstall's one-shot connection, and this
	// package's tests — get spooling disabled, which every drain path handles.
	//
	// It returns the sequence number it assigned and the encoded wire size,
	// which is what the in-flight window is tracked in.
	//
	// TS is deliberately not stamped here: an observation's timestamp is fixed
	// at enqueue, so a sample recovered from an hours-old backlog keeps the
	// instant it was taken. sendLive still stamps, because the nil-spool path
	// it serves has no enqueue to do it.
	sendDataFrame := func(f frame.Frame) (uint64, int64, error) {
		seq++
		f.V = frame.FrameVersion
		f.Seq = seq
		data, err := frame.Encode(f)
		if err != nil {
			return 0, 0, err
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(data)); err != nil {
			return 0, 0, err
		}
		return seq, int64(len(data)), nil
	}
	sender := newDataFrameSender(opts.Spool, sendDataFrame, opts.OnSpoolStats)

	// Bounds the hello.ack wait. A select arm rather than a read deadline: the
	// reader's deadline has to keep refreshing on every inbound frame for the
	// steady-state case, so it cannot also express a one-shot budget.
	helloAckDeadline := time.After(helloAckTimeout)

	for {
		select {
		case <-ctx.Done():
			return outcome, ctx.Err()
		case <-helloAckDeadline:
			if !connectedFired {
				return outcome, errHelloAckTimeout
			}
		case err := <-readErrCh:
			return outcome, fmt.Errorf("link: connection lost: %w", err)
		case f := <-opts.DataFrames:
			// Only reachable for a link with no spool. Run sets this channel
			// to nil whenever Options.Spool is set — which is every link the
			// daemon builds — and a receive on a nil channel never selects,
			// so for those the drain arm below is the sole outbound data
			// path. What is left here is Uninstall's one-shot connection and
			// this package's spool-less tests, which sendLive serves with no
			// durability guarantee at all.
			if err := sender.sendLive(f); err != nil {
				return outcome, err
			}
		case <-drainTicker.C:
			// The outbound data path, paced. This is an arm of *this* select
			// and never a side goroutine: gorilla's websocket forbids
			// concurrent writers and seq above is owned by this loop. Gated
			// on connectedFired because a session the server has not accepted
			// yet has not settled the ack mode either, and must not have
			// frames committed against it.
			//
			// hasBacklog covers the in-flight window too — an unacknowledged
			// frame is still an undelivered one and still sits in the spool —
			// so the ack-stall check inside drainBurst is reachable on every
			// tick that could possibly need it.
			//
			// A send error, or a stalled ack, ends the connection. Under
			// commit-on-ack nothing has been committed, so everything written
			// on this connection is still at the head of the spool, in order,
			// for the next one.
			if !connectedFired || !sender.hasBacklog() {
				continue
			}
			if err := sender.drainBurst(drainFramesPerTick, drainBytesPerTick); err != nil {
				return outcome, err
			}
		case evt := <-opts.UpdateStatusFrames:
			// The update worker's status reports cross onto the wire here, on the
			// event-loop goroutine, so the one-writer rule and sequence ownership
			// hold. Deliberately not gated on connectedFired: hello is always the
			// first frame on every connection, so a status frame drained in the
			// pre-ack window still reaches the server after its hello and is
			// dispatched against a bound session. Dropping it until acceptance would
			// lose terminal reports far more often than the head start costs. A send
			// error is deferred, not fatal — terminal outcomes are already durable,
			// so the connection decides when runOnce ends.
			if err := sendUpdateStatus(evt.Version, evt.Phase, evt.ErrMsg); err != nil {
				log.Printf("link: send update.status(%s, %s): %v — deferred", evt.Version, evt.Phase, err)
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
				return outcome, writeErr
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
					// A refusal we understand ends the run rather than sitting
					// on a socket the server has already said no to. It carries
					// its own ladder (refusedDelay): "approve me" is worth
					// asking about often, "you are revoked" is not. A reason we
					// do not recognise falls through to waiting for the
					// server to close.
					if refusal := refusalError(ack.Reason); refusal != nil {
						outcome.class = classRefused
						outcome.refusal = refusal
						return outcome, refusal
					}
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
				// The server accepted this session — fire OnConnected exactly
				// once per connection, even though the server may re-send
				// hello.ack later (e.g. to push a refreshed capabilities set).
				// Recording the acceptance is what resets the reconnect ladder:
				// being accepted at all is the signal, not surviving some
				// arbitrary window afterwards.
				if !connectedFired {
					connectedFired = true
					outcome.reachedHelloAck = true
					acceptedAt = time.Now()
					// Settle the delivery mode before the first drain tick
					// can fire — the drain arm is gated on connectedFired
					// for exactly this reason, so no frame is ever sent
					// before the agent knows what a successful write means.
					sender.negotiateAck(ack.DataAck)
					if !ack.DataAck {
						// Once per connection, and worded as what is at
						// risk rather than as a missing feature: an
						// operator reading this needs to know their data
						// is less safe than the documentation says, not
						// that a flag came back false.
						log.Printf("link: this server does not acknowledge data frames — buffered " +
							"observations are discarded once they are written to the socket, not once " +
							"the server has stored them, so anything in flight when a connection drops " +
							"is lost. Upgrade the server to make delivery at-least-once into the database.")
					}
					opts.OnConnected()
					// Report an update outcome a previous process couldn't send live — a
					// rollback, or a succeeded update whose pre-re-exec send was lost — now
					// that this connection has an accepted hello.ack. Only cleared on a
					// successful send; a failed send leaves it for the next reconnect to
					// retry. Nil-guarded rather than relying on Run's defaulting, since some
					// tests call runOnce directly.
					if opts.ReportPendingUpdateOutcome != nil {
						if version, phase, ok := opts.ReportPendingUpdateOutcome(); ok {
							if err := sendUpdateStatus(version, phase, ""); err != nil {
								// Deferred, not lost: the record stays on disk
								// for the next accepted connection to retry.
								log.Printf("link: send %s update.status: %v — deferred to next reconnect", phase, err)
							} else if opts.ClearPendingUpdateOutcome != nil {
								opts.ClearPendingUpdateOutcome()
							}
						}
					}
				}
			case frame.TypeDataAck:
				// The server has terminally handled every frame this
				// connection sent up to this watermark, so the matching
				// prefix of the spool can finally be discarded. A malformed
				// payload is dropped rather than fatal: the frames stay in
				// flight and the next ack — or, failing that, the stall
				// timeout — decides what happens to them.
				var dataAck frame.DataAckPayload
				if err := json.Unmarshal(f.Payload, &dataAck); err != nil {
					log.Printf("link: malformed data.ack payload: %v", err)
					continue
				}
				if err := sender.onDataAck(dataAck.Seq); err != nil {
					return outcome, err
				}
			case frame.TypePing:
				if err := sendHeartbeat(); err != nil {
					return outcome, err
				}
			case frame.TypeDisconnect:
				return outcome, errors.New("link: server requested disconnect")
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
				// Enqueue-only: opts.OnUpdate validates the payload and queues it for
				// the daemon's serialized update worker, and this arm returns to the
				// select loop immediately so heartbeats, the reader and the drain
				// tickers keep running through the whole two-minute download window. A
				// refusal — malformed payload, queue full, worker shutting down — is
				// reported as an explicit failed status so the server is never left
				// waiting on an instruction that was dropped. The instruction's version
				// is echoed back when the payload carries one; "" when it is too
				// malformed to name one.
				if err := opts.OnUpdate(f.Payload); err != nil {
					log.Printf("link: update instruction refused: %v", err)
					// A duplicate of the instruction already in flight is not
					// dropped work — the server delivers every update twice by
					// design and the running attempt reports its own outcome.
					// Calling it "failed" makes the server clear
					// pending_update_version, and the successful reconnect that
					// follows then records no version_changed at all.
					if !errors.Is(err, ErrUpdateAlreadyRunning) {
						_ = sendUpdateStatus(instructionVersion(f.Payload), "failed", err.Error())
					}
				}
			case frame.TypeKeyRotate:
				handleKeyRotate(opts, f.Payload)
			case frame.TypeTLSPinRotate:
				handleTLSPinRotate(opts, f.Payload)
			}
		case <-ticker.C:
			if err := sendHeartbeat(); err != nil {
				return outcome, err
			}
		case <-rekeyTicker.C:
			if err := sendRekey(); err != nil {
				return outcome, err
			}
		}
	}
}

// instructionVersion extracts the `version` field from a raw `update`
// instruction payload, "" when the payload is too malformed to carry one.
// Used only to echo a refused instruction's target version back in the
// failed status runOnce reports when opts.OnUpdate rejects it, so the
// server's timeline names the update that was refused rather than an empty
// string whenever the payload is well-formed enough to have one. It is
// deliberately not the validation — opts.OnUpdate owns that, and a payload
// whose version this cannot read is one OnUpdate refuses anyway.
func instructionVersion(payload json.RawMessage) string {
	var instr struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(payload, &instr); err != nil {
		return ""
	}
	return instr.Version
}

// handleKeyRotate processes one inbound `key.rotate` frame in the server ->
// agent direction (kind="server"; kind="device" is the agent's own direction,
// never sent by the server, so it is logged and ignored). Persists the
// successor server public key via config.SaveServerKeyRotation so
// serverKeyCandidates picks it up on every future connection attempt,
// including across a restart: from then on the agent trusts either the config
// file's ServerStaticPK or this successor, mirroring the server's own overlap
// window. Malformed payloads and persistence failures are logged, never fatal
// — the same stance capabilities.set/update take above.
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

// handleTLSPinRotate processes one inbound `tls.pin.rotate` frame: the TLS
// trust policy this server is about to start serving, advertised ahead of
// the certificate actually changing so the agent can accept either leaf
// across the cutover. Persisted (never applied immediately) — see
// config.TLSPinRotation and ResolveTrust for why both policies stay live
// until a dial actually succeeds against the successor.
//
// Every rejection path here logs and returns rather than persisting.
// Recording a policy the agent cannot act on is strictly worse than
// ignoring the frame: the agent still reaches the server on its current
// pin, and the operator can retry the rotation.
func handleTLSPinRotate(opts Options, payload json.RawMessage) {
	var rotate frame.TLSPinRotatePayload
	if err := json.Unmarshal(payload, &rotate); err != nil {
		log.Printf("link: malformed tls.pin.rotate payload: %v", err)
		return
	}
	switch rotate.Mode {
	case tlsdial.ModeSelfSigned:
		if rotate.SuccessorPin == "" {
			log.Printf("link: ignoring tls.pin.rotate with mode=self_signed and no successor pin")
			return
		}
	case tlsdial.ModePublic:
		// A public successor carries no pin by definition.
	default:
		log.Printf("link: ignoring tls.pin.rotate with unknown mode %q", rotate.Mode)
		return
	}
	if opts.StateDir == "" {
		log.Printf("link: received tls.pin.rotate but StateDir is unset — successor policy not persisted")
		return
	}
	state := config.TLSPinRotation{
		Mode:         rotate.Mode,
		SuccessorPin: rotate.SuccessorPin,
		Expiry:       rotate.Expiry,
	}
	if err := config.SaveTLSPinRotation(opts.StateDir, state); err != nil {
		log.Printf("link: persisting tls pin rotation: %v", err)
		return
	}
	log.Printf("link: persisted successor TLS trust policy (mode=%s) from tls.pin.rotate — "+
		"both the current and successor certificates will be accepted until one is promoted",
		rotate.Mode)
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

// ErrUninstallUnconfirmed means the uninstall frame was written but the server
// never acknowledged handling it, so this agent may still be `active` on the
// server. Every "we could not confirm" outcome wraps it — a server that
// declines to acknowledge, a watermark that never reaches this frame, silence
// until the deadline — so `cb-agent uninstall` can tell that one class of
// failure (the operator has a leftover record to revoke by hand) apart from
// "we could not even reach the server".
var ErrUninstallUnconfirmed = errors.New("link: the server did not confirm the uninstall")

// uninstallFrameSeq is the sequence number the uninstall frame carries, and
// the watermark a `data.ack` has to reach before this agent may claim it was
// revoked. It is 1, not 0, because the hello is seq 0: an ack watermark of 0
// says nothing about whether the uninstall was handled.
const uninstallFrameSeq = 1

// Uninstall performs one short-lived connection: handshake, hello, the
// uninstall notification — and then waits for the server to acknowledge
// handling it before closing.
//
// The wait is the point, and removing it silently breaks uninstall. Writing
// the frame and closing immediately reports only that the local kernel took
// the bytes: uvicorn completes the close handshake the moment it arrives, so
// `ws_agents.link_stream`'s next send (the hello.ack, which follows a chunk
// of database work) fails and the handler exits before its receive loop ever
// runs. The uninstall frame is never read and the agent is never revoked,
// while `cb-agent uninstall` still reports success.
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

	helloPayload := hostinfo.Collect(opts.AgentVersion, opts.Config.ServerURL)
	// The whole basis on which this command is allowed to tell an operator the
	// server marked the agent revoked. A server that answers `data_ack: false`
	// is saying it will never acknowledge, and the wait below stops there
	// rather than sitting out the deadline.
	helloPayload.AckData = true
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

	uninstallFrame := frame.Frame{
		V: 1, Type: frame.TypeUninstall, Seq: uninstallFrameSeq,
		TS: time.Now().UTC(), Payload: json.RawMessage("{}"),
	}
	uninstallBytes, _ := frame.Encode(uninstallFrame)
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(uninstallBytes)); err != nil {
		return fmt.Errorf("link: send uninstall: %w", err)
	}

	ackErr := awaitUninstallAck(conn, session, uninstallDeadline(ctx))

	// The close goes out only now, after the wait above has ended one way or
	// the other, and this ordering is the fix. Sending it earlier is what lost
	// the frame: the server's websocket layer completes the close handshake
	// on its own schedule, and once it has, `link_stream`'s hello.ack send
	// fails and the handler leaves before reading anything this connection
	// sent. Writing a real close frame (rather than letting `defer
	// conn.Close()` fire with unread bytes still in the receive buffer, which
	// Linux answers with an RST that can discard data already handed to the
	// kernel) is still worth doing — just not until there is nothing left to
	// hear.
	_ = conn.WriteControl(
		websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
		time.Now().Add(2*time.Second),
	)
	// Whatever the server queued behind the acknowledgement, so the socket
	// closes with an empty receive buffer. Best-effort; the count is not
	// meaningful to the caller.
	drainPending(conn, time.Now().Add(2*time.Second))
	return ackErr
}

// uninstallDeadline is when the wait for an acknowledgement gives up: the
// caller's context deadline if it set one, otherwise a bounded default. An
// operator's terminal must never hang on a server that accepted the connection
// and then went quiet.
func uninstallDeadline(ctx context.Context) time.Time {
	if deadline, ok := ctx.Deadline(); ok {
		return deadline
	}
	return time.Now().Add(uninstallAckTimeout)
}

// uninstallAckTimeout bounds the wait when the caller supplied no deadline.
// `cmd/cb-agent`'s own context is shorter; this exists so a library caller
// cannot hang forever.
const uninstallAckTimeout = 15 * time.Second

// awaitUninstallAck reads until the server acknowledges handling the uninstall
// frame, and returns nil only then.
//
// Everything else on the wire is read past rather than treated as an answer:
// `hello.ack` and `capabilities.set` always arrive first, and a coalesced
// `data.ack` may legitimately carry a watermark behind this frame. Two frames
// do end the wait early, both because continuing would only burn the deadline
// to reach the same conclusion: a hello.ack that refuses the session, and one
// that says this server will not acknowledge delivery at all (`data_ack:
// false` — what a server predating the mechanism sends).
//
// An inbound `transport.rekey` is applied rather than skipped. The server
// rekeys on its own clock, that clock is configurable, and ignoring one would
// leave every later frame undecryptable — a confirmable uninstall reported as
// unconfirmed.
func awaitUninstallAck(conn *websocket.Conn, session *noiseconn.Session, deadline time.Time) error {
	var inboundRekeyGen uint64
	for {
		_ = conn.SetReadDeadline(deadline)
		_, ct, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("%w: %w", ErrUninstallUnconfirmed, classifyReadError(err))
		}
		pt, err := session.Decrypt(ct)
		if err != nil {
			return fmt.Errorf("%w: %w", ErrUninstallUnconfirmed, err)
		}
		f, err := frame.Decode(pt)
		if err != nil {
			return fmt.Errorf("%w: %w", ErrUninstallUnconfirmed, err)
		}

		switch f.Type {
		case frame.TypeTransportRekey:
			if err := applyInboundRekey(session, f, &inboundRekeyGen); err != nil {
				return fmt.Errorf("%w: %w", ErrUninstallUnconfirmed, err)
			}
		case frame.TypeHelloAck:
			var ack frame.HelloAckPayload
			if err := json.Unmarshal(f.Payload, &ack); err != nil {
				return fmt.Errorf("%w: malformed hello.ack: %w", ErrUninstallUnconfirmed, err)
			}
			if !ack.Accepted {
				reason := ack.Reason
				if reason == "" {
					reason = "no reason given"
				}
				// Wrapped like every other unconfirmed outcome: from the
				// operator's side this is the same fact — the uninstall was
				// not recorded — and the reason is what distinguishes it.
				return fmt.Errorf(
					"%w: the server refused this agent's session: %s",
					ErrUninstallUnconfirmed, reason)
			}
			if !ack.DataAck {
				return fmt.Errorf(
					"%w: this server does not acknowledge frame delivery, so the uninstall "+
						"cannot be confirmed from here", ErrUninstallUnconfirmed)
			}
		case frame.TypeDataAck:
			var ack frame.DataAckPayload
			if err := json.Unmarshal(f.Payload, &ack); err != nil {
				// Not fatal on its own: the next ack — or the deadline —
				// still decides, exactly as the daemon's own handling does.
				log.Printf("link: malformed data.ack payload: %v", err)
				continue
			}
			if ack.Seq >= uninstallFrameSeq {
				return nil
			}
		}
	}
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

// optionalTime renders a spool eviction bound for the wire: a real instant
// stays itself, and the zero value becomes an explicit JSON `null`. The
// distinction matters on the server, where the columns are nullable and a
// year-1 timestamp would persist as a genuine — and wildly wrong — claim
// about when an observation was taken.
func optionalTime(ts time.Time) *time.Time {
	if ts.IsZero() {
		return nil
	}
	utc := ts.UTC()
	return &utc
}
