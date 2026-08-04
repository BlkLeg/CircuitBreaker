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
func Run(cfg *config.Config, key *DeviceKey, agentVersion string) error {
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

	conn, _, err := tlsdial.NewDialer(cfg.TLSPin).Dial(u.String(), nil)
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

	for {
		_, ct, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("enroll: connection closed while awaiting approval: %w", err)
		}
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
