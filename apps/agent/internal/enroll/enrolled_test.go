// apps/agent/internal/enroll/enrolled_test.go
package enroll

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

func TestMarkEnrolled_RoundTripsThroughIsEnrolledAndClearEnrolled(t *testing.T) {
	dir := t.TempDir()

	if IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = true before MarkEnrolled was ever called")
	}

	if err := MarkEnrolled(dir); err != nil {
		t.Fatalf("MarkEnrolled() error = %v", err)
	}
	if !IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = false right after MarkEnrolled succeeded")
	}

	if err := ClearEnrolled(dir); err != nil {
		t.Fatalf("ClearEnrolled() error = %v", err)
	}
	if IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = true after ClearEnrolled")
	}
}

func TestClearEnrolled_IsSilentWhenThereIsNoMarker(t *testing.T) {
	// Phase 6 clears this unconditionally on an unknown-device refusal; that
	// path must not error just because enrollment never happened yet.
	if err := ClearEnrolled(t.TempDir()); err != nil {
		t.Fatalf("ClearEnrolled() on an absent marker error = %v, want nil", err)
	}
}

func TestMarkEnrolled_WritesNoTornStateOnRename(t *testing.T) {
	// The temp file must not survive a successful MarkEnrolled — only the
	// renamed-into-place marker should remain, mirroring
	// spool.writeHeadMarker's own contract.
	dir := t.TempDir()
	if err := MarkEnrolled(dir); err != nil {
		t.Fatalf("MarkEnrolled() error = %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, enrolledFilename+".tmp")); !os.IsNotExist(err) {
		t.Fatalf("temp marker file survived: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(dir, enrolledFilename))
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("marker file is empty")
	}
}

// runEnrollAgainstFinalStatus drives Run against a minimal server that skips
// straight to a final hello.ack carrying the given status, and returns
// whatever Run returns. It exists so the rejected/revoked marker tests below
// don't have to re-derive the whole Noise/websocket harness the "active"
// test in enroll_test.go already establishes.
func runEnrollAgainstFinalStatus(t *testing.T, stateDir, status string) error {
	t.Helper()
	serverPriv, serverPub := generateTestKeypair(t)

	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		responder := newTestResponderSession(t, serverPriv, serverPub)
		_, msg1, err := conn.ReadMessage()
		if err != nil {
			return
		}
		msg2, err := responder.ReadHandshakeMessage(msg1)
		if err != nil {
			return
		}
		if err := conn.WriteMessage(websocket.BinaryMessage, msg2); err != nil {
			return
		}
		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}

		final := map[string]any{
			"v": 1, "type": "hello.ack", "seq": 0, "ts": time.Now().UTC(),
			"payload": map[string]any{"agent_id": 1, "status": status},
		}
		finalBytes, _ := json.Marshal(final)
		conn.WriteMessage(websocket.BinaryMessage, responder.Encrypt(finalBytes))
	}))
	t.Cleanup(srv.Close)

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http")
	key, err := LoadOrCreateDeviceKey(stateDir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	cfg := &config.Config{ServerURL: wsURL, ServerStaticPK: hex.EncodeToString(serverPub[:])}
	return Run(cfg, key, "0.1.0-test", tlsdial.Trust{Mode: tlsdial.ModePublic}, stateDir)
}

func TestRun_RejectedReturnsErrRejectedAndWritesNoMarker(t *testing.T) {
	dir := t.TempDir()

	err := runEnrollAgainstFinalStatus(t, dir, "rejected")
	if !errors.Is(err, ErrRejected) {
		t.Fatalf("Run() error = %v, want ErrRejected", err)
	}
	if IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = true after a rejected enrollment")
	}
}

func TestRun_RevokedReturnsErrRevokedAndWritesNoMarker(t *testing.T) {
	dir := t.TempDir()

	err := runEnrollAgainstFinalStatus(t, dir, "revoked")
	if !errors.Is(err, ErrRevoked) {
		t.Fatalf("Run() error = %v, want ErrRevoked", err)
	}
	if IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = true after a revoked enrollment")
	}
}

func TestRun_UnreachableServerWritesNoMarker(t *testing.T) {
	// A dial failure never reaches the "active" branch at all; asserted
	// directly so a future refactor of Run's error paths can't accidentally
	// start marking a device enrolled before the server has said so.
	dir := t.TempDir()
	key, err := LoadOrCreateDeviceKey(dir)
	if err != nil {
		t.Fatalf("LoadOrCreateDeviceKey() error = %v", err)
	}
	_, pub := generateTestKeypair(t)
	cfg := &config.Config{ServerURL: "ws://127.0.0.1:1", ServerStaticPK: hex.EncodeToString(pub[:])}

	if err := Run(cfg, key, "0.1.0-test", tlsdial.Trust{Mode: tlsdial.ModePublic}, dir); err == nil {
		t.Fatal("Run() error = nil, want a dial error against an unreachable server")
	}
	if IsEnrolled(dir) {
		t.Fatal("IsEnrolled() = true after Run could not even reach the server")
	}
}
