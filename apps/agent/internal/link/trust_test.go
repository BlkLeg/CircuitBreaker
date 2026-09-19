package link

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/tlsdial"
)

func TestResolveTrust_NoRotationIsTheConfiguredPin(t *testing.T) {
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, t.TempDir())
	if got.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("Mode = %q, want %q", got.Mode, tlsdial.ModeSelfSigned)
	}
	if len(got.Pins) != 1 || got.Pins[0] != "PIN-A" {
		t.Errorf("Pins = %v, want [PIN-A]", got.Pins)
	}
}

// An empty tls_pin is how agent.toml expresses "public" trust — the
// installer writes no pin for a Let's Encrypt server.
func TestResolveTrust_EmptyPinIsPublicMode(t *testing.T) {
	got := ResolveTrust(&config.Config{}, t.TempDir())
	if got.Mode != tlsdial.ModePublic {
		t.Errorf("Mode = %q, want %q", got.Mode, tlsdial.ModePublic)
	}
}

func TestResolveTrust_AppendsThePersistedSuccessor(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode:         "self_signed",
		SuccessorPin: "PIN-B",
		Expiry:       time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, dir)
	if len(got.Pins) != 2 || got.Pins[0] != "PIN-A" || got.Pins[1] != "PIN-B" {
		t.Errorf("Pins = %v, want [PIN-A PIN-B]", got.Pins)
	}
}

// A public-mode successor is the self-signed -> Let's Encrypt cutover. Both
// policies must stay acceptable across it, so the resolved mode stays
// self_signed (which is the one needing a callback) and the *server* proving
// a publicly-trusted leaf is handled by promotion, not by pre-emptively
// dropping the pin. Dropping it here would strand the agent the moment the
// successor was advertised but before the cert actually changed.
func TestResolveTrust_PublicSuccessorKeepsTheCurrentPinUsable(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode:   "public",
		Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, dir)
	if got.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("Mode = %q, want the current policy to remain usable", got.Mode)
	}
	if len(got.Pins) != 1 || got.Pins[0] != "PIN-A" {
		t.Errorf("Pins = %v, want [PIN-A]", got.Pins)
	}
	if !got.PublicSuccessorPending {
		t.Error("PublicSuccessorPending = false, want true")
	}
}

func TestResolveTrust_EmptyStateDirSkipsTheLookup(t *testing.T) {
	got := ResolveTrust(&config.Config{TLSPin: "PIN-A"}, "")
	if len(got.Pins) != 1 {
		t.Errorf("Pins = %v, want just the configured pin", got.Pins)
	}
}

func TestHandleTLSPinRotate_PersistsTheSuccessor(t *testing.T) {
	dir := t.TempDir()
	payload := []byte(`{"mode":"self_signed","successor_pin":"PIN-B","expiry":"2026-09-08T10:00:00Z"}`)

	handleTLSPinRotate(Options{StateDir: dir}, payload)

	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil {
		t.Fatal("LoadTLSPinRotation = nil, want the advertised rotation")
	}
	if got.Mode != "self_signed" || got.SuccessorPin != "PIN-B" {
		t.Errorf("persisted = %+v, want mode=self_signed pin=PIN-B", *got)
	}
}

func TestHandleTLSPinRotate_PersistsAPublicCutover(t *testing.T) {
	dir := t.TempDir()
	payload := []byte(`{"mode":"public","successor_pin":"","expiry":"2026-09-08T10:00:00Z"}`)

	handleTLSPinRotate(Options{StateDir: dir}, payload)

	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil || got.Mode != "public" {
		t.Errorf("persisted = %+v, want a present public-mode rotation", got)
	}
}

// A malformed or unknown-mode frame must be dropped, not persisted. Writing
// garbage into the trust file would be worse than ignoring the frame: the
// agent still reaches the server on its current pin, and an operator can
// retry the rotation.
func TestHandleTLSPinRotate_DropsMalformedAndUnknownModes(t *testing.T) {
	for name, payload := range map[string]string{
		"malformed json":          `{not json`,
		"unknown mode":            `{"mode":"whatever","successor_pin":"X","expiry":"2026-09-08T10:00:00Z"}`,
		"self_signed with no pin": `{"mode":"self_signed","successor_pin":"","expiry":"2026-09-08T10:00:00Z"}`,
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			handleTLSPinRotate(Options{StateDir: dir}, []byte(payload))
			got, err := config.LoadTLSPinRotation(dir)
			if err != nil {
				t.Fatalf("LoadTLSPinRotation: %v", err)
			}
			if got != nil {
				t.Errorf("persisted = %+v, want nothing written", *got)
			}
		})
	}
}

// StateDir unset means there is nowhere durable to record the successor.
// Logging and dropping is correct; panicking or writing to the process CWD
// would both be worse.
func TestHandleTLSPinRotate_NoStateDirIsANoOp(t *testing.T) {
	handleTLSPinRotate(Options{}, []byte(`{"mode":"public","expiry":"2026-09-08T10:00:00Z"}`))
}

func TestPromoteTrust_MatchingTheCurrentPinReportsCurrentAndKeepsTheRotation(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, 0)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "current" {
		t.Errorf("kind = %q, want current", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got == nil {
		t.Error("rotation was cleared on a current-pin match, want it kept — the cutover has not happened yet")
	}
}

func TestPromoteTrust_MatchingTheSuccessorClearsTheRotation(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, 1)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "successor" {
		t.Errorf("kind = %q, want successor", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got != nil {
		t.Errorf("rotation = %+v after promotion, want it cleared", *got)
	}
}

func TestPromoteTrust_NoRotationReportsCurrent(t *testing.T) {
	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, t.TempDir(), 0)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "current" {
		t.Errorf("kind = %q, want current", kind)
	}
}

// The self-signed -> Let's Encrypt cutover. The pinned dial fails because the
// new leaf is publicly trusted rather than pinned; because a public successor
// was advertised, one standard-verification retry is warranted.
func TestSuccessorRetry_SelfSignedToPublic(t *testing.T) {
	pinned := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{"PIN-A"}}

	if _, ok := successorRetryTrust(pinned, nil); ok {
		t.Error("successorRetryTrust with no advertised successor = true, want false")
	}

	retry, ok := successorRetryTrust(pinned, &config.TLSPinRotation{Mode: "public"})
	if !ok {
		t.Fatal("successorRetryTrust with an advertised public successor = false, want true")
	}
	if retry.Mode != tlsdial.ModePublic {
		t.Errorf("retry mode = %q, want public", retry.Mode)
	}
}

// The reverse cutover, Let's Encrypt -> self-signed. The agent holds no pin and
// does standard verification, which a self-signed leaf can never pass — the
// mirror image of the case above, and equally fleet-fatal without a retry.
func TestSuccessorRetry_PublicToSelfSigned(t *testing.T) {
	unpinned := tlsdial.Trust{Mode: tlsdial.ModePublic}

	retry, ok := successorRetryTrust(unpinned, &config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B",
	})
	if !ok {
		t.Fatal("successorRetryTrust with an advertised self-signed successor = false, want true")
	}
	if retry.Mode != tlsdial.ModeSelfSigned {
		t.Errorf("retry mode = %q, want self_signed", retry.Mode)
	}
	if len(retry.Pins) != 1 || retry.Pins[0] != "PIN-B" {
		t.Errorf("retry pins = %v, want [PIN-B]", retry.Pins)
	}
}

// A same-mode successor is not a cross-mode cutover: ResolveTrust already
// carries it as an extra pin candidate, so the first dial covers it and a
// retry would be redundant.
func TestSuccessorRetry_NotOfferedForASameModeSuccessor(t *testing.T) {
	pinned := tlsdial.Trust{Mode: tlsdial.ModeSelfSigned, Pins: []string{"PIN-A", "PIN-B"}}

	if _, ok := successorRetryTrust(pinned, &config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B",
	}); ok {
		t.Error("successorRetryTrust for a same-mode successor = true, want false")
	}
}

// A self-signed successor with no pin is malformed; there is nothing to retry
// against and it must not produce an empty pin set, which tlsdial fails closed
// on anyway.
func TestSuccessorRetry_RefusesASelfSignedSuccessorWithNoPin(t *testing.T) {
	if _, ok := successorRetryTrust(tlsdial.Trust{Mode: tlsdial.ModePublic},
		&config.TLSPinRotation{Mode: "self_signed"}); ok {
		t.Error("successorRetryTrust with a pinless self-signed successor = true, want false")
	}
}

// After a successful public retry the agent promotes: the advertised policy is
// now the served one, so the rotation file is cleared and the connection
// reports "successor" — which is what lets convergence reach zero and the
// operator's activation gate open.
func TestPromoteTrust_PublicRetryReportsSuccessorAndClears(t *testing.T) {
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "public", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	kind, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, successorRetryIndex)
	if err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}
	if kind != "successor" {
		t.Errorf("kind = %q, want successor", kind)
	}
	got, err := config.LoadTLSPinRotation(dir)
	if err != nil {
		t.Fatalf("LoadTLSPinRotation: %v", err)
	}
	if got != nil {
		t.Errorf("rotation = %+v after a public promotion, want it cleared", *got)
	}
}

// countingListener counts every accepted connection, so a test can assert a
// dial attempted exactly one TCP connection (no retry) or two (one retry).
type countingListener struct {
	net.Listener
	accepts int32
}

func (c *countingListener) Accept() (net.Conn, error) {
	conn, err := c.Listener.Accept()
	if err == nil {
		// Only a genuine accepted connection counts. Accept also returns an
		// error every time — including at t.Cleanup's srv.Close(), whose
		// Listener.Close unblocks the server's own blocking Accept call with
		// "use of closed network connection" — and counting that would
		// inflate every test's total by one regardless of how many dials it
		// actually made.
		atomic.AddInt32(&c.accepts, 1)
	}
	return conn, err
}

// newCountingTLSServer starts an httptest TLS server whose accepted
// connection count is observable, so dialWithTrust's retry decisions can be
// asserted on the wire rather than inferred from its return values alone.
func newCountingTLSServer(t *testing.T) (*httptest.Server, *countingListener) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("net.Listen: %v", err)
	}
	cl := &countingListener{Listener: ln}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	srv.Listener = cl
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return srv, cl
}

func wsURL(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	return strings.Replace(srv.URL, "https://", "wss://", 1)
}

// A pin failure with no persisted rotation at all is the overwhelmingly
// common case (no cutover has ever been advertised to this agent). It must
// not attempt a second dial: successorRetryTrust has nothing to say yes to,
// so dialWithTrust should fail on the very first (and only) connection.
func TestDialWithTrust_NoRotationPerformsNoSecondDial(t *testing.T) {
	srv, cl := newCountingTLSServer(t)

	opts := Options{
		Config:   &config.Config{TLSPin: "WRONG-PIN"},
		StateDir: t.TempDir(), // no rotation ever saved here
	}
	conn, promote, err := dialWithTrust(context.Background(), opts, wsURL(t, srv))
	if err == nil {
		if conn != nil {
			conn.Close()
		}
		t.Fatal("dialWithTrust succeeded against a server presenting an unpinned certificate")
	}
	if promote != nil {
		t.Error("promote func = non-nil on a failed dial, want nil")
	}
	if got := atomic.LoadInt32(&cl.accepts); got != 1 {
		t.Errorf("accepted connections = %d, want 1 (no retry dial)", got)
	}
}

// opts.StateDir == "" must skip the retry path entirely rather than falling
// back to LoadTLSPinRotation's process-relative default location — every
// other stateDir-gated lookup in this package (ResolveTrust,
// serverKeyCandidates, handleTLSPinRotate) guards this case explicitly, and
// this is the one path where reading a file an attacker could plant in the
// process's working directory would matter most.
func TestDialWithTrust_NoStateDirPerformsNoSecondDial(t *testing.T) {
	srv, cl := newCountingTLSServer(t)

	opts := Options{
		Config:   &config.Config{TLSPin: "WRONG-PIN"},
		StateDir: "",
	}
	conn, promote, err := dialWithTrust(context.Background(), opts, wsURL(t, srv))
	if err == nil {
		if conn != nil {
			conn.Close()
		}
		t.Fatal("dialWithTrust succeeded against a server presenting an unpinned certificate")
	}
	if promote != nil {
		t.Error("promote func = non-nil on a failed dial, want nil")
	}
	if got := atomic.LoadInt32(&cl.accepts); got != 1 {
		t.Errorf("accepted connections = %d, want 1 (no retry dial with StateDir unset)", got)
	}
}

// When a cross-mode retry is warranted but the retry dial fails too (here:
// the advertised "public" successor is retried with standard verification
// against a still-self-signed leaf, which can never pass), the error
// reported to the caller must be the *original* pin-mismatch error, not the
// retry's own failure — the original is what actually describes what the
// operator has to fix.
func TestDialWithTrust_RetryFailureSurfacesTheOriginalError(t *testing.T) {
	srv, cl := newCountingTLSServer(t)
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "public", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	opts := Options{
		Config:   &config.Config{TLSPin: "WRONG-PIN"},
		StateDir: dir,
	}
	conn, promote, err := dialWithTrust(context.Background(), opts, wsURL(t, srv))
	if err == nil {
		if conn != nil {
			conn.Close()
		}
		t.Fatal("dialWithTrust succeeded, want both the pinned dial and the public retry to fail")
	}
	if promote != nil {
		t.Error("promote func = non-nil on a failed dial+retry, want nil")
	}
	if !strings.Contains(err.Error(), "certificate pin mismatch") {
		t.Errorf("err = %q, want the original pin-mismatch error, not the retry's own failure", err)
	}
	if got := atomic.LoadInt32(&cl.accepts); got != 2 {
		t.Errorf("accepted connections = %d, want 2 (the original dial plus one retry)", got)
	}
}

// ── Defect B: promotion must survive the reconnect after it ───────────────

func TestPromoteTrust_SuccessorBecomesTheEffectivePolicy(t *testing.T) {
	// Clearing the rotation on promotion without recording the successor
	// anywhere left ResolveTrust falling back to agent.toml's tls_pin — the
	// pin of the certificate that had just been replaced. The agent survived
	// exactly one connection past the cutover and stranded on the next
	// reconnect, which is the failure F4 exists to eliminate.
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	cfg := &config.Config{TLSPin: "PIN-A"}

	if _, err := PromoteTrust(cfg, dir, 1); err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}

	got := ResolveTrust(cfg, dir)
	if got.Mode != tlsdial.ModeSelfSigned {
		t.Fatalf("Mode = %q, want %q", got.Mode, tlsdial.ModeSelfSigned)
	}
	if len(got.Pins) != 1 || got.Pins[0] != "PIN-B" {
		t.Errorf("Pins = %v, want [PIN-B] — the promoted successor, not agent.toml's replaced pin", got.Pins)
	}
}

func TestPromoteTrust_PublicSuccessorBecomesTheEffectivePolicy(t *testing.T) {
	// The cross-mode direction: after a self_signed -> public cutover the
	// agent must stop pinning entirely, or every later dial fails against a
	// publicly-trusted leaf it holds no digest for.
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "public", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	cfg := &config.Config{TLSPin: "PIN-A"}

	if _, err := PromoteTrust(cfg, dir, successorRetryIndex); err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}

	got := ResolveTrust(cfg, dir)
	if got.Mode != tlsdial.ModePublic {
		t.Errorf("Mode = %q, want %q after promoting a public successor", got.Mode, tlsdial.ModePublic)
	}
	if len(got.Pins) != 0 {
		t.Errorf("Pins = %v, want none in public mode", got.Pins)
	}
}

func TestResolveTrust_APromotedPolicyStillAcceptsANewSuccessor(t *testing.T) {
	// A second rotation after a first has been promoted must still produce a
	// two-candidate set, or an install can only ever rotate once.
	dir := t.TempDir()
	cfg := &config.Config{TLSPin: "PIN-A"}
	if err := config.SaveEffectiveTLSTrust(dir, config.TLSTrustPolicy{
		Mode: "self_signed", Pin: "PIN-B",
	}); err != nil {
		t.Fatalf("SaveEffectiveTLSTrust: %v", err)
	}
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-C", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	got := ResolveTrust(cfg, dir)
	if len(got.Pins) != 2 || got.Pins[0] != "PIN-B" || got.Pins[1] != "PIN-C" {
		t.Errorf("Pins = %v, want [PIN-B PIN-C]", got.Pins)
	}
}

// ── Defect A: readiness is reportable before the cutover ─────────────────

func TestSuccessorReady_TrueWhileARotationIsHeld(t *testing.T) {
	// The activation gate needs to know, BEFORE the certificate changes,
	// which agents already accept the successor. "Which policy did this
	// handshake match" cannot answer that: until the server actually serves
	// the successor, every agent matches the current policy, so a gate
	// keyed on a successor *match* can never open on the normal path.
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}

	if !SuccessorReady(dir) {
		t.Error("SuccessorReady = false while a successor is persisted, want true")
	}
}

func TestSuccessorReady_FalseWithNoRotation(t *testing.T) {
	if SuccessorReady(t.TempDir()) {
		t.Error("SuccessorReady = true with no rotation persisted, want false")
	}
}

func TestSuccessorReady_FalseWithoutAStateDir(t *testing.T) {
	// Nowhere durable to have persisted anything, so nothing can be held.
	if SuccessorReady("") {
		t.Error("SuccessorReady = true with no state dir, want false")
	}
}

func TestSuccessorReady_FalseAfterPromotion(t *testing.T) {
	// Once promoted there is no longer a successor pending; the agent is on
	// the new policy outright, which it reports as a "successor" match.
	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: "PIN-B", Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	if _, err := PromoteTrust(&config.Config{TLSPin: "PIN-A"}, dir, 1); err != nil {
		t.Fatalf("PromoteTrust: %v", err)
	}

	if SuccessorReady(dir) {
		t.Error("SuccessorReady = true after promotion, want false")
	}
}

// ── The peer certificate has to come from the connection ─────────────────

func TestDialWithTrust_ReportsTheMatchedPolicyOverTLS(t *testing.T) {
	// gorilla's Dialer builds its *http.Response by reading the handshake
	// response off the connection itself rather than going through
	// net/http's transport, so resp.TLS is nil however the dial was made.
	// Keying promotion on it meant the promote closure was never built: every
	// dial reported an empty tls_pin_kind, no agent ever promoted a
	// successor, and no agent ever reported convergence through the matched
	// kind. The peer certificate must be read from the connection.
	upgrader := websocket.Upgrader{}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		// Hold the connection open long enough for the dial to return.
		time.Sleep(50 * time.Millisecond)
	}))
	defer srv.Close()

	leaf := srv.Certificate()
	sum := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	pin := base64.StdEncoding.EncodeToString(sum[:])

	dir := t.TempDir()
	cfg := &config.Config{TLSPin: pin}
	u := "wss" + strings.TrimPrefix(srv.URL, "https")

	conn, promote, err := dialWithTrust(context.Background(), Options{Config: cfg, StateDir: dir}, u)
	if err != nil {
		t.Fatalf("dialWithTrust: %v", err)
	}
	defer conn.Close()

	if promote == nil {
		t.Fatal("promote closure is nil — the peer certificate was never inspected")
	}
	kind, err := promote()
	if err != nil {
		t.Fatalf("promote: %v", err)
	}
	if kind != "current" {
		t.Errorf("kind = %q, want current", kind)
	}
}

func TestDialWithTrust_MatchesTheSuccessorAfterACutover(t *testing.T) {
	// The same dial once the server has actually cut over: the configured pin
	// no longer matches, the advertised successor does, and that is what
	// promotion and the reported kind must both key on.
	upgrader := websocket.Upgrader{}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		time.Sleep(50 * time.Millisecond)
	}))
	defer srv.Close()

	leaf := srv.Certificate()
	sum := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	successorPin := base64.StdEncoding.EncodeToString(sum[:])

	dir := t.TempDir()
	if err := config.SaveTLSPinRotation(dir, config.TLSPinRotation{
		Mode: "self_signed", SuccessorPin: successorPin, Expiry: time.Now().Add(time.Hour),
	}); err != nil {
		t.Fatalf("SaveTLSPinRotation: %v", err)
	}
	cfg := &config.Config{TLSPin: "PIN-THE-SERVER-NO-LONGER-SERVES"}
	u := "wss" + strings.TrimPrefix(srv.URL, "https")

	conn, promote, err := dialWithTrust(context.Background(), Options{Config: cfg, StateDir: dir}, u)
	if err != nil {
		t.Fatalf("dialWithTrust: %v", err)
	}
	defer conn.Close()
	if promote == nil {
		t.Fatal("promote closure is nil after a successor match")
	}

	kind, err := promote()
	if err != nil {
		t.Fatalf("promote: %v", err)
	}
	if kind != "successor" {
		t.Errorf("kind = %q, want successor", kind)
	}
	// And it stuck: the next dial resolves the promoted policy alone.
	if got := ResolveTrust(cfg, dir); len(got.Pins) != 1 || got.Pins[0] != successorPin {
		t.Errorf("Pins = %v, want [%s]", got.Pins, successorPin)
	}
}
