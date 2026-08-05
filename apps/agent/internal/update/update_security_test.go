// apps/agent/internal/update/update_security_test.go
package update

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/config"
)

// TestDownload_RejectsCertPinMismatch proves Download actually enforces
// cfg.TLSPin against the server it downloads from — the point of routing
// through tlsdial.NewTransport instead of a bare http.Get.
func TestDownload_RejectsCertPinMismatch(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("should never be read"))
	}))
	defer srv.Close()

	// A well-formed but wrong SPKI pin (32 zero bytes, base64'd) — the
	// server's real cert will never match it.
	const wrongPin = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

	cfg := &config.Config{ServerURL: srv.URL, TLSPin: wrongPin}
	instr := Instruction{Version: "0.2.0", SHA256: "deadbeef", Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err == nil {
		os.Remove(tmpPath)
		t.Fatal("Download() with mismatched pin = nil error, want an error")
	}
	if !strings.Contains(err.Error(), "download") {
		t.Errorf("Download() error = %v, want it to wrap the download failure", err)
	}
}

// TestDownload_RejectsOnTimeout proves Download's client actually enforces
// downloadTimeout rather than blocking forever against a server that never
// finishes responding.
func TestDownload_RejectsOnTimeout(t *testing.T) {
	orig := downloadTimeout
	downloadTimeout = 50 * time.Millisecond
	defer func() { downloadTimeout = orig }()

	blockUntil := make(chan struct{})
	// Deferred close(blockUntil) MUST run before srv.Close(): httptest.
	// Server.Close() blocks until every outstanding handler goroutine
	// returns, and the handler below blocks on <-blockUntil until this
	// fires. Defers run LIFO, so declaring srv (and its defer) first, then
	// blockUntil's defer second, makes close(blockUntil) run first at
	// function return — unblocking the handler so srv.Close() can proceed.
	// Registering these in the opposite order deadlocks the whole test
	// binary (Close() waits on the handler; the handler waits on this
	// close, which never runs because Close() hasn't returned yet).
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-blockUntil // never returns within the test's lifetime
	}))
	defer srv.Close()
	defer close(blockUntil)

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: "deadbeef", Arch: "amd64", OS: "linux"}

	start := time.Now()
	tmpPath, err := Download(cfg, instr)
	elapsed := time.Since(start)
	if err == nil {
		os.Remove(tmpPath)
		t.Fatal("Download() against a hanging server = nil error, want a timeout error")
	}
	if elapsed > 5*time.Second {
		t.Errorf("Download() took %s to fail, want it bounded by downloadTimeout (50ms)", elapsed)
	}
}

// TestDownload_RejectsOversizeContentLength proves Download rejects a
// response whose Content-Length header alone already exceeds
// maxDownloadBytes, without reading the (huge) body at all.
func TestDownload_RejectsOversizeContentLength(t *testing.T) {
	orig := maxDownloadBytes
	maxDownloadBytes = 16
	defer func() { maxDownloadBytes = orig }()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "1000000")
		w.WriteHeader(http.StatusOK)
		// Deliberately do not write 1000000 bytes — if Download tried to
		// read that many it would hang/EOF-error rather than fail fast on
		// the Content-Length check, which is exactly what this test wants
		// to rule out.
	}))
	defer srv.Close()

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: "deadbeef", Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err == nil {
		os.Remove(tmpPath)
		t.Fatal("Download() with oversize Content-Length = nil error, want an error")
	}
	if !strings.Contains(err.Error(), "exceeds limit") {
		t.Errorf("Download() error = %v, want it to mention the size limit", err)
	}
}

// TestDownload_RejectsOversizeStreamedBody proves Download also enforces
// maxDownloadBytes against the actual bytes streamed, independent of
// (and even in the absence of) any Content-Length header — a server can
// omit or lie about it, so the real limit must not rely on trusting it.
func TestDownload_RejectsOversizeStreamedBody(t *testing.T) {
	orig := maxDownloadBytes
	maxDownloadBytes = 16
	defer func() { maxDownloadBytes = orig }()

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		flusher, _ := w.(http.Flusher)
		for i := 0; i < 8; i++ {
			_, _ = w.Write([]byte("xxxx")) // 8 * 4 = 32 bytes, no Content-Length set
			if flusher != nil {
				flusher.Flush() // forces chunked transfer, defeating any Content-Length precheck
			}
		}
	}))
	defer srv.Close()

	cfg := &config.Config{ServerURL: srv.URL}
	instr := Instruction{Version: "0.2.0", SHA256: "deadbeef", Arch: "amd64", OS: "linux"}

	tmpPath, err := Download(cfg, instr)
	if err == nil {
		os.Remove(tmpPath)
		t.Fatal("Download() with oversize streamed body = nil error, want an error")
	}
	if !strings.Contains(err.Error(), "size limit") {
		t.Errorf("Download() error = %v, want it to mention the size limit", err)
	}
}

// TestVerifySHA256_CaseInsensitive proves VerifySHA256 accepts a want value
// in any hex case, since it now compares via constantTimeEqualHexFold rather
// than a plain ==.
func TestVerifySHA256_CaseInsensitive(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/binary"
	content := []byte("some binary contents")
	if err := os.WriteFile(path, content, 0o755); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(content)
	lower := hex.EncodeToString(sum[:])
	mixed := mixCase(lower)

	if err := VerifySHA256(path, mixed); err != nil {
		t.Errorf("VerifySHA256() with mixed-case want = %v, want nil (case-insensitive match)", err)
	}

	// Sanity: an actually-wrong hash (even same-case) must still be rejected.
	wrong := strings.Repeat("0", len(lower))
	if err := VerifySHA256(path, wrong); err == nil {
		t.Error("VerifySHA256() with wrong hash = nil error, want an error")
	}
}

// TestConstantTimeEqualHexFold_MismatchedCase directly exercises the
// comparison helper: equal content, different case, different length.
func TestConstantTimeEqualHexFold_MismatchedCase(t *testing.T) {
	cases := []struct {
		name string
		a, b string
		want bool
	}{
		{"identical", "deadbeef", "deadbeef", true},
		{"mixed case equal", "DeAdBeEf", "deadbeef", true},
		{"all upper vs all lower", "DEADBEEF", "deadbeef", true},
		{"different content", "deadbeef", "deadbeee", false},
		{"different length", "deadbeef", "deadbee", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := constantTimeEqualHexFold(tc.a, tc.b); got != tc.want {
				t.Errorf("constantTimeEqualHexFold(%q, %q) = %v, want %v", tc.a, tc.b, got, tc.want)
			}
		})
	}
}

// mixCase alternates upper/lower case across a hex string's letters, leaving
// digits untouched, to produce a deliberately mixed-case variant for testing.
func mixCase(s string) string {
	b := []byte(s)
	for i, c := range b {
		if i%2 == 0 && c >= 'a' && c <= 'f' {
			b[i] = c - ('a' - 'A')
		}
	}
	return string(b)
}
