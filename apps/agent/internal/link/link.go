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
				// down the whole link over one bad server frame.
				log.Printf("link: rejecting inbound frame: %v", err)
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
	var seq uint64
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
		case <-stableC:
			// The connection has stayed up for stabilityWindow since its
			// first accepted hello.ack — reset backoff to the floor on the
			// next reconnect. stableC only ever fires once (time.After),
			// so no need to clear it back to nil afterward.
			stable = true
		}
	}
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
