// apps/agent/internal/enroll/enroll.go
package enroll

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/hostinfo"
	"circuitbreaker.dev/cb-agent/internal/noiseconn"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

// Run dials WS /api/agents/enroll, completes the Noise IK handshake, sends
// the hello frame, prints the pairing code / magic link / fingerprint to
// stdout, and blocks until the server reports the agent is no longer
// pending. Returns nil once status is "active" (caller proceeds to
// internal/link.Run); returns an error for "rejected" or "revoked".
// handshakeTimeout bounds the reads that happen before the server has proved
// it is answering: the Noise handshake response, and the first frame after our
// hello. gorilla's ReadMessage carries no deadline of its own, so a server
// that accepts the upgrade and then stalls — wedged behind its own database,
// or on the far side of a connection that went half-open — left Run blocked in
// one read with nothing able to recover it. internal/link fixed exactly this
// (see its own handshakeTimeout); enroll did not, and runDaemon calls Run on
// every start before it reaches the link, the spool or the status writer, so
// the whole daemon hung there silently.
//
// It is deliberately NOT the bound on waiting for approval: that wait is a
// human pressing a button and is legitimately unbounded, so the deadline is
// cleared as soon as the first frame arrives. A var so tests can shrink it.
var handshakeTimeout = 10 * time.Second

// Run takes trust as a resolved tlsdial.Trust rather than resolving it
// itself: internal/link already imports internal/enroll for DeviceKey, so
// enroll importing internal/link back (to call link.ResolveTrust) would be
// an import cycle. cmd/cb-agent/main.go resolves it once via
// link.ResolveTrust(cfg, config.StateDir()) and passes the result in.
func Run(cfg *config.Config, key *DeviceKey, agentVersion string, trust tlsdial.Trust) error {
	remotePub, err := hex.DecodeString(cfg.ServerStaticPK)
	if err != nil || len(remotePub) != 32 {
		return fmt.Errorf("enroll: invalid server_static_pk in config: %w", err)
	}
	var remotePubArr [32]byte
	copy(remotePubArr[:], remotePub)

	session, err := noiseconn.NewInitiator(key.Private, key.Public, remotePubArr)
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}

	u, err := url.Parse(cfg.ServerURL)
	if err != nil {
		return fmt.Errorf("enroll: invalid server_url: %w", err)
	}
	u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)
	u.Path = "/api/v1/agents/enroll"

	conn, _, err := tlsdial.NewDialer(trust).Dial(u.String(), nil)
	if err != nil {
		return fmt.Errorf("enroll: dial %s: %w", u.String(), err)
	}
	defer conn.Close()

	msg1, err := session.WriteHandshakeMessage()
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, msg1); err != nil {
		return fmt.Errorf("enroll: send handshake message: %w", err)
	}

	_ = conn.SetReadDeadline(time.Now().Add(handshakeTimeout))
	_, msg2, err := conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("enroll: read handshake response: %w", err)
	}
	if err := session.ReadHandshakeMessage(msg2); err != nil {
		return fmt.Errorf("enroll: %w", err)
	}

	helloPayload := hostinfo.Collect(agentVersion)
	helloFrame := frame.Frame{V: 1, Type: frame.TypeHello, Seq: 0, TS: time.Now().UTC()}
	helloFrame.Payload, err = json.Marshal(helloPayload)
	if err != nil {
		return fmt.Errorf("enroll: encode hello payload: %w", err)
	}
	helloBytes, err := frame.Encode(helloFrame)
	if err != nil {
		return fmt.Errorf("enroll: %w", err)
	}
	if err := conn.WriteMessage(websocket.BinaryMessage, session.Encrypt(helloBytes)); err != nil {
		return fmt.Errorf("enroll: send hello: %w", err)
	}

	fp := key.FingerprintGrouped()
	fmt.Printf("device fingerprint: %s\n", fp)
	fmt.Println("compare this fingerprint against the one shown on the approval screen")

	// Still bounded: the server owes us its first frame promptly, whether that
	// is the pairing code for a new device or the immediate status=active an
	// already-enrolled agent gets on every daemon start. Cleared below, once
	// that frame arrives.
	_ = conn.SetReadDeadline(time.Now().Add(handshakeTimeout))
	for {
		_, ct, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("enroll: connection closed while awaiting approval: %w", err)
		}
		// The server is answering. Everything from here on waits on a human,
		// so no deadline applies.
		_ = conn.SetReadDeadline(time.Time{})
		pt, err := session.Decrypt(ct)
		if err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		f, err := frame.Decode(pt)
		if err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		var payload map[string]any
		if err := json.Unmarshal(f.Payload, &payload); err != nil {
			return fmt.Errorf("enroll: %w", err)
		}
		if code, ok := payload["pairing_code"].(string); ok {
			fmt.Printf("pairing code: %s\n", code)
			link, _ := payload["magic_link"].(string)
			if link != "" {
				fmt.Printf("magic link:   %s%s\n", cfg.ServerURL, link)
			}
			continue
		}
		status, _ := payload["status"].(string)
		switch status {
		case "active":
			fmt.Println("approved — connecting")
			return nil
		case "rejected":
			return errors.New("enroll: enrollment was rejected")
		case "revoked":
			return errors.New("enroll: agent was revoked")
		}
	}
}
