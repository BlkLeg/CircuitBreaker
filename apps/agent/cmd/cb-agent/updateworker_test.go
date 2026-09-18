// Tests for the serialized update worker: heartbeats must keep flowing while
// an update blocks its
// own goroutine, a second instruction during a live update must be refused,
// cancellation must stop the worker without stranding a goroutine, and the
// outcome/rollback durability contracts must hold on both the succeeded and
// failed paths.
package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/flynn/noise"
	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// workerTestResponder is the Noise responder side of a fake link server —
// duplicated from internal/link's test helpers per that package's own note
// (no shared Go test-utility package yet).
type workerTestResponder struct {
	hs   *noise.HandshakeState
	send *noise.CipherState
	recv *noise.CipherState
}

func newWorkerTestResponder(t *testing.T, priv, pub [32]byte) *workerTestResponder {
	t.Helper()
	cs := noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashSHA256)
	hs, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:   cs,
		Pattern:       noise.HandshakeIK,
		Initiator:     false,
		StaticKeypair: noise.DHKey{Private: priv[:], Public: pub[:]},
	})
	if err != nil {
		t.Fatalf("NewHandshakeState() error = %v", err)
	}
	return &workerTestResponder{hs: hs}
}

func (s *workerTestResponder) ReadHandshakeMessage(msg1 []byte) ([]byte, error) {
	if _, _, _, err := s.hs.ReadMessage(nil, msg1); err != nil {
		return nil, fmt.Errorf("workerTestResponder: read message 1: %w", err)
	}
	msg2, c1, c2, err := s.hs.WriteMessage(nil, nil)
	if err != nil {
		return nil, fmt.Errorf("workerTestResponder: write message 2: %w", err)
	}
	s.recv = c1
	s.send = c2
	return msg2, nil
}

func (s *workerTestResponder) Encrypt(plaintext []byte) []byte {
	ct, err := s.send.Encrypt(nil, nil, plaintext)
	if err != nil {
		panic(fmt.Sprintf("workerTestResponder: encrypt: %v", err))
	}
	return ct
}

func (s *workerTestResponder) Decrypt(ciphertext []byte) ([]byte, error) {
	pt, err := s.recv.Decrypt(nil, nil, ciphertext)
	if err != nil {
		return nil, fmt.Errorf("workerTestResponder: decrypt: %w", err)
	}
	return pt, nil
}

func workerTestKeypair(t *testing.T) (priv, pub [32]byte) {
	t.Helper()
	dhKey, err := noise.DH25519.GenerateKeypair(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKeypair() error = %v", err)
	}
	copy(priv[:], dhKey.Private)
	copy(pub[:], dhKey.Public)
	return priv, pub
}

// waitFor polls cond until it returns true or the timeout elapses, failing
// the test with msg in the latter case. The worker releases its busy gate
// asynchronously from the enqueue path, so tests that assert on admission
// must poll rather than assume.
func waitFor(t *testing.T, cond func() bool, timeout time.Duration, msg string) {
	t.Helper()
	deadline := time.After(timeout)
	for !cond() {
		select {
		case <-deadline:
			t.Fatal(msg)
		case <-time.After(20 * time.Millisecond):
		}
	}
}

func updateInstructionPayload(version string) json.RawMessage {
	raw, _ := json.Marshal(map[string]string{
		"version": version, "sha256": strings.Repeat("ab", 32), "arch": "amd64", "os": "linux",
	})
	return raw
}

// Heartbeats must survive a blocked update, in the form the daemon can
// actually exercise: the update worker's execute goroutine is blocked, and the
// link must keep serving traffic the whole time. Pings are the probe — the
// link answers each inbound `ping` with an immediate heartbeat, so a
// heartbeat arriving while execute is blocked proves both that inbound
// frames are still being read and dispatched and that the event loop is
// still writing. An update that ran on the event loop itself would answer
// nothing while it ran.
func TestUpdateWorker_HeartbeatsContinueWhileUpdateBlocks(t *testing.T) {
	serverPriv, serverPub := workerTestKeypair(t)

	const wantReplies = 5
	var (
		beatMu       sync.Mutex
		pingReplies  atomic.Int32
		statusMu     sync.Mutex
		statusPhases []string
		unblock      = make(chan struct{})
	)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		resp := newWorkerTestResponder(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := resp.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		conn.WriteMessage(websocket.BinaryMessage, msg2)
		_, helloCt, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if _, err := resp.Decrypt(helloCt); err != nil {
			return
		}
		ack, _ := json.Marshal(map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"accepted": true, "agent_id": 1},
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ack))

		instr, _ := json.Marshal(map[string]any{
			"v": 1, "type": "update", "seq": 1, "ts": time.Now().UTC(),
			"payload": updateInstructionPayload("0.9.0"),
		})
		conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(instr))

		// Pings on a ticker, each expecting an immediate heartbeat back.
		pingSeq := uint64(1)
		stopPings := make(chan struct{})
		defer close(stopPings)
		go func() {
			ticker := time.NewTicker(150 * time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-stopPings:
					return
				case <-ticker.C:
					pingSeq++
					ping, _ := json.Marshal(map[string]any{
						"v": 1, "type": "ping", "seq": pingSeq, "ts": time.Now().UTC(),
					})
					if err := conn.WriteMessage(websocket.BinaryMessage, resp.Encrypt(ping)); err != nil {
						return
					}
				}
			}
		}()

		for {
			_, ct, err := conn.ReadMessage()
			if err != nil {
				return
			}
			pt, err := resp.Decrypt(ct)
			if err != nil {
				return
			}
			var f struct {
				Type    string          `json:"type"`
				Payload json.RawMessage `json:"payload"`
			}
			if err := json.Unmarshal(pt, &f); err != nil {
				return
			}
			switch f.Type {
			case "heartbeat":
				beatMu.Lock()
				pingReplies.Add(1)
				beatMu.Unlock()
			case "update.status":
				var st struct {
					Phase string `json:"phase"`
				}
				json.Unmarshal(f.Payload, &st)
				statusMu.Lock()
				statusPhases = append(statusPhases, st.Phase)
				statusMu.Unlock()
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

	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()

	// The real wiring runDaemon builds: the worker behind OnUpdate, its
	// status channel behind UpdateStatusFrames. The execute seam blocks —
	// the download it stands in for is the two-minute window this whole
	// change exists to take off the event loop.
	statusC := make(chan link.UpdateStatusEvent, updateStatusQueueDepth)
	worker := newUpdateWorker(ctx, &config.Config{ServerURL: wsURL}, dir, statusC)
	executeStarted := make(chan struct{})
	worker.execute = func(ctx context.Context, job updateJob, report func(link.UpdateStatusEvent) error, exec func() error) error {
		close(executeStarted)
		<-unblock // the blocked download: heartbeats must keep flowing past here
		if err := report(link.UpdateStatusEvent{Version: job.instr.Version, Phase: "succeeded"}); err != nil {
			t.Errorf("report(succeeded) error = %v", err)
		}
		return nil
	}
	worker.start()
	defer worker.stop()

	opts := link.Options{
		Config: &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])},
		Key:    key, AgentVersion: "0.1.0-test",
		OnUpdate:           worker.enqueue,
		UpdateStatusFrames: statusC,
	}
	go func() { _ = link.Run(ctx, opts) }()

	select {
	case <-executeStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("the update instruction never reached the worker")
	}

	// The assertion: while execute is blocked on <-unblock, the link keeps
	// answering pings. wantReplies at 150ms apart is over a second of
	// proven liveness mid-"download".
	deadline := time.After(5 * time.Second)
	for {
		if pingReplies.Load() >= wantReplies {
			break
		}
		select {
		case <-deadline:
			t.Fatalf("only %d of %d heartbeat replies arrived while the update worker was blocked — the event loop is stalled by the update",
				pingReplies.Load(), wantReplies)
		case <-time.After(50 * time.Millisecond):
		}
	}

	close(unblock)
	statusDeadline := time.After(3 * time.Second)
	for {
		statusMu.Lock()
		got := append([]string(nil), statusPhases...)
		statusMu.Unlock()
		if len(got) >= 1 && got[len(got)-1] == "succeeded" {
			break
		}
		select {
		case <-statusDeadline:
			t.Fatalf("the succeeded status never crossed to the server: phases observed = %v", got)
		case <-time.After(50 * time.Millisecond):
		}
	}
	cancel()
}

// a second instruction arriving while one is queued or running is
// refused with the exact wire-contract message — never queued behind the
// first, never dropped silently.
func TestUpdateWorker_SecondInstructionRefusedWhileExecuting(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	statusC := make(chan link.UpdateStatusEvent, updateStatusQueueDepth)
	worker := newUpdateWorker(ctx, &config.Config{}, t.TempDir(), statusC)

	executeStarted := make(chan struct{})
	var startedOnce sync.Once
	unblock := make(chan struct{})
	worker.execute = func(context.Context, updateJob, func(link.UpdateStatusEvent) error, func() error) error {
		// The second instruction this test admits after unblocking reuses
		// this seam; the signal is for the first job only.
		startedOnce.Do(func() { close(executeStarted) })
		<-unblock
		return nil
	}
	worker.start()
	defer worker.stop()

	if err := worker.enqueue(updateInstructionPayload("0.9.0")); err != nil {
		t.Fatalf("first enqueue() error = %v, want nil", err)
	}
	select {
	case <-executeStarted:
	case <-time.After(3 * time.Second):
		t.Fatal("worker never started executing the first instruction")
	}

	// Refused while running — the dequeued job leaves jobC empty, so this
	// is the case the busy gate exists for.
	err := worker.enqueue(updateInstructionPayload("0.10.0"))
	if !errors.Is(err, errUpdateInProgress) {
		t.Fatalf("second enqueue() while running = %v, want %q", err, errUpdateInProgress)
	}
	// A malformed payload is refused as malformed without disturbing the
	// in-flight update's serialization state.
	if err := worker.enqueue(json.RawMessage("{not json")); err == nil {
		t.Fatal("enqueue() of malformed json = nil, want an error")
	}
	if err := worker.enqueue(updateInstructionPayload("0.10.0")); !errors.Is(err, errUpdateInProgress) {
		t.Fatalf("enqueue() after a malformed refusal = %v, want %q — a malformed payload must not free the busy gate", err, errUpdateInProgress)
	}

	close(unblock)
	// busy is released once the job finishes, so a later instruction is
	// admitted again.
	waitFor(t, func() bool {
		return worker.enqueue(updateInstructionPayload("0.11.0")) == nil
	}, 3*time.Second, "the worker never accepted work again after its job finished")

	// A canceled worker refuses new work outright.
	cancel()
	waitFor(t, func() bool {
		err := worker.enqueue(updateInstructionPayload("0.12.0"))
		return err != nil && !errors.Is(err, errUpdateInProgress)
	}, 3*time.Second, "enqueue() after cancellation still returns a running-worker error, want a stopping-worker error")
}

// cancellation stops the worker and no goroutine stays blocked — not
// on the job queue, and not on a status channel whose consumer (the link's
// event loop) is already gone.
func TestUpdateWorker_CancelStopsBlockedExecuteWithoutStrandingAGoroutine(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	statusC := make(chan link.UpdateStatusEvent, updateStatusQueueDepth)
	worker := newUpdateWorker(ctx, &config.Config{}, t.TempDir(), statusC)

	worker.execute = func(context.Context, updateJob, func(link.UpdateStatusEvent) error, func() error) error {
		<-ctx.Done() // a download that only ends when its context does
		return ctx.Err()
	}
	worker.start()

	if err := worker.enqueue(updateInstructionPayload("0.9.0")); err != nil {
		t.Fatalf("enqueue() error = %v, want nil", err)
	}

	// Saturate the status channel first: report() must still return
	// promptly on a canceled context even when there is no room and no
	// reader (the link is gone during shutdown).
	for i := 0; i < updateStatusQueueDepth; i++ {
		statusC <- link.UpdateStatusEvent{Version: "0.9.0", Phase: "started"}
	}
	reportDone := make(chan error, 1)
	go func() {
		reportDone <- worker.report(ctx, link.UpdateStatusEvent{Version: "0.9.0", Phase: "failed", ErrMsg: "x"})
	}()
	cancel()
	select {
	case err := <-reportDone:
		if err == nil {
			t.Error("report() on a canceled worker = nil, want the context error")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("report() blocked past cancellation — a full channel with no reader must not strand the worker")
	}

	stopDone := make(chan struct{})
	go func() {
		worker.stop()
		close(stopDone)
	}()
	select {
	case <-stopDone:
	case <-time.After(5 * time.Second):
		t.Fatal("stop() did not return within 5s of cancellation — the worker goroutine is stranded")
	}
	// Drain so a later reconnect in this test (there is none) could not
	// see stale events; capacity restored.
	for i := 0; i < updateStatusQueueDepth; i++ {
		<-statusC
	}
}

// the pending outcome is durably recorded
// before the succeeded status is handed to the link, and re-exec happens
// after — so a drop in the exact pre-reexec window leaves a record the next
// process reports. Drives the real executeUpdate against a fake update
// server.
func TestUpdateWorker_ExecutePersistsOutcomeBeforeSucceededAndReexec(t *testing.T) {
	content := []byte("#!/bin/sh\nfake agent binary\n")
	sum := sha256.Sum256(content)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, ".sig"):
			_, _ = w.Write([]byte("c2lnbmF0dXJlLWJ5dGVz"))
		default:
			_, _ = w.Write(content)
		}
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stateDir := t.TempDir()
	statusC := make(chan link.UpdateStatusEvent, updateStatusQueueDepth)
	worker := newUpdateWorker(ctx, &config.Config{ServerURL: srv.URL}, stateDir, statusC)

	execCalled := make(chan struct{}, 1)
	worker.exec = func() error {
		execCalled <- struct{}{}
		return nil
	}
	worker.start()
	defer worker.stop()

	instr, err := json.Marshal(update.Instruction{
		Version: "0.9.0", SHA256: hex.EncodeToString(sum[:]), Arch: "amd64", OS: "linux",
	})
	if err != nil {
		t.Fatalf("marshal instruction: %v", err)
	}
	if err := worker.enqueue(instr); err != nil {
		t.Fatalf("enqueue() error = %v, want nil", err)
	}

	readStatus := func(wantPhase string) link.UpdateStatusEvent {
		t.Helper()
		deadline := time.After(10 * time.Second)
		for {
			select {
			case evt := <-statusC:
				if evt.Phase == wantPhase {
					return evt
				}
			case <-deadline:
				t.Fatalf("no %s update.status observed in time", wantPhase)
			}
		}
	}
	started := readStatus("started")
	if started.Version != "0.9.0" {
		t.Fatalf("started status version = %q, want 0.9.0", started.Version)
	}
	succeeded := readStatus("succeeded")
	if succeeded.Version != "0.9.0" {
		t.Fatalf("succeeded status version = %q, want 0.9.0", succeeded.Version)
	}

	// The ordering assertion: by the time the succeeded event is visible to
	// the link, the outcome it describes is already durable — a connection
	// drop from this instant forward still converges on the server.
	version, phase, ok, err := update.ReadPendingOutcome(stateDir)
	if err != nil || !ok {
		t.Fatalf("ReadPendingOutcome() after succeeded = (%q, %q, %v, %v), want ok=true err=nil — the outcome must be durable before the status is sent", version, phase, ok, err)
	}
	if version != "0.9.0" || phase != "succeeded" {
		t.Fatalf("ReadPendingOutcome() = (%q, %q), want (0.9.0, succeeded)", version, phase)
	}

	// The marker must sit in pending-confirm — the swap completed and the
	// rollback window is armed, exactly as the pre-refactor path left it.
	_, _, swapped, present, err := update.ReadMarker(stateDir)
	if err != nil || !present || !swapped {
		t.Fatalf("ReadMarker() = (present=%v, swapped=%v, err=%v), want the pending-confirm marker the rollback window depends on", present, swapped, err)
	}

	select {
	case <-execCalled:
	case <-time.After(3 * time.Second):
		t.Fatal("re-exec never happened after the succeeded status")
	}
	// Cancel before returning: the deferred stop() must not wait on a
	// worker whose ctx is still live (see the note in the failed-update
	// test above).
	cancel()
}

// a failed download/verify/swap never reports success, leaves no
// misleading pending outcome, and never re-execs.
func TestUpdateWorker_FailedUpdateLeavesNoPendingOutcomeAndNoExec(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stateDir := t.TempDir()
	statusC := make(chan link.UpdateStatusEvent, updateStatusQueueDepth)
	// Port 1 on the loopback: nothing listens, so the download fails fast.
	worker := newUpdateWorker(ctx, &config.Config{ServerURL: "http://127.0.0.1:1"}, stateDir, statusC)

	execCalled := false
	worker.exec = func() error {
		execCalled = true
		return nil
	}
	worker.start()
	defer worker.stop()

	if err := worker.enqueue(updateInstructionPayload("0.9.0")); err != nil {
		t.Fatalf("enqueue() error = %v, want nil", err)
	}

	var phases []string
	deadline := time.After(10 * time.Second)
	for {
		select {
		case evt := <-statusC:
			phases = append(phases, evt.Phase)
			if evt.Phase == "failed" {
				if evt.Version != "0.9.0" {
					t.Errorf("failed status version = %q, want 0.9.0", evt.Version)
				}
				if evt.ErrMsg == "" {
					t.Error("failed status carries no error message — the server cannot tell why it failed")
				}
				goto done
			}
		case <-deadline:
			t.Fatalf("update never reported failed; phases observed = %v", phases)
		}
	}
done:
	// Cancel explicitly: the deferred stop() waits on the worker goroutine,
	// which only exits once this ctx is done — defers run LIFO, so leaving
	// the cancellation to its own defer would deadlock the shutdown path
	// this test exists to prove bounded.
	cancel()
	if _, _, ok, err := update.ReadPendingOutcome(stateDir); ok || err != nil {
		t.Errorf("ReadPendingOutcome() after a failed update = (ok=%v, err=%v), want ok=false err=nil — a failed update must leave no succeeded-shaped record", ok, err)
	}
	if _, _, _, present, _ := update.ReadMarker(stateDir); present {
		t.Error("a rollback marker survived a failed download — nothing was installed, so nothing must be guarded")
	}
	if execCalled {
		t.Error("re-exec ran for a failed update")
	}
}
