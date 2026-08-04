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
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/hostinfo"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
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

// rekeyInterval is how often each side rotates its *own* outbound Noise
// cipher (spec §3.5). The two directions are independent: the agent times its
// agent->server cipher here, the server times its server->agent cipher in
// ws_agents.py's link_stream, and neither waits on the other. A var, not a
// const, so tests can shrink it — production stays at 15 minutes.
var rekeyInterval = 15 * time.Minute

// rekeyDirectionOutbound is the only `transport.rekey` direction either side
// ever sends. `direction` is sender-relative (see frame.TransportRekeyPayload),
// so "outbound" means "the cipher I encrypt with", which the receiver matches
// to its own receive cipher. A peer has no way to rekey our send cipher, so an
// inbound frame claiming direction "inbound" is nonsense and gets rejected
// rather than guessed at.
const rekeyDirectionOutbound = "outbound"

type Options struct {
	Config            *config.Config
	Key               *enroll.DeviceKey
	AgentVersion      string
	OnCapabilitiesSet func(json.RawMessage) error
	OnUpdate          func(json.RawMessage) error
	OnConnected       func()
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
		opts.OnUpdate = func(json.RawMessage) error { return nil }
	}
	if opts.OnConnected == nil {
		opts.OnConnected = func() {}
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
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
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
	remotePub, err := hex.DecodeString(opts.Config.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return false, fmt.Errorf("link: invalid server_static_pk: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(opts.Key.Private, opts.Key.Public, remotePubArr)
	if err != nil {
		return false, fmt.Errorf("link: %w", err)
	}

	u, err := url.Parse(opts.Config.ServerURL)
	if err != nil {
		return false, fmt.Errorf("link: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/link"

	conn, _, err := tlsdial.NewDialer(opts.Config.TLSPin).DialContext(ctx, u.String(), nil)
	if err != nil {
		return false, fmt.Errorf("link: dial: %w", err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return false, fmt.Errorf("link: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return false, fmt.Errorf("link: send handshake: %w", err)
	}
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return false, fmt.Errorf("link: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return false, fmt.Errorf("link: %w", err)
	}

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
		return nil
	}

	for {
		select {
		case <-ctx.Done():
			return stable, ctx.Err()
		case err := <-readErrCh:
			return stable, fmt.Errorf("link: connection lost: %w", err)
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
				if err := opts.OnUpdate(f.Payload); err != nil {
					log.Printf("link: update failed: %v", err)
				}
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
