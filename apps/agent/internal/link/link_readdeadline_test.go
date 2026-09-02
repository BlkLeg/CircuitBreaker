// apps/agent/internal/link/link_readdeadline_test.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// blackHoleServer is the harness for every test in this file: a real Noise
// responder that completes the handshake, accepts the hello, and then goes
// permanently silent while *still draining* everything the agent writes.
//
// The draining is the whole point. It reproduces a black-hole partition —
// `docker network disconnect`, a firewall DROP, a stale NAT entry — from
// the agent's side of the socket, which is not the same thing as a closed
// connection: no FIN or RST ever arrives, so `conn.WriteMessage` keeps
// returning nil into a void and the only evidence anything is wrong is the
// silence coming back. A test server that simply stopped reading would
// eventually fill the send buffer and surface a *write* error instead,
// which is the failure mode the agent already handled.
//
// pingEvery > 0 makes the server break its silence on that cadence with a
// `ping` frame, which is what the real backend does every 20s
// (ws_agents.py's _LINK_PING_INTERVAL_SECONDS) — the healthy case that must
// NOT be torn down.
type blackHoleServer struct {
	url       string
	serverPub [32]byte

	connections atomic.Int32
	// acceptOnlyFirst makes every connection after the first close
	// immediately, without a handshake — so a test can pin what the agent
	// does *after* a partition without the reconnect succeeding and
	// resetting the state under assertion.
	acceptOnlyFirst bool
}

func newBlackHoleServer(t *testing.T, pingEvery time.Duration, acceptOnlyFirst bool) *blackHoleServer {
	t.Helper()
	serverPriv, serverPub := generateTestKeypair(t)
	s := &blackHoleServer{serverPub: serverPub, acceptOnlyFirst: acceptOnlyFirst}

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		if s.connections.Add(1) > 1 && s.acceptOnlyFirst {
			return
		}

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		if _, _, err := conn.ReadMessage(); err != nil { // the hello
			return
		}
		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		// Drain forever so the agent's writes never fail, and — unless this
		// server was asked to ping — send nothing more.
		done := make(chan struct{})
		go func() {
			defer close(done)
			for {
				if _, _, err := conn.ReadMessage(); err != nil {
					return
				}
			}
		}()
		if pingEvery <= 0 {
			<-done
			return
		}
		seq := uint64(1)
		ticker := time.NewTicker(pingEvery)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				ping := map[string]any{
					"v": 1, "type": "ping", "seq": seq, "ts": time.Now().UTC(),
					"payload": map[string]any{},
				}
				seq++
				pingBytes, _ := json.Marshal(ping)
				if err := conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(pingBytes)); err != nil {
					return
				}
			}
		}
	}))
	t.Cleanup(srv.Close)
	s.url = "ws" + strings.TrimPrefix(srv.URL, "http")
	return s
}

func (s *blackHoleServer) options(t *testing.T) Options {
	t.Helper()
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	// runOnce is called directly by some tests here, bypassing Run's
	// callback defaulting, so the no-ops have to be supplied explicitly.
	return Options{
		Config: &config.Config{ServerURL: s.url, ServerStaticPK: hex.EncodeToString(s.serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnConnected:       func() {},
		OnRejected:        func(string) {},
		OnCapabilitiesSet: func(json.RawMessage) error { return nil },
		OnUpdate:          func(json.RawMessage, SendUpdateStatus) error { return nil },
	}
}

// shrinkReadTimeout scales the steady-state read deadline down for a test
// and restores it afterwards, the same way the stabilityWindow and
// heartbeatInterval tests do.
func shrinkReadTimeout(t *testing.T, d time.Duration) {
	t.Helper()
	original := readTimeout
	readTimeout = d
	t.Cleanup(func() { readTimeout = original })
}

// TestRunOnce_SilentServerTripsSteadyStateReadDeadline is the F-5
// regression at the connection level: an established link whose peer has
// gone silent must be torn down on the read deadline, not held open
// forever.
//
// Before the fix runOnce had no steady-state read deadline at all, so this
// test hung until its own context expired — returning context.DeadlineExceeded
// after 3s rather than a read timeout after ~600ms.
func TestRunOnce_SilentServerTripsSteadyStateReadDeadline(t *testing.T) {
	shrinkReadTimeout(t, 400*time.Millisecond)
	srv := newBlackHoleServer(t, 0, false)

	// The context is the safety net, not the mechanism: it is deliberately
	// several multiples of readTimeout so that "runOnce returned" can only
	// mean the deadline fired.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	start := time.Now()
	_, err := runOnce(ctx, srv.options(t))
	elapsed := time.Since(start)

	if !errors.Is(err, errReadTimeout) {
		t.Fatalf("runOnce err = %v, want it to wrap errReadTimeout", err)
	}
	if errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("runOnce hung until the context expired — the read deadline never fired")
	}
	if elapsed > 3*time.Second {
		t.Errorf("runOnce took %s to notice a silent peer, want ~%s", elapsed, readTimeout)
	}
}

// TestRunOnce_InboundFramesRefreshTheReadDeadline is the other half of the
// contract: the deadline is per-read, refreshed by any inbound frame, so a
// healthy connection that is merely idle of *application* traffic is never
// torn down. The real backend guarantees this by sending a `ping` every 20s
// (ws_agents.py's _LINK_PING_INTERVAL_SECONDS), which is exactly what this
// server does on a scaled-down cadence.
//
// Without the refresh, a fixed deadline set once at connect would kill this
// connection at readTimeout regardless of the pings.
func TestRunOnce_InboundFramesRefreshTheReadDeadline(t *testing.T) {
	shrinkReadTimeout(t, 400*time.Millisecond)
	originalInterval := heartbeatInterval
	heartbeatInterval = 10 * time.Second // keep agent-side chatter out of this
	defer func() { heartbeatInterval = originalInterval }()

	// One ping per third of the deadline, for ~5 deadlines' worth of time.
	srv := newBlackHoleServer(t, 130*time.Millisecond, false)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	_, err := runOnce(ctx, srv.options(t))

	if errors.Is(err, errReadTimeout) {
		t.Fatalf("runOnce tore down a connection that was receiving pings every %s "+
			"with a %s deadline — the deadline is not being refreshed per read", 130*time.Millisecond, readTimeout)
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("runOnce err = %v, want context.DeadlineExceeded (the connection should have "+
			"survived until the test cancelled it)", err)
	}
}

// TestRun_BlackHolePartitionSpoolsSubsequentDataFrames is the F-5
// regression at the level the follow-up actually describes: during a
// black-hole partition the agent must stop believing the link is up and
// start spooling, so an outage's samples survive to be delivered on
// reconnect instead of being written into the void.
//
// The server accepts exactly one connection; after the deadline tears it
// down, every redial is refused, so the agent stays disconnected and every
// data frame pushed from then on has nowhere to go but the spool.
//
// Before the fix this asserted zero: Run's `live` flag stayed true forever
// because no send ever failed, so DataFrames were routed straight into the
// dead socket and the spool was never touched.
func TestRun_BlackHolePartitionSpoolsSubsequentDataFrames(t *testing.T) {
	shrinkReadTimeout(t, 400*time.Millisecond)
	srv := newBlackHoleServer(t, 0, true)

	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}

	dataFrames := make(chan frame.Frame, 8)
	var connected sync.WaitGroup
	connected.Add(1)
	var onConnectedOnce sync.Once
	disconnected := make(chan struct{})
	var onDisconnectedOnce sync.Once

	opts := srv.options(t)
	opts.Spool = sp
	opts.DataFrames = dataFrames
	opts.OnConnected = func() { onConnectedOnce.Do(connected.Done) }
	opts.OnDisconnected = func(error) { onDisconnectedOnce.Do(func() { close(disconnected) }) }

	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	connected.Wait()

	select {
	case <-disconnected:
	case <-time.After(3 * time.Second):
		cancel()
		<-done
		t.Fatal("the link never dropped despite a silent peer — a black-hole partition went undetected")
	}

	// Collected during the partition: with the link correctly down these
	// must land in the spool rather than in the void.
	for i := 0; i < 3; i++ {
		dataFrames <- frame.Frame{Type: fakeDataFrameType, Payload: json.RawMessage(`{}`)}
	}

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && sp.Len() < 3 {
		time.Sleep(20 * time.Millisecond)
	}
	got := sp.Len()
	cancel()
	<-done

	if got < 3 {
		t.Errorf("spool Len() = %d after a partition, want 3 — frames collected during a "+
			"black-hole partition were dropped instead of spooled", got)
	}
}

// TestDialAndHandshake_SilentServerTripsHandshakeReadDeadline covers the
// same defect one step earlier. A partition that lands between the TCP
// connect and the server's handshake response left dialAndHandshake blocked
// in ReadMessage with no deadline and no ctx wiring — which hangs runOnce,
// and with it Run's whole reconnect loop, permanently. Nothing recovers
// from that: not backoff, not ctx cancellation, not shutdown.
func TestDialAndHandshake_SilentServerTripsHandshakeReadDeadline(t *testing.T) {
	original := handshakeTimeout
	handshakeTimeout = 300 * time.Millisecond
	defer func() { handshakeTimeout = original }()

	_, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		// Read the agent's handshake message and never answer it.
		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}
		time.Sleep(5 * time.Second)
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
	}

	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()

	start := time.Now()
	_, _, _, err = dialAndHandshake(ctx, opts, wsURL, hex.EncodeToString(serverPub[:]))
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("dialAndHandshake() succeeded against a server that never responded")
	}
	if elapsed > 2*time.Second {
		t.Errorf("dialAndHandshake blocked for %s on a silent server, want ~%s", elapsed, handshakeTimeout)
	}
}
