// apps/agent/internal/link/link_spool_test.go
package link

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/spool"
)

// TestRun_DataFramesFlowThroughLiveConnectionWithoutSpooling drives a full
// Run() connection — real Noise handshake, real encrypted WS frames — and
// pushes fake data frames (fakeDataFrameType — no real Slice 1 data frame
// type exists to test with) through Options.DataFrames while heartbeats keep
// ticking on their own schedule. It verifies, through the actually-wired
// path (not just a direct dataFrameSender call):
//   - live data frames reach the server over the connection;
//   - the spool stays empty throughout, since every send here succeeds —
//     spooling is a send-failure fallback, not a parallel duplicate path;
//   - heartbeat frames flow independently and never touch the spool either.
func TestRun_DataFramesFlowThroughLiveConnectionWithoutSpooling(t *testing.T) {
	originalInterval := heartbeatInterval
	heartbeatInterval = 100 * time.Millisecond
	defer func() { heartbeatInterval = originalInterval }()

	serverPriv, serverPub := generateTestKeypair(t)

	var mu sync.Mutex
	var dataFramesSeen, heartbeatsSeen int

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("upgrade: %v", err)
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Errorf("responder handshake: %v", err)
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("expected a hello frame after handshake: %v", err)
			return
		}
		if _, err := responder.Decrypt(helloCt); err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}

		ack := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		}
		ackBytes, _ := json.Marshal(ack)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := responder.Decrypt(ct)
			if err != nil {
				return
			}
			var f map[string]any
			json.Unmarshal(pt, &f)
			mu.Lock()
			switch f["type"] {
			case fakeDataFrameType:
				dataFramesSeen++
			case "heartbeat":
				heartbeatsSeen++
			}
			mu.Unlock()
		}
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dir := t.TempDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}

	sp, err := spool.Open(t.TempDir(), spool.DefaultCapBytes)
	if err != nil {
		t.Fatalf("spool.Open() error = %v", err)
	}

	dataFrames := make(chan frame.Frame, 8)
	var connected sync.WaitGroup
	connected.Add(1)
	var onConnectedOnce sync.Once

	opts := Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		Spool:      sp,
		DataFrames: dataFrames,
		OnConnected: func() {
			onConnectedOnce.Do(connected.Done)
		},
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_ = Run(ctx, opts)
		close(done)
	}()

	connected.Wait()
	for i := 0; i < 5; i++ {
		dataFrames <- frame.Frame{Type: fakeDataFrameType, Payload: json.RawMessage(`{}`)}
	}

	// Give the connection time to carry both the data frames and at least
	// one heartbeat tick before tearing down.
	time.Sleep(500 * time.Millisecond)
	cancel()
	<-done

	mu.Lock()
	defer mu.Unlock()
	if dataFramesSeen != 5 {
		t.Errorf("server saw %d data frames, want 5", dataFramesSeen)
	}
	if heartbeatsSeen == 0 {
		t.Error("server saw no heartbeat frames — heartbeat ticker should keep running independently")
	}
	if got := sp.Len(); got != 0 {
		t.Errorf("spool Len() = %d, want 0 — no send failed, so nothing should have been spooled", got)
	}
}
