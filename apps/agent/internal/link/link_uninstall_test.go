package link

import (
	"context"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
)

// TestDrainPending_ReadsMultipleQueuedMessagesNotJustTheFirst is a focused
// regression test for the bug fixed alongside Uninstall's close-handshake: a
// single ReadMessage() call only ever drained the *first* of however many
// messages the peer had queued before the deadline. drainPending must keep
// reading until nothing more arrives (an error, here the deadline), so every
// message already sitting in the local receive buffer is consumed — not just
// one — before the caller closes the connection.
func TestDrainPending_ReadsMultipleQueuedMessagesNotJustTheFirst(t *testing.T) {
	const queuedMessages = 3

	upgrader := websocket.Upgrader{}
	serverDone := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
			close(serverDone)
			return
		}
		defer conn.Close()

		// Mirrors the real /link server queuing more than one message
		// (hello.ack, then capabilities.set) before the client's
		// close-handshake even begins.
		for i := 0; i < queuedMessages; i++ {
			if err := conn.WriteMessage(websocket.BinaryMessage, []byte("queued-message")); err != nil {
				t.Errorf("write queued message %d: %v", i, err)
				close(serverDone)
				return
			}
		}
		// Deliberately never closes or sends anything further — this is
		// the production shape being guarded against: the server has no
		// reason to close first, so the client's own drain deadline (not
		// a peer close) is what has to end the loop.
		<-serverDone
	}))
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	dialer := websocket.DefaultDialer
	conn, _, err := dialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Give the server's writes time to actually land in this connection's
	// local receive buffer before draining starts, so the test isn't
	// relying on drainPending's own deadline to also cover network latency.
	time.Sleep(200 * time.Millisecond)

	got := drainPending(conn, time.Now().Add(500*time.Millisecond))
	close(serverDone)

	if got != queuedMessages {
		t.Fatalf("drainPending() drained %d message(s), want %d — it must not stop after the first",
			got, queuedMessages)
	}
}

// TestUninstall_DeliversFrameAndReturnsCleanlyWithMultiplePendingServerMessages
// exercises the full Uninstall() call path against a fake server shaped like
// the real /link server: it queues two messages (hello.ack, capabilities.set)
// before ever reading again, mirroring ws_agents.py's link_stream. Uninstall
// must still both deliver the uninstall frame and return a nil error.
func TestUninstall_DeliversFrameAndReturnsCleanlyWithMultiplePendingServerMessages(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	uninstallReceived := make(chan struct{}, 1)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Errorf("upgrade: %v", err)
			return
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("read handshake msg1: %v", err)
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			t.Errorf("responder handshake: %v", err)
			return
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, msg2); err != nil {
			t.Errorf("write handshake msg2: %v", err)
			return
		}

		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("read hello: %v", err)
			return
		}
		helloPt, err := responder.Decrypt(helloCt)
		if err != nil {
			t.Errorf("decrypt hello: %v", err)
			return
		}
		if helloFrame, err := frame.Decode(helloPt); err != nil || helloFrame.Type != frame.TypeHello {
			t.Errorf("expected a hello frame, got %+v (err=%v)", helloFrame, err)
			return
		}

		_, uninstallCt, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("read uninstall: %v", err)
			return
		}
		uninstallPt, err := responder.Decrypt(uninstallCt)
		if err != nil {
			t.Errorf("decrypt uninstall: %v", err)
			return
		}
		uninstallFrame, err := frame.Decode(uninstallPt)
		if err != nil || uninstallFrame.Type != frame.TypeUninstall {
			t.Errorf("expected an uninstall frame, got %+v (err=%v)", uninstallFrame, err)
			return
		}
		uninstallReceived <- struct{}{}

		// Two messages queued before ever reading again — the real
		// /link server's actual shape (hello.ack immediately followed by
		// capabilities.set on accept), and the specific case a single-read
		// drain used to leave half-drained.
		ackBytes, _ := frame.Encode(frame.Frame{V: 1, Type: "hello.ack", Seq: 0, TS: time.Now().UTC()})
		_ = conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(ackBytes))
		capsBytes, _ := frame.Encode(frame.Frame{V: 1, Type: "capabilities.set", Seq: 1, TS: time.Now().UTC()})
		_ = conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(capsBytes))

		// Never reads again and never closes first — Uninstall's own
		// close-handshake (write close, drain, then the real socket close)
		// is what has to end this connection.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
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

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	errCh := make(chan error, 1)
	go func() { errCh <- Uninstall(ctx, opts) }()

	select {
	case <-uninstallReceived:
	case <-time.After(3 * time.Second):
		t.Fatal("server never received an uninstall frame")
	}

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("Uninstall() error = %v, want nil", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Uninstall() did not return")
	}
}
