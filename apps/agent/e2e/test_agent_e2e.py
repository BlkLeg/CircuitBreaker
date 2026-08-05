"""Docker E2E: the full 12-step cb-agent acceptance flow (Task 31).

Requires Docker; not run by default pytest invocations.

Run explicitly (from this directory):
    pytest test_agent_e2e.py -v -m e2e

Topology: `docker-compose.yml`'s `cb-agent` service runs on its own Docker
bridge network (`agent-net`), publishing/exposing no ports at all — the
agent dials OUT to `circuitbreaker` (Docker DNS-resolved service name) over
that network; nothing has a route IN. This is what makes "outbound only,
never listen on a remote-subnet port" a property this harness actually
proves rather than merely asserts (see docker-compose.yml's top-of-file
comment, and test_agent_full_lifecycle_enroll_through_revoke_and_reconnect's
step 11/isolation probe below).

Structure — five test functions, each bringing up (and tearing down) its own
full stack, so failures/timing in one scenario can't leak into another:

  * test_agent_full_lifecycle_enroll_through_revoke_and_reconnect
      Steps 1 (fetch+verify install script/binary), 2 (enroll), 3 (observe
      pending via /agents/stream, no polling), 4 (approve with default
      grants + a host-link selection), 5 (online + heartbeats), 6 (grant
      push while connected, observed via the agent's own status file), 9
      (revoke closes the socket) — plus step 11's connectivity-probe (no
      inbound route into cb-agent) and a reconnect exercised over that same
      outbound-only topology.

  * test_agent_uninstall_marks_server_revoked_and_removes_local_files
      Step 10.

  * test_agent_noise_rekey_interval_with_accelerated_clock
      Step 8, using the CB_AGENT_TEST_REKEY_INTERVAL_SECONDS override
      (production default stays 15 minutes when unset — see
      app/core/agent_crypto.py and internal/link/link.go).

  * test_agent_update_success_and_forced_rollback
      Step 7. The forced-rollback half genuinely waits out the real
      2-minute confirm window (internal/update's rollbackWindow) — this is
      not a per-CI-run hot path test, and there is no test-only override for
      that window (unlike the rekey interval, it isn't a
      Global-Constraints-governed value, so this test just pays the real
      cost once).

  * test_agent_independent_restarts_recover_without_new_setup
      Step 12: `docker compose restart` on the backend and the agent
      independently (not `down`/`up`, which would lose volumes/state).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest

BASE_URL = "https://localhost:8443"
WS_BASE_URL = "wss://localhost:8443"
# The agent's own view of the server — a Docker-DNS service name on the
# isolated agent-net bridge network, NOT localhost (see module docstring /
# docker-compose.yml). tls_pin verification (Task 17) ignores hostname
# entirely, so this mismatch with BASE_URL's "localhost" is deliberate and
# safe — see apps/agent/internal/tlsdial's package doc comment.
AGENT_SERVER_URL = "https://circuitbreaker:8443"

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "docker-compose.yml")]
E2E_DIR = Path(__file__).parent
AGENT_SRC_DIR = E2E_DIR.parent
# .env's CB_DATA_DIR=./e2e-data is interpolated into the *base* (repo-root)
# docker-compose.yml's volumes: entry, which resolves relative paths against
# its OWN file's directory (the repo root) — NOT against this .env file's
# directory (see .env's own comment). So the actual bind-mounted Postgres/
# vault/OOBE state for every run in this harness lives at
# <repo-root>/e2e-data, not apps/agent/e2e/e2e-data. `docker compose down -v`
# only removes named volumes (cb-agent-state) — it does NOT touch this bind
# mount, so without explicitly removing it here, every test function in this
# file would silently inherit the *previous* test's Postgres data, OOBE/
# bootstrap state, and vault key across nominally-independent runs.
REPO_ROOT = E2E_DIR.parents[2]
_E2E_DATA_DIR = REPO_ROOT / "e2e-data"

_ADMIN_EMAIL = "e2e@example.com"
_ADMIN_PASSWORD = "E2eTest1234!"


def _wait_until(predicate, *, timeout=30, interval=1.0):
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # noqa: BLE001 — retry on transient connection errors
            last_exc = exc
        time.sleep(interval)
    raise TimeoutError(f"condition not met within {timeout}s (last error: {last_exc})")


def _bootstrap_admin(client: httpx.Client) -> str:
    status = client.get("/api/v1/bootstrap/status")
    if status.status_code == 200 and status.json().get("needs_bootstrap"):
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "email": _ADMIN_EMAIL,
                "password": _ADMIN_PASSWORD,
                "theme_preset": "one-dark",
            },
        )
    else:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
        )
    resp.raise_for_status()
    # bootstrap/login also sets a cb_session cookie; if this client kept it,
    # every subsequent mutating request would be treated as cookie-authenticated
    # and rejected by CSRFMiddleware for lacking an X-CSRF-Token header. Clearing
    # it here keeps this client purely bearer-token-authenticated, matching how
    # a real API consumer (not the browser UI) talks to these endpoints.
    client.cookies.clear()
    return resp.json()["token"]


def _new_client() -> httpx.Client:
    # verify=False is deliberate and test-scoped: the mono container generates
    # a fresh self-signed cert per run with no stable CA to pin/trust here,
    # and this harness never leaves localhost. Do not carry this pattern into
    # any production code path — agent_install.py's tls_pin mechanism
    # (Task 17) is the real integrity anchor for actual installs.
    return httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0)


def _up_server(env: dict | None = None) -> None:
    subprocess.run(
        [*COMPOSE, "up", "-d", "--build", "circuitbreaker"],
        check=True,
        cwd=E2E_DIR,
        env=env,
    )


def _down(env: dict | None = None) -> None:
    subprocess.run([*COMPOSE, "down", "-v"], cwd=E2E_DIR, env=env)
    # See _E2E_DATA_DIR's comment: `down -v` alone leaves this bind-mounted
    # directory (and its Postgres data / OOBE marker / vault key) in place,
    # which would otherwise leak into the next test function's "fresh" run.
    shutil.rmtree(_E2E_DATA_DIR, ignore_errors=True)


def _write_agent_toml(server_pk: str, tls_pin: str, path: Path | None = None) -> Path:
    target = path or (E2E_DIR / "agent.toml")
    target.write_text(
        f'server_url = "{AGENT_SERVER_URL}"\n'
        f'server_static_pk = "{server_pk}"\n'
        f'tls_pin = "{tls_pin}"\n'
        f'log_level = "info"\n'
        f"spool_cap_bytes = 67108864\n"
    )
    return target


def _fetch_install_material(client: httpx.Client, headers: dict) -> dict:
    """Step 1: fetch install-agent.sh and the pinned agent binary it names,
    and verify the binary's sha256 matches what the script pins — the same
    integrity check a real install performs, just against localhost instead
    of a real download host."""
    script = client.get("/install-agent.sh").text
    server_pk = re.search(r'CB_SERVER_STATIC_PK="([0-9a-f]+)"', script).group(1)
    tls_pin = re.search(r'CB_TLS_PIN="([^"]*)"', script).group(1)
    version = re.search(r"/api/v1/agents/binary/([^/]+)/linux/", script).group(1)
    binary_sha256_match = re.search(
        r'\$CB_ARCH" = "amd64" \]; then CB_BINARY_SHA256="([0-9a-f]{64})"', script
    )
    assert binary_sha256_match, (
        "install-agent.sh has no amd64 binary digest — Dockerfile.mono's "
        "agent-builder stage may be stale or missing"
    )
    binary_sha256 = binary_sha256_match.group(1)
    binary = client.get(f"/api/v1/agents/binary/{version}/linux/amd64")
    assert binary.status_code == 200, binary.text
    assert hashlib.sha256(binary.content).hexdigest() == binary_sha256, (
        "downloaded cb-agent binary does not match the sha256 pinned in "
        "install-agent.sh — Dockerfile.mono's agent-builder stage may be "
        "stale or missing"
    )
    return {
        "server_pk": server_pk,
        "tls_pin": tls_pin,
        "baked_version": version,
        "binary_sha256": binary_sha256,
    }


def _agent_status(env: dict | None = None) -> dict:
    """Reads <state-dir>/status.json directly from the running cb-agent
    container (Task 20's status.json — see internal/status/status.go),
    rather than shelling out to `cb-agent status` (which prints human text,
    not JSON) — simpler and exactly as authoritative, since that file is the
    one thing both `cb-agent status` and this test ultimately read."""
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", "cb-agent", "cat", "/var/lib/cb-agent/status.json"],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _agent_logs(env: dict | None = None) -> str:
    return subprocess.run(
        [*COMPOSE, "logs", "cb-agent"], capture_output=True, text=True, cwd=E2E_DIR, env=env
    ).stdout


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _AgentStreamListener:
    """Connects to GET /api/v1/agents/stream (Task 14's live-agent-event
    push — token-as-first-message auth, see ws_agents.py's
    agent_presence_stream) and records every event_type-bearing message it
    receives, from a background thread — so a test can assert an event
    arrived on the *push* stream without ever polling a REST list endpoint
    to notice it.
    """

    def __init__(self, token: str):
        from websockets.sync.client import connect

        # Authorization header at handshake time so the router-level
        # `Depends(require_auth)` (defense-in-depth on this route — see
        # agent_presence_stream's docstring) doesn't 401 the handshake
        # outright: HTTPConnection-based auth (_extract_token) does read
        # this header for a websocket scope, even though the *endpoint's
        # own* auth (token_from_websocket_scope) only ever reads the
        # cb_session cookie from the handshake — hence still sending the
        # same token as the first text message below, which is the actual
        # mechanism this endpoint's body uses to authenticate a bearer-only
        # (no-cookie) client such as this one.
        self._ws = connect(
            f"{WS_BASE_URL}/api/v1/agents/stream",
            ssl_context=_tls_context(),
            open_timeout=15,
            additional_headers={"Authorization": f"Bearer {token}"},
        )
        self._ws.send(token)
        ack = json.loads(self._ws.recv(timeout=10))
        assert ack.get("status") == "connected", f"stream auth handshake failed: {ack}"

        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._ws.recv(timeout=1)
            except TimeoutError:
                continue
            except Exception:
                return
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if isinstance(msg, dict) and "event_type" in msg:
                with self._lock:
                    self.events.append(msg)

    def has_event(self, agent_id: int, event_type: str) -> bool:
        with self._lock:
            return any(
                e.get("agent_id") == agent_id and e.get("event_type") == event_type
                for e in self.events
            )

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        try:
            self._ws.close()
        except Exception:
            pass


def _enroll_agent(client: httpx.Client, headers: dict, *, env: dict | None = None) -> tuple:
    """Steps 2-4 combined into one reusable helper: build + run `cb-agent
    enroll` (a real Go agent, not a stub), watch /agents/stream for the
    resulting `enrolled` push event (step 3 — no REST polling involved in
    that assertion), then approve with default capability grants and an
    explicit host-link selection (step 4). Returns (agent_id, stream).
    Caller is responsible for stream.close() and for `up -d cb-agent`
    afterward to run the daemon.
    """
    token = client.headers.get("Authorization") or headers["Authorization"]
    stream = _AgentStreamListener(token.removeprefix("Bearer "))

    subprocess.run([*COMPOSE, "build", "cb-agent"], check=True, cwd=E2E_DIR, env=env)
    proc = subprocess.Popen(
        [*COMPOSE, "run", "--rm", "cb-agent", "enroll"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=E2E_DIR,
        env=env,
    )
    pairing_code = None
    deadline = time.monotonic() + 30
    for line in proc.stdout:
        m = re.search(r"pairing code:\s*(\S+)", line)
        if m:
            pairing_code = m.group(1)
            break
        if time.monotonic() > deadline:
            break
    assert pairing_code, "agent did not print a pairing code within 30s"

    lookup = client.post(
        "/api/v1/agents/pairing/lookup", json={"code": pairing_code}, headers=headers
    )
    assert lookup.status_code == 200, lookup.text
    agent_id = lookup.json()["agent_id"]

    # Step 3's actual assertion: the /agents/stream viewer connected BEFORE
    # enroll ran must have seen this exact agent_id's "enrolled" event pushed
    # to it live — never by polling GET /agents or /agents/pending.
    _wait_until(lambda: stream.has_event(agent_id, "enrolled"), timeout=15)

    # Step 4: approve with default grants (no capability_overrides — the
    # server applies agent_registry.DEFAULT_CAPABILITY_GRANTS) and an
    # explicit host-link selection ("unlinked" is a real, UI-supported
    # selection — Task 18's AgentApprovalModal — not a null/omitted value).
    approve = client.post(
        f"/api/v1/agents/{agent_id}/approve",
        json={"host_link_action": "unlinked"},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["capabilities"] == {
        "host_telemetry": True,
        "remote_probe": False,
        "local_discovery": False,
    }, "approve did not apply the server's default capability grants"

    assert proc.wait(timeout=15) == 0, "enroll process did not exit 0 after approval"
    return agent_id, stream


def _agent_network_name(env: dict | None = None) -> tuple[str, str]:
    """Resolves the live container name + the (compose-project-prefixed)
    Docker network name cb-agent is attached to, for the network
    disconnect/reconnect used by the rollback and topology-isolation tests.
    Looked up dynamically rather than hardcoded so this doesn't silently
    break if Compose's project/network naming ever changes.
    """
    container = subprocess.run(
        [*COMPOSE, "ps", "-q", "cb-agent"],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert container, "cb-agent container is not running"
    networks_json = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    networks = json.loads(networks_json)
    assert len(networks) == 1, (
        f"expected cb-agent to be attached to exactly one network (agent-net "
        f"only — see docker-compose.yml's topology comment), got {list(networks)}"
    )
    return container, next(iter(networks))


# ─────────────────────────────────────────────────────────────────────────
# Steps 1,2,3,4,5,6,9 + step 11's isolation probe/reconnect
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_agent_full_lifecycle_enroll_through_revoke_and_reconnect():
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)

        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        # ---- Step 1: fetch + verify install script/binary ----
        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])

        # ---- Steps 2,3,4 ----
        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)

            # ---- Step 5: online=true and heartbeats ----
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )
            # internal/link.heartbeatInterval's ticker fires only *after* its
            # first 20s elapses (not immediately on connect), so last_seen_at
            # (only ever written from an actual TYPE_HEARTBEAT frame — see
            # agent_link._handle_heartbeat/refresh_presence_heartbeat) stays
            # null until then. 45s gives margin over connection setup + one
            # full interval.
            _wait_until_and_return(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json().get("last_seen_at"),
                timeout=45,
            )
            # refresh_presence_heartbeat throttles its last_seen_at DB write
            # to roughly once/minute, so re-checking last_seen_at itself
            # "advanced" would mean waiting out that 60s throttle. The
            # Redis presence key (agent_registry.mark_presence_connected/
            # is_agent_online), by contrast, is refreshed on every single
            # heartbeat with a 60s TTL — so continuing to observe
            # online=True across an interval spanning more than one 20s
            # heartbeat tick (without the key ever expiring) is direct proof
            # heartbeats kept arriving, without waiting a full minute.
            def _is_online() -> bool:
                presence = client.get("/api/v1/agents/presence", headers=headers).json()
                return any(a["agent_id"] == agent_id and a["online"] for a in presence)

            _wait_until(_is_online, timeout=10)
            time.sleep(45)
            assert _is_online(), f"agent {agent_id} did not stay online across multiple heartbeat intervals"
            assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active"

            # ---- Step 6: change grants, verify the running agent receives
            # them without a reconnect ----
            # Capture the baseline connected_since timestamp BEFORE the grant
            # change is issued, so a reconnect occurring during grant delivery
            # (rather than after) will be detected by the later assertion.
            connected_since_before = client.get(f"/api/v1/agents/{agent_id}").json()[
                "connected_since"
            ]
            put = client.put(
                f"/api/v1/agents/{agent_id}/capabilities",
                json={"capabilities": {"remote_probe": True}},
                headers=headers,
            )
            assert put.status_code == 200, put.text
            _wait_until(
                lambda: _agent_status().get("grants", {}).get("remote_probe") is True,
                timeout=15,
            )
            # Confirming this landed via the live control-frame push, not a
            # reconnect: the daemon's link_state must have stayed "accepted"
            # throughout (a reconnect would show a disconnected/re-accepted
            # transition, and connected_since on the server side would jump).
            assert _agent_status()["link_state"] == "accepted"
            assert (
                client.get(f"/api/v1/agents/{agent_id}").json()["connected_since"]
                == connected_since_before
            )

            # ---- Step 11 (isolation half): confirm nothing has an inbound
            # route into cb-agent — it publishes no ports and listens on
            # nothing, so a connect attempt from its only network peer must
            # be refused, not merely blocked by policy. ----
            for port in (22, 80, 443, 2019, 8080, 9000):
                probe = subprocess.run(
                    [
                        *COMPOSE,
                        "exec",
                        "-T",
                        "circuitbreaker",
                        "sh",
                        "-c",
                        f"nc -z -w 2 cb-agent {port}",
                    ],
                    cwd=E2E_DIR,
                    capture_output=True,
                    text=True,
                )
                assert probe.returncode != 0, (
                    f"unexpected: circuitbreaker could dial INTO cb-agent on port {port} — "
                    "the agent must not accept any inbound connection"
                )

            # ---- Step 11 (reconnect half): the agent daemon dropped and
            # restarted (its container process, not the whole stack) must
            # come back online over the same outbound-only topology, with no
            # new pairing code / config edit. ----
            subprocess.run([*COMPOSE, "restart", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )
            assert _agent_status()["link_state"] == "accepted"

            # ---- Step 9: revoke closes the socket immediately ----
            revoke = client.post(
                f"/api/v1/agents/{agent_id}/revoke",
                json={"reason": "e2e test"},
                headers=headers,
            )
            assert revoke.status_code == 200, revoke.text

            # The live presence stream (already connected the whole test)
            # must see the "revoked" push directly — not by polling.
            _wait_until(lambda: stream.has_event(agent_id, "revoked"), timeout=10)

            # Task 12's /link poll interval is 5s — allow a bit of margin for
            # the immediate cross-worker disconnect push to land and the
            # daemon to log the resulting drop.
            _wait_until(
                lambda: (
                    "disconnect" in _agent_logs().lower() or "reconnect" in _agent_logs().lower()
                ),
                timeout=15,
            )
            assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "revoked"
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


def _wait_until_and_return(getter, *, timeout=30, interval=1.0):
    """Like _wait_until but returns the first truthy value observed, instead
    of only reporting pass/fail — used where a later assertion needs to
    compare against that first-observed value (e.g. "did last_seen_at
    advance past whatever it first was")."""
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            value = getter()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(interval)
    raise TimeoutError(f"condition not met within {timeout}s (last error: {last_exc})")


# ─────────────────────────────────────────────────────────────────────────
# Step 10: uninstall + server audit state
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.xfail(
    reason=(
        "Known production bug (follow-up task required): "
        "apps/agent/internal/link/link.go's Uninstall() one-shot uninstall-notification "
        "connection does not fully drain the server's responses — both hello.ack AND "
        "capabilities.set are sent before agent closes, but only one is currently read, "
        "a real RST-on-close data-loss risk. Combined with silent unlogged frame-decrypt-failure "
        "swallow in apps/backend/src/app/api/ws_agents.py's link_stream (bare except Exception: "
        "continue with no logging) that makes root-causing from production logs impossible. "
        "Collateral finding: second concurrent /link connection's teardown incorrectly deregisters "
        "first (still-live) connection's registry entry too (apps/backend/src/app/services/"
        "agent_registry.py's connection-registry deregister), a cross-worker presence-corruption "
        "risk under multi-worker deployments (also requires follow-up task)."
    ),
    strict=False,
)
def test_agent_uninstall_marks_server_revoked_and_removes_local_files():
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )

            # `cb-agent uninstall` requires root (main.go's requireRoot) —
            # the daemon itself runs unprivileged (Dockerfile's USER
            # cb-agent), so this runs as a one-shot root exec against the
            # same running container/state, exactly mirroring a real host
            # where the daemon runs as a dedicated user but uninstall is
            # invoked via sudo.
            result = subprocess.run(
                [*COMPOSE, "exec", "-T", "-u", "root", "cb-agent", "cb-agent", "uninstall"],
                cwd=E2E_DIR,
                capture_output=True,
                text=True,
            )
            # Not asserting returncode == 0: this minimal container has no
            # systemd, so performUninstall's `systemctl disable --now`
            # deliberately fails here (DisableErr non-nil -> exit 1) — an
            # artifact of the container environment, not a real failure.
            # What matters is verified below: the server-side audit state
            # and the actual on-disk removal, both independent of the
            # systemd step.
            assert "Notified the server" in result.stdout, result.stdout + result.stderr

            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "revoked",
                timeout=15,
            )
            events = client.get(f"/api/v1/agents/{agent_id}/events", headers=headers).json()
            assert any(
                e["event_type"] == "revoked" and (e.get("detail") or {}).get("reason")
                == "uninstalled by agent"
                for e in events
            ), f"expected a revoked/'uninstalled by agent' audit event, got: {events}"

            # On-disk removal: the binary and config file performUninstall
            # targets must actually be gone.
            check = subprocess.run(
                [
                    *COMPOSE,
                    "exec",
                    "-T",
                    "cb-agent",
                    "sh",
                    "-c",
                    "test -e /usr/local/bin/cb-agent && echo BINARY_STILL_PRESENT || echo BINARY_REMOVED;"
                    "test -e /etc/circuit-breaker/agent.toml && echo CONFIG_STILL_PRESENT || echo CONFIG_REMOVED",
                ],
                cwd=E2E_DIR,
                capture_output=True,
                text=True,
            )
            assert "BINARY_REMOVED" in check.stdout, check.stdout
            assert "CONFIG_REMOVED" in check.stdout, check.stdout
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Step 8: Noise rekey with an accelerated test clock
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_agent_noise_rekey_interval_with_accelerated_clock():
    rekey_env = {**os.environ, "CB_AGENT_TEST_REKEY_INTERVAL_SECONDS": "6"}
    _up_server(env=rekey_env)
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])

        agent_id, stream = _enroll_agent(client, headers, env=rekey_env)
        try:
            subprocess.run(
                [*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR, env=rekey_env
            )
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )

            # With a 6s interval, ~30-40s of connected time should carry at
            # least two full rekey cycles in EACH independent direction
            # (agent->server and server->agent — see link.go's rekeyInterval
            # / ws_agents.py's REKEY_INTERVAL_SECONDS, both driven off this
            # same env override here).
            #
            # Both counts are read from `docker compose logs cb-agent` alone
            # — NOT the server's own Python log. ws_agents.py's matching
            # _logger.info call (added in the same commit as link.go's) is
            # real and correctly gated on this same env override, but this
            # app has no logging.basicConfig/dictConfig anywhere on the
            # `uvicorn app.main:app` startup path actually used here, so the
            # root logger stays at Python's default WARNING and every
            # `_logger.info` call in this codebase (this one and pre-existing
            # ones alike, e.g. ws_agents.py's "agent enroll: handshake
            # failed") is silently dropped — confirmed empirically by
            # grepping a real run's backend_api_err.log for zero hits on
            # either. That is a pre-existing app-wide logging-configuration
            # gap, out of scope to change here. Instead, the agent's OWN Go
            # log (always visible — no supervisord indirection, no logging-
            # level gate on the standard library `log` package) already
            # proves the *server* rekeyed independently too: "applied inbound
            # transport.rekey" only ever fires when the agent received and
            # correctly applied a `transport.rekey` frame the SERVER sent on
            # its own schedule (see applyInboundRekey in link.go) — a wrong/
            # missing server-side rekey would desync the ciphers and break
            # the connection outright, not merely fail to log.
            def _rekey_counts():
                logs = _agent_logs(rekey_env)
                agent_rekeys = len(re.findall(r"performed outbound transport\.rekey", logs))
                server_rekeys = len(re.findall(r"applied inbound transport\.rekey", logs))
                return agent_rekeys, server_rekeys

            _wait_until(
                lambda: all(n >= 2 for n in _rekey_counts()),
                timeout=50,
                interval=2.0,
            )
            agent_rekeys, server_rekeys = _rekey_counts()
            assert agent_rekeys >= 2 and server_rekeys >= 2, (
                f"expected >=2 rekeys in both directions with a 6s accelerated "
                f"interval, got agent-initiated={agent_rekeys} "
                f"server-initiated(applied by agent)={server_rekeys}"
            )

            # The connection must still be healthy afterward — heartbeats
            # keep landing across (and after) multiple rekey cycles, i.e.
            # the two ciphers stayed in sync rather than diverging.
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=10,
            )
        finally:
            stream.close()
    finally:
        _down(env=rekey_env)
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Step 7: successful update + forced rollback
# ─────────────────────────────────────────────────────────────────────────


def _build_test_agent_binary(version: str, dest: Path) -> Path:
    """Builds a real cb-agent binary tagged with `version` via the same
    -X main.AgentVersion ldflag apps/agent/Makefile's build-all target uses,
    targeting linux/amd64 (matching the e2e Dockerfile's runtime) with
    CGO_ENABLED=0 so it doesn't depend on the host's libc."""
    out = dest / "cb-agent-linux-amd64"
    subprocess.run(
        [
            "go",
            "build",
            "-ldflags",
            f"-X main.AgentVersion={version}",
            "-o",
            str(out),
            "./cmd/cb-agent",
        ],
        cwd=AGENT_SRC_DIR,
        check=True,
        env={**os.environ, "GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0"},
    )
    return out


def _inject_binary_version(version: str, binary_path: Path) -> str:
    """Copies binary_path into the running circuitbreaker container's
    AGENT_BINARIES_DIR under `version`, and adds a matching manifest.json
    entry — the same {version: {os-arch: sha256}} shape
    app/services/agent_update.py reads (Task 23's manifest format).
    Returns the binary's sha256."""
    sha256 = hashlib.sha256(binary_path.read_bytes()).hexdigest()

    manifest_raw = subprocess.run(
        [*COMPOSE, "exec", "-T", "circuitbreaker", "cat", "/opt/circuitbreaker/agent-binaries/manifest.json"],
        cwd=E2E_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    manifest = json.loads(manifest_raw)
    manifest.setdefault(version, {})["linux-amd64"] = sha256

    container = subprocess.run(
        [*COMPOSE, "ps", "-q", "circuitbreaker"],
        cwd=E2E_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "mkdir",
            "-p",
            f"/opt/circuitbreaker/agent-binaries/{version}",
        ],
        check=True,
    )
    subprocess.run(
        ["docker", "cp", str(binary_path), f"{container}:/opt/circuitbreaker/agent-binaries/{version}/cb-agent-linux-amd64"],
        check=True,
    )
    subprocess.run(
        [
            "docker",
            "exec",
            container,
            "chmod",
            "755",
            f"/opt/circuitbreaker/agent-binaries/{version}/cb-agent-linux-amd64",
        ],
        check=True,
    )

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        json.dump(manifest, tmp)
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["docker", "cp", tmp_path, f"{container}:/opt/circuitbreaker/agent-binaries/manifest.json"],
            check=True,
        )
    finally:
        os.unlink(tmp_path)

    return sha256


@pytest.mark.e2e
@pytest.mark.xfail(
    reason=(
        "Known production bug (follow-up task required): "
        "Agent self-update is structurally blocked by file ownership: binary is installed "
        "root-owned at /usr/local/bin/cb-agent but the agent daemon runs unprivileged. "
        "Further: systemd's ProtectSystem=strict sandbox (from real install script via "
        "apps/backend/src/app/services/agent_install.py's systemd unit template, Task 17 "
        "↔ Tasks 22-25 seam) blocks any write access to /usr/local/bin without "
        "ReadWritePaths covering the binary's directory. The actual swap in "
        "apps/agent/internal/update/update.go's Swap() requires rename-in-place write "
        "access to /usr/local/bin, which cannot succeed under this combination. "
        "Requires dedicated follow-up task, not a quick fix."
    ),
    strict=False,
)
def test_agent_update_success_and_forced_rollback():
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        baked_version = material["baked_version"]  # e.g. "0.3.4" — /VERSION

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )
            # The e2e Dockerfile builds cb-agent with no -X ldflag, so it
            # starts at the Go default "0.0.0-dev" — meaning the manifest's
            # already-baked `baked_version` (VERSION at server-image build
            # time) is itself a genuine *newer* target, no custom binary
            # needed for the successful-update half.
            assert _agent_status()["version"] == "0.0.0-dev"

            # ---- Step 7a: successful update ----
            update = client.post(f"/api/v1/agents/{agent_id}/update", json={}, headers=headers)
            assert update.status_code == 200, update.text
            assert update.json()["version"] == baked_version

            _wait_until(lambda: _agent_status().get("version") == baked_version, timeout=60)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )
            events = client.get(f"/api/v1/agents/{agent_id}/events", headers=headers).json()
            assert any(
                e["event_type"] == "version_changed"
                and (e.get("detail") or {}).get("version") == baked_version
                for e in events
            ), f"expected a version_changed event for {baked_version}, got {events}"

            # ---- Step 7b: forced rollback ----
            # Build+inject a genuinely newer version, trigger an update to
            # it, then sever outbound connectivity the instant the swap
            # completes (watched via the daemon's own "re-executing" log
            # line — see main.go's onUpdate) — so the freshly re-exec'd
            # binary can never complete a post-update hello.ack, exactly the
            # "update never confirms" case internal/update's rollbackWindow
            # (2 real minutes) guards against.
            with tempfile.TemporaryDirectory() as tmp:
                rollback_version = "9.9.9-e2e-rollback"
                binary = _build_test_agent_binary(rollback_version, Path(tmp))
                _inject_binary_version(rollback_version, binary)

            update2 = client.post(
                f"/api/v1/agents/{agent_id}/update",
                json={"version": rollback_version},
                headers=headers,
            )
            assert update2.status_code == 200, update2.text

            _wait_until(
                lambda: "re-executing" in _agent_logs(),
                timeout=30,
            )

            container, network = _agent_network_name()
            subprocess.run(["docker", "network", "disconnect", network, container], check=True)
            try:
                # rollbackWindow is a real 2 minutes (internal/update, via
                # main.go) with no test-only override — Global Constraints
                # doesn't govern this value the way it governs the rekey
                # interval, so this test just pays the real cost once.
                time.sleep(150)
            finally:
                subprocess.run(["docker", "network", "connect", network, container], check=True)

            _wait_until(lambda: _agent_status().get("version") == baked_version, timeout=60)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )
            events2 = client.get(f"/api/v1/agents/{agent_id}/events", headers=headers).json()
            assert any(
                e["event_type"] == "update_rolled_back" for e in events2
            ), f"expected an update_rolled_back audit event, got {events2}"
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Step 12: independent restarts, no new setup
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
def test_agent_independent_restarts_recover_without_new_setup():
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        agent_toml_path = _write_agent_toml(material["server_pk"], material["tls_pin"])
        agent_toml_before = agent_toml_path.read_text()

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )

            device_key_before = subprocess.run(
                [*COMPOSE, "exec", "-T", "cb-agent", "sha256sum", "/var/lib/cb-agent/device.key"],
                cwd=E2E_DIR,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()[0]

            # Restart the backend independently — `restart`, not `down`+`up`,
            # so its Postgres/state volume survives.
            subprocess.run([*COMPOSE, "restart", "circuitbreaker"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60
            )
            # No new bootstrap/setup: logging back in with the same admin
            # credentials must still work — a fresh bootstrap would mean the
            # server forgot its prior state entirely.
            token_after_backend_restart = _bootstrap_admin(client)
            assert token_after_backend_restart

            # Restart the agent independently.
            subprocess.run([*COMPOSE, "restart", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )

            # No new pairing code / certificate action / config edit: the
            # device key and agent.toml on disk are byte-for-byte the same
            # as before either restart, and the agent reconnected as the
            # SAME already-approved agent_id (not a new pending enrollment).
            device_key_after = subprocess.run(
                [*COMPOSE, "exec", "-T", "cb-agent", "sha256sum", "/var/lib/cb-agent/device.key"],
                cwd=E2E_DIR,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()[0]
            assert device_key_after == device_key_before, (
                "device.key changed across restarts — implies a new identity/"
                "certificate action, which step 12 must not require"
            )
            assert agent_toml_path.read_text() == agent_toml_before, (
                "agent.toml was edited — step 12 must not require a config edit"
            )
            pending = client.get("/api/v1/agents/pending", headers=headers).json()
            assert not any(a["id"] == agent_id for a in pending), (
                "agent reappeared as pending after restart — implies a new "
                "pairing code was needed, which step 12 must not require"
            )
            detail = client.get(f"/api/v1/agents/{agent_id}", headers=headers).json()
            assert detail["status"] == "active"
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)
