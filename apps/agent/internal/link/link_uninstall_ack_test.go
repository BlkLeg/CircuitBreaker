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
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/frame"
)

// Uninstall's contract, and why it is what it is.
//
// Uninstall used to write the uninstall frame, immediately write a WebSocket
// close, and return nil — which said only that the local kernel had accepted
// the bytes. Against the real server that was reliably wrong: uvicorn
// completes the close handshake as soon as it arrives, so link_stream's very
// next send (the hello.ack, sent after a chunk of database work) raised, the
// handler exited before its receive loop ever started, and the uninstall
// frame was never read. `cb-agent uninstall` printed "Notified the server
// (agent record marked revoked)" while the agent stayed active forever.
// Reproduced end to end on 2026-09-08 against the docker harness, and proved
// by keeping the socket open instead: same run, agent revoked.
//
// So the close is no longer what ends this connection — the server's
// acknowledgement is. The hello asks for delivery acks, and Uninstall returns
// nil only once a `data.ack` watermark has reached the uninstall frame's own
// sequence number, which by then means `_handle_uninstall` has run and
// committed. Everything below pins one clause of that.

// uninstallAckServer is a fake /link server shaped like the real one:
// Noise handshake, read hello, read one frame, then whatever `respond` does
// with the connection. It reports the hello it saw and the order in which
// things happened, which is what the ordering assertions need.
type uninstallAckServer struct {
	url        string
	mu         sync.Mutex
	events     []string
	helloAck   bool // whether the hello asked for delivery acks
	frameType  string
	frameSeq   uint64
	closeSeen  chan struct{}
	frameSeen  chan struct{}
	shutdownFn func()
}

func (s *uninstallAckServer) record(event string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.events = append(s.events, event)
}

func (s *uninstallAckServer) eventLog() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.events...)
}

// newUninstallAckServer starts the fake server. `respond` is called once the
// uninstall frame has been read, with a helper that seals and sends one frame
// on the live session.
func newUninstallAckServer(
	t *testing.T,
	serverPriv, serverPub [32]byte,
	respond func(send func(f frame.Frame)),
) *uninstallAckServer {
	t.Helper()
	s := &uninstallAckServer{
		closeSeen: make(chan struct{}, 1),
		frameSeen: make(chan struct{}, 1),
	}
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
		helloFrame, err := frame.Decode(helloPt)
		if err != nil {
			t.Errorf("decode hello: %v", err)
			return
		}
		var hello frame.HelloPayload
		if err := json.Unmarshal(helloFrame.Payload, &hello); err != nil {
			t.Errorf("unmarshal hello payload: %v", err)
			return
		}

		_, ct, err := conn.ReadMessage()
		if err != nil {
			t.Errorf("read uninstall: %v", err)
			return
		}
		pt, err := responder.Decrypt(ct)
		if err != nil {
			t.Errorf("decrypt uninstall: %v", err)
			return
		}
		f, err := frame.Decode(pt)
		if err != nil {
			t.Errorf("decode uninstall: %v", err)
			return
		}

		s.mu.Lock()
		s.helloAck = hello.AckData
		s.frameType = f.Type
		s.frameSeq = f.Seq
		s.mu.Unlock()
		s.record("uninstall-received")
		s.frameSeen <- struct{}{}

		send := func(out frame.Frame) {
			encoded, err := frame.Encode(out)
			if err != nil {
				t.Errorf("encode %s: %v", out.Type, err)
				return
			}
			if err := conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(encoded)); err != nil {
				t.Errorf("write %s: %v", out.Type, err)
				return
			}
			s.record("sent-" + out.Type)
		}
		respond(send)

		// Read until the client's close arrives. The ordering assertions
		// hang on this: the close must be the *last* thing that happens.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				s.record("close-received")
				select {
				case s.closeSeen <- struct{}{}:
				default:
				}
				return
			}
		}
	}))
	s.url = "ws" + strings.TrimPrefix(srv.URL, "http")
	s.shutdownFn = srv.Close
	t.Cleanup(srv.Close)
	return s
}

func uninstallOptions(t *testing.T, serverURL string, serverPub [32]byte) Options {
	t.Helper()
	key, err := enroll.LoadOrCreateDeviceKey(t.TempDir())
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	return Options{
		Config:       &config.Config{ServerURL: serverURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:          key,
		AgentVersion: "0.1.0-test",
	}
}

func helloAckFrame(dataAck bool) frame.Frame {
	payload, _ := json.Marshal(frame.HelloAckPayload{Accepted: true, AgentID: 1, DataAck: dataAck})
	return frame.Frame{V: 1, Type: frame.TypeHelloAck, Seq: 0, TS: time.Now().UTC(), Payload: payload}
}

func dataAckFrame(seq uint64, outSeq uint64) frame.Frame {
	payload, _ := json.Marshal(frame.DataAckPayload{Seq: seq})
	return frame.Frame{V: 1, Type: frame.TypeDataAck, Seq: outSeq, TS: time.Now().UTC(), Payload: payload}
}

// The frame must ask for acknowledgement, or the server has no reason to send
// one and the wait below could never end in success.
func TestUninstall_AsksForDeliveryAcknowledgement(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		send(helloAckFrame(true))
		send(dataAckFrame(1, 1))
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub)); err != nil {
		t.Fatalf("Uninstall() error = %v, want nil", err)
	}

	srv.mu.Lock()
	defer srv.mu.Unlock()
	if !srv.helloAck {
		t.Error("hello did not set ack_data — the server will never acknowledge the uninstall")
	}
	if srv.frameType != frame.TypeUninstall {
		t.Errorf("frame type = %q, want %q", srv.frameType, frame.TypeUninstall)
	}
	if srv.frameSeq < 1 {
		t.Errorf("uninstall seq = %d, want >= 1 — seq 0 is the hello's and no watermark could distinguish it",
			srv.frameSeq)
	}
}

// The close is what used to lose the frame. It must now come last.
func TestUninstall_ClosesOnlyAfterTheServerAcknowledges(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		send(helloAckFrame(true))
		// A deliberate gap: if Uninstall closed on write success, the close
		// would land inside it and the ordering assertion below would catch
		// exactly the regression this test exists for.
		time.Sleep(300 * time.Millisecond)
		send(dataAckFrame(1, 1))
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub)); err != nil {
		t.Fatalf("Uninstall() error = %v, want nil", err)
	}

	select {
	case <-srv.closeSeen:
	case <-time.After(3 * time.Second):
		t.Fatal("the server never saw the client close")
	}

	events := srv.eventLog()
	ackAt, closeAt := -1, -1
	for i, e := range events {
		switch e {
		case "sent-" + frame.TypeDataAck:
			ackAt = i
		case "close-received":
			closeAt = i
		}
	}
	if ackAt < 0 || closeAt < 0 {
		t.Fatalf("expected both an ack and a close in %v", events)
	}
	if closeAt < ackAt {
		t.Fatalf("the connection closed before the acknowledgement arrived: %v", events)
	}
}

// Frames the server sends before the ack must not be mistaken for it, and
// must not end the wait — hello.ack and capabilities.set always arrive first.
func TestUninstall_ReadsPastHelloAckAndCapabilitiesToFindTheAck(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		send(helloAckFrame(true))
		send(frame.Frame{
			V: 1, Type: frame.TypeCapabilitiesSet, Seq: 1,
			TS: time.Now().UTC(), Payload: json.RawMessage(`{"host_telemetry":true}`),
		})
		send(dataAckFrame(1, 2))
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub)); err != nil {
		t.Fatalf("Uninstall() error = %v, want nil", err)
	}
}

// A watermark behind the uninstall frame acknowledges something else. The
// server coalesces acks, so one for an earlier frame can legitimately arrive
// on this connection; treating it as confirmation would put the old lie back.
func TestUninstall_IgnoresAnAcknowledgementBehindTheUninstallFrame(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		send(helloAckFrame(true))
		send(dataAckFrame(0, 1))
	})

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub))
	if err == nil {
		t.Fatal("Uninstall() returned nil on a watermark that never reached the uninstall frame")
	}
	if !errors.Is(err, ErrUninstallUnconfirmed) {
		t.Errorf("error = %v, want it to wrap ErrUninstallUnconfirmed", err)
	}
}

// Silence is failure, and it must not take the whole context to say so when
// the server has already told us it will never acknowledge anything.
func TestUninstall_FailsFastWhenTheServerDeclinesToAcknowledge(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		// What a server predating the data.ack mechanism sends: an accepted
		// hello.ack with no data_ack. Waiting out the full timeout for an ack
		// it will never send tells the operator nothing extra.
		send(helloAckFrame(false))
	})

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	started := time.Now()
	err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub))
	if err == nil {
		t.Fatal("Uninstall() returned nil against a server that does not acknowledge delivery")
	}
	if !errors.Is(err, ErrUninstallUnconfirmed) {
		t.Errorf("error = %v, want it to wrap ErrUninstallUnconfirmed", err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Errorf("took %s to give up on a server that said it would not acknowledge — should be immediate",
			elapsed)
	}
}

// A rejected hello is a different failure with a different remedy, and the
// operator should be told which one they have.
func TestUninstall_ReportsARejectedHello(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		payload, _ := json.Marshal(frame.HelloAckPayload{Accepted: false, Reason: "revoked"})
		send(frame.Frame{
			V: 1, Type: frame.TypeHelloAck, Seq: 0, TS: time.Now().UTC(), Payload: payload,
		})
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub))
	if err == nil {
		t.Fatal("Uninstall() returned nil against a server that refused the session")
	}
	if !strings.Contains(err.Error(), "revoked") {
		t.Errorf("error = %v, want it to carry the server's stated reason", err)
	}
}

// Silence must end at the deadline rather than hanging an operator's terminal.
func TestUninstall_GivesUpAtTheDeadlineWhenNothingIsAcknowledged(t *testing.T) {
	serverPriv, serverPub := generateTestKeypair(t)
	srv := newUninstallAckServer(t, serverPriv, serverPub, func(send func(frame.Frame)) {
		send(helloAckFrame(true))
		// Then nothing at all — a server that accepted the session, promised
		// acknowledgement, and died before delivering one.
	})

	ctx, cancel := context.WithTimeout(context.Background(), 1500*time.Millisecond)
	defer cancel()
	started := time.Now()
	err := Uninstall(ctx, uninstallOptions(t, srv.url, serverPub))
	if err == nil {
		t.Fatal("Uninstall() returned nil without ever being acknowledged")
	}
	if !errors.Is(err, ErrUninstallUnconfirmed) {
		t.Errorf("error = %v, want it to wrap ErrUninstallUnconfirmed", err)
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Errorf("waited %s, well past the context deadline", elapsed)
	}
}
