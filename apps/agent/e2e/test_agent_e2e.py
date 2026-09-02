"""Docker E2E: the full 12-step cb-agent acceptance flow (Task 31).

Requires Docker; not run by default pytest invocations.

Run explicitly (from this directory):
    pytest test_agent_e2e.py -v -m e2e

Topology: `docker-compose.yml`'s `cb-agent` service runs in its own network
namespace on Docker bridge networks, publishing/exposing no ports at all —
`agent-net`, where it dials OUT to `circuitbreaker` (Docker DNS-resolved
service name), and `probe-net`, where the remote-probe target lives and
which `circuitbreaker` is deliberately NOT attached to. Nothing has a route
IN to the agent on either. That is what makes "outbound only, never listen
on a remote-subnet port" a property this harness actually proves rather than
merely asserts (see docker-compose.yml's top-of-file comment, and
test_agent_full_lifecycle_enroll_through_revoke_and_reconnect's step
11/isolation probe below) — and what makes "the backend cannot reach this
target, so a passing check can only have come from the agent" provable too.

Slice 4 (Task 31, D-12) pins every subnet to a literal /24 and adds three
things to that picture: `probe-target-new`, a second host started mid-test on
the subnet the agent already knows; `late-net`, whose fixture target and agent
attachment both arrive MID-TEST so a whole directly connected subnet can appear
on an already-running agent; and a second agent, `cb-agent-2`, on its own
outbound network (`agent-net-2`), its own fixture subnet (`probe-net-2`) and
its own state volume. The two agents share no network and no state, which is
what makes per-agent provenance falsifiable rather than merely recorded. The
pinned numbers all live in one constants block below; `_AGENT_TOPOLOGY`
records which networks each agent service may be on.

Structure — twelve test functions, each bringing up (and tearing down) its own
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

  * test_agent_host_telemetry_first_sample_catchup_and_disable
      Task 20: the host-telemetry outbound path end to end — collector ->
      spool -> Noise -> dispatch_frame -> AgentHostSample -> REST. Proves
      first-sample acceptance, unlinked retention + collector readiness,
      bounded outage catch-up with original collected_at values and no
      duplicate rows, a live cadence change with no reconnect, and that
      revoking host_telemetry both stops collection and actively rewrites
      every host.* readiness row to "disabled" (D-4). Driven at
      interval_s: 10 (the production minimum, internal/capability) per D-13,
      restoring 30 before it exits.

  * test_agent_black_hole_partition_is_detected_and_spools
      F-5: a severed route rather than a stopped server — `docker network
      disconnect`, which closes no socket and produces silence instead of a
      write error. Proves internal/link's steady-state read deadline takes
      the link down on that silence and diverts collection into the spool,
      which is the one outage shape nothing exercised before. Pays the real
      60s deadline; no test-only override.

  * test_remote_probe_assignment_execution_and_unavailability
      Slice 3 §9 steps 1-6 and 9-11, in one stack lifetime: an ICMP, TCP,
      HTTP and DNS monitor executed by the agent against a target the
      backend provably cannot reach; the same events/history/uptime/retry
      semantics a server-executed check produces; an unavailable vantage
      that retains target state and writes no avail=0 sample; the warning
      clearing on reconnect; a reassignment that retires the in-flight run
      so the old vantage's result is inert; and an explicit return to server
      execution. Steps 7 and 8 (scope narrowing, fairness under concurrency)
      are unit/integration-covered elsewhere and are not repeated here.

  * test_e2e_harness_topology_is_pinned_and_two_agents_stay_isolated
      Slice 4 Task 31 (D-12): the harness's own preconditions, asserted
      before Tasks 32-33 rest on them. Every subnet is the pinned one (read
      back live from Docker, not trusted from the compose file); a subnet
      can materialise on an already-enrolled agent and reach the server's
      derived scope on the next hello with no CIDR typed anywhere;
      `_agent_network_name` still resolves the route to the server across
      both of the topology shapes that are now legal; the two agents have
      distinct ids, device keys, attachments and routing tables, neither
      seeing the other's fixture subnet; and the backend can reach none of
      the three fixture subnets over ICMP or TCP — the negative every later
      discovery assertion is worth exactly as much as.

  * test_agent_zero_configuration_discovery_import_and_replay
      Slice 4 Task 32 (§8 steps 1-7): the slice's central claim, end to end.
      One install command and one ordinary approval — no CIDR typed anywhere
      — put both directly connected subnets into the server's derived scope,
      mint one system-managed profile per subnet (D-12), and start an initial
      scan by themselves; the fixture's finding is pushed incrementally on
      the Discovery page's own WebSocket before the job's terminal event,
      lands in the ordinary review queue, imports as exactly one Hardware
      row, and survives a real replay of the agent's own spooled findings
      with no duplicate result and no duplicate Hardware row. The backend is
      made to fail at reaching 10.77.0.10 over both ICMP and TCP before and
      after, so the only possible source of that row is the agent.

  * test_agent_discovery_capability_disable_cancels_and_late_findings_die
      Slice 4 Task 33 (§8 step 8): the capability is turned off in the middle
      of a running sweep while the agent is partitioned from the server, so
      the `discovery.cancel` provably never arrives. The agent goes on
      scanning and spooling findings for a dispatch the server has already
      closed; when its link comes back it delivers every one of them, and not
      one becomes a row. What that separates is the server ENFORCING the
      cancellation from the agent merely OBEYING it — outcomes that leave an
      identical `scan_results` table when the cancel does get through.

  * test_agent_discovery_reconnects_per_agent_and_requeues_only_changes
      Slice 4 Task 33 (§8 steps 9-11): both ends restart and the agent's
      address moves inside its own subnet, and it comes back with no
      re-enrollment, no second profile for the subnet whose address changed,
      and its six-hourly cadence still registered; a second agent on its own
      isolated subnet keeps its findings and its scope entirely its own, with
      `scan_results.discovery_agent_id` read straight out of the database
      because that provenance column is deliberately not on the wire; and the
      recurring sweeps tell the three cases apart — a device the inventory
      already knows, a device that genuinely just appeared, and a device whose
      agent-reported hostname disagrees with the name an operator gave it,
      which stays pending and never renames anything.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
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

# ─────────────────────────────────────────────────────────────────────────
# docker-compose.yml's pinned topology, in one place
# ─────────────────────────────────────────────────────────────────────────
#
# Every network in the harness has a hand-pinned subnet (see the compose
# file's own topology note for why each one exists). Restating the numbers
# here is unavoidable — Docker owns them at runtime, this file owns the
# assertions about them — so they live in ONE block rather than scattered
# through the tests, and `_network_subnet()` re-reads the live network so a
# drift between the two halves fails as a named assertion instead of as an
# unexplained timeout somewhere downstream.
#
# The compose *service* names are constants for the same reason: with two
# agent services and three fixture targets, a bare "cb-agent" string literal
# inside a helper is a silent single-agent assumption.

_AGENT_SERVICE = "cb-agent"
_AGENT_2_SERVICE = "cb-agent-2"

# cb-agent's route to the server. Pinned to a /24 by Slice 4 D-12: as an
# unpinned bridge Docker gave it a /16, whose 65 534 addresses exceed the
# local_discovery grant's max_addresses_per_job on their own, so the agent's
# own directly connected subnet could never be dispatched as a discovery
# target.
_AGENT_NET = "agent-net"
_AGENT_NET_CIDR = "10.88.0.0/24"

# cb-agent's isolated fixture subnet; circuitbreaker is not on it.
_PROBE_NET = "probe-net"
_PROBE_NET_CIDR = "10.77.0.0/24"
_PROBE_TARGET_SERVICE = "probe-target"
_PROBE_TARGET_NAME = "probe-target"
_PROBE_TARGET_IP = "10.77.0.10"

# A second host on probe-net, started mid-test: a genuinely new device on a
# subnet the agent already knows and has already scanned, as distinct from
# late-net's whole-new-subnet case. Nothing brings it up at stack start.
_PROBE_TARGET_NEW_SERVICE = "probe-target-new"
_PROBE_TARGET_NEW_IP = "10.77.0.20"

# The subnet that appears LATE: `late-target` is started, and cb-agent
# attached to late-net, only after cb-agent is already enrolled, approved and
# running. See `_attach_agent_to_late_net`.
_LATE_NET = "late-net"
_LATE_NET_CIDR = "10.66.0.0/24"
_LATE_TARGET_SERVICE = "late-target"
_LATE_TARGET_IP = "10.66.0.10"

# The second agent's route to the server, and its own isolated fixture
# subnet. Neither circuitbreaker nor cb-agent is on probe-net-2.
_AGENT_2_NET = "agent-net-2"
_AGENT_2_NET_CIDR = "10.89.0.0/24"
_PROBE_NET_2 = "probe-net-2"
_PROBE_NET_2_CIDR = "10.78.0.0/24"
_PROBE_TARGET_2_SERVICE = "probe-target-2"
_PROBE_TARGET_2_IP = "10.78.0.10"

# Which Docker networks each agent service may be attached to, and which one
# carries its route to the SERVER. Keyed by compose service name.
#
# `required` is what a caller may rely on being present; `allowed` bounds what
# may be present at all. Both halves are load-bearing, and they catch opposite
# failures — both of which would otherwise leave a *passing* test:
#
#   * falling below `required` means a route this suite's proofs depend on has
#     silently gone away. cb-agent losing probe-net turns "the backend cannot
#     reach the target, so only the agent can have" into "nobody can reach the
#     target", and every check simply fails for the wrong reason.
#   * rising above `allowed` — `default` above all, or the other agent's
#     networks — means the isolation those same proofs rest on has silently
#     been widened, and an agent-executed result becomes indistinguishable
#     from a server-executed one.
#
# This was a single exact-set assertion (`== {"agent-net", "probe-net"}`) up
# to Slice 4. An exact set is now wrong rather than merely strict: cb-agent
# legitimately GAINS late-net partway through a test — that is the
# zero-configuration trigger under test, not a topology bug — and cb-agent-2
# has a different set entirely. Required-subset plus allowed-superset keeps
# every failure the exact set used to catch while admitting the two shapes
# that are now legitimate.
_AGENT_TOPOLOGY = {
    _AGENT_SERVICE: {
        "server_net": _AGENT_NET,
        "required": frozenset({_AGENT_NET, _PROBE_NET}),
        "allowed": frozenset({_AGENT_NET, _PROBE_NET, _LATE_NET}),
    },
    _AGENT_2_SERVICE: {
        "server_net": _AGENT_2_NET,
        "required": frozenset({_AGENT_2_NET, _PROBE_NET_2}),
        "allowed": frozenset({_AGENT_2_NET, _PROBE_NET_2}),
    },
}


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


def _read_setup_token_from_container() -> str:
    """The one-time bootstrap setup token, read from inside the container.

    SEC-4 made `/api/v1/bootstrap/initialize` require a token, and the server
    writes the generated one to `$CB_DATA_DIR/bootstrap-setup-token`
    (auth_service._write_bootstrap_token_file). That path only means anything
    *inside* the mono container, where Dockerfile.mono pins CB_DATA_DIR=/data.
    Reading it from the host — as this helper did — is wrong twice over:

      * `CB_DATA_DIR` is declared in this directory's `.env`, which only the
        `docker compose` CLI reads. It is never exported into the pytest
        process, so `os.environ.get("CB_DATA_DIR", "/data")` always fell
        through to the literal "/data" — a container path resolved against the
        host. On a CI runner nothing is mounted there, so all 11 tests died on
        `FileNotFoundError` before their first assertion — and a developer box
        fares no better: /data there is either absent or a *different*, real
        deployment's data directory, so the read fails or quietly picks up a
        foreign token. This never worked anywhere; the composed job simply
        never got far enough to show it until the httpx fix let collection run.
      * Correcting the host path to the actual bind mount (`_E2E_DATA_DIR`)
        would not be enough on its own: the file is 0600 and owned by the
        container's `breaker` user (uid 1000), so a host-side read would still
        only succeed for a developer who happens to share that uid, and never
        for CI's `runner`. That is why this reads the file rather than
        re-pointing it.

    Asking the container for its own file sidesteps both: the path is correct
    by construction (resolved from the container's own CB_DATA_DIR, exactly as
    entrypoint-mono.sh and auth_service do), and `exec` runs as root — the mono
    runtime deliberately starts as root (Dockerfile.mono) — which can read a
    breaker-owned 0600 file. No CB_SETUP_TOKEN is injected, so the harness
    keeps exercising the default generated-token path a real install uses.

    Retried rather than read once: `bootstrap_status` only writes the file on a
    request that finds an `AppSettings` row, and `_up_server`'s caller waits for
    the endpoint to return 200, not for that row to exist. The window is short
    and usually already closed, but it is real.
    """
    result: dict[str, str] = {}

    def _read() -> bool:
        proc = subprocess.run(
            [
                *COMPOSE, "exec", "-T", "circuitbreaker",
                "sh", "-c", 'cat "${CB_DATA_DIR:-/data}/bootstrap-setup-token"',
            ],
            cwd=E2E_DIR,
            capture_output=True,
            text=True,
        )
        token = proc.stdout.strip()
        if proc.returncode != 0 or not token:
            raise RuntimeError(
                f"setup token not readable yet (rc={proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        result["token"] = token
        return True

    _wait_until(_read, timeout=60)
    return result["token"]


def _bootstrap_admin(client: httpx.Client) -> str:
    status = client.get("/api/v1/bootstrap/status")
    if status.status_code == 200 and status.json().get("needs_bootstrap"):
        # CB_SETUP_TOKEN still wins when set: it is auth_service's own operator
        # escape hatch (ensure_bootstrap_token), and honouring it here lets a
        # run pin a known token without patching the harness.
        setup_token = os.environ.get("CB_SETUP_TOKEN", "").strip()
        if not setup_token:
            setup_token = _read_setup_token_from_container()
        resp = client.post(
            "/api/v1/bootstrap/initialize",
            json={
                "setup_token": setup_token,
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
    # Establish the clean baseline on the way IN, not only on the way out.
    # Every test ends with `_down()` in a `finally`, but an interrupted run —
    # Ctrl-C, a pytest timeout, a killed CI job — never reaches it, and what it
    # leaves behind is not inert. A surviving `cb-agent-state` volume still
    # holds an enrolled device key, so the next `cb-agent enroll` is answered
    # "already active" and never prints a pairing code; a surviving
    # `agent.toml/` directory (see `_write_agent_toml`) kills the agent at
    # config load. Both surface minutes later as an unrelated-looking timeout
    # in whichever test happened to run first. Each test is only independent of
    # how the previous one *ended* if it starts by saying so.
    _down(env)
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
    # Docker creates a *directory* at a bind-mount source that does not exist,
    # and docker-compose.yml mounts this exact path into both agents. Each
    # test's `finally` unlinks the file, so any container started between that
    # unlink and the next `_write_agent_toml` — an interrupted run, a stray
    # `compose up` — leaves a root-owned `agent.toml/` here. The agent then
    # exits with "load /etc/circuit-breaker/agent.toml: is a directory" and,
    # because that output goes to `_enroll_agent`'s pipe, the test reports only
    # a pairing-code timeout. Clear it before writing rather than letting the
    # next `write_text` fail with an equally opaque IsADirectoryError.
    if target.is_dir() and not target.is_symlink():
        target.rmdir()
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


def _agent_status(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> dict:
    """Reads <state-dir>/status.json directly from the running cb-agent
    container (Task 20's status.json — see internal/status/status.go),
    rather than shelling out to `cb-agent status` (which prints human text,
    not JSON) — simpler and exactly as authoritative, since that file is the
    one thing both `cb-agent status` and this test ultimately read.

    `service` selects which agent container is being asked. It exists because
    the two agents have SEPARATE state volumes (docker-compose.yml): status.json
    is per-agent state, so there is no such thing as "the" agent's status once a
    second agent is running."""
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", service, "cat", "/var/lib/cb-agent/status.json"],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _agent_logs(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> str:
    return subprocess.run(
        [*COMPOSE, "logs", service], capture_output=True, text=True, cwd=E2E_DIR, env=env
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
        # Two websockets deprecations are load-bearing here, because pytest.ini's
        # `filterwarnings = error` makes both fatal and e2e.yml pins no version:
        #
        #   * `ssl`, not `ssl_context` — renamed in 13.0.
        #   * `connect()` entered as a context manager — 17.0 deprecated holding
        #     the return value directly. This listener outlives its constructor,
        #     so it cannot use a `with` block; an ExitStack held on the instance
        #     is the same contract with the lifetime this class actually has,
        #     and `close()` unwinds it. `legacy=True` would also silence it, but
        #     that switch exists to be removed.
        self._stack = contextlib.ExitStack()
        self._ws = self._stack.enter_context(
            connect(
                f"{WS_BASE_URL}/api/v1/agents/stream",
                ssl=_tls_context(),
                open_timeout=15,
                additional_headers={"Authorization": f"Bearer {token}"},
            )
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
            # Unwinds the ExitStack the constructor opened, which is what closes
            # the socket; `self._ws.close()` would leave the stack un-exited.
            self._stack.close()
        except Exception:
            pass


def _enroll_agent(
    client: httpx.Client,
    headers: dict,
    *,
    env: dict | None = None,
    service: str = _AGENT_SERVICE,
) -> tuple:
    """Steps 2-4 combined into one reusable helper: build + run `cb-agent
    enroll` (a real Go agent, not a stub), watch /agents/stream for the
    resulting `enrolled` push event (step 3 — no REST polling involved in
    that assertion), then approve with default capability grants and an
    explicit host-link selection (step 4). Returns (agent_id, stream).
    Caller is responsible for stream.close() and for `up -d <service>`
    afterward to run the daemon.

    `service` picks which agent container enrolls. The second agent goes
    through this identical path — same binary, same agent.toml, same default
    grants, no argument distinguishing it — because "a second agent needs no
    special handling" is the property Slice 4 §8 step 10 is really claiming;
    a bespoke enrollment path for it would assume that claim rather than test
    it.
    """
    token = client.headers.get("Authorization") or headers["Authorization"]
    stream = _AgentStreamListener(token.removeprefix("Bearer "))

    subprocess.run([*COMPOSE, "build", service], check=True, cwd=E2E_DIR, env=env)
    proc = subprocess.Popen(
        [*COMPOSE, "run", "--rm", service, "enroll"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=E2E_DIR,
        env=env,
    )
    # Every line the agent printed, kept so a failure here can say WHY. Without
    # it the only thing this helper can report is "no pairing code in 30s",
    # which is the symptom of every possible enroll failure — a bad tls_pin, a
    # config file Docker turned into a directory, an already-enrolled state
    # volume that makes the server answer "active" instead of issuing a code —
    # and distinguishes none of them. The output is on this pipe and nowhere
    # else: `stderr=STDOUT` means it never reaches pytest's captured output.
    transcript: list[str] = []
    pairing_code = None
    deadline = time.monotonic() + 30
    # `for line in proc.stdout` blocks until a line arrives, so the deadline
    # below is only reached if the agent is talking. A silent agent — one that
    # died before its first write, or one waiting on something that will never
    # come — would hang this loop forever. The watchdog turns that into the
    # same diagnosable assertion failure as every other enroll fault.
    watchdog = threading.Timer(35, proc.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        for line in proc.stdout:
            transcript.append(line.rstrip())
            m = re.search(r"pairing code:\s*(\S+)", line)
            if m:
                pairing_code = m.group(1)
                break
            if time.monotonic() > deadline:
                break
    finally:
        watchdog.cancel()
    assert pairing_code, (
        f"`cb-agent enroll` ({service}) printed no pairing code within 30s. It said:\n"
        + ("\n".join(transcript) if transcript else "(nothing at all)")
    )

    lookup = client.post(
        "/api/v1/agents/pairing/lookup", json={"code": pairing_code}, headers=headers
    )
    assert lookup.status_code == 200, lookup.text
    agent_id = lookup.json()["agent_id"]

    # Step 3's actual assertion: the /agents/stream viewer connected BEFORE
    # enroll ran must have seen this exact agent_id's "enrolled" event pushed
    # to it live — never by polling GET /agents or /agents/pending.
    _wait_until(lambda: stream.has_event(agent_id, "enrolled"), timeout=15)

    # Step 4: approve with default grants (no `capabilities` in the body — the
    # server applies its own CAPABILITY_DEFINITIONS registry, D-10: all three
    # enabled) and an explicit host-link selection ("unlinked" is a real,
    # UI-supported selection — Task 18's AgentApprovalModal — not a
    # null/omitted value).
    approve = client.post(
        f"/api/v1/agents/{agent_id}/approve",
        json={"host_link_action": "unlinked"},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    # `AgentRead.capabilities` is the canonical structured wire shape
    # (`{name: {enabled, config}}` with server-normalized config), never a bare
    # boolean — see the "Canonical capability wire shape" Global Constraint.
    assert approve.json()["capabilities"] == {
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        },
        "remote_probe": {
            "enabled": True,
            "config": {
                "max_concurrent": 20,
                "scope_mode": "direct_private",
                "excluded_cidrs": [],
                "additional_cidrs": [],
                "additional_hostnames": [],
            },
        },
        "local_discovery": {
            "enabled": True,
            "config": {
                "scope_mode": "direct_private",
                "excluded_cidrs": [],
                "additional_cidrs": [],
                "max_addresses_per_job": 1024,
                "max_concurrent_hosts": 64,
                "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
                "host_timeout_ms": 1500,
                "job_timeout_seconds": 300,
                "auto_discovery_paused": False,
            },
        },
    }, "approve did not apply the server's default capability grants"

    assert proc.wait(timeout=15) == 0, "enroll process did not exit 0 after approval"
    # The pipe outlives the loop above on purpose: `enroll.Run` blocks until the
    # server stops reporting the agent as pending (internal/enroll/enroll.go),
    # so the process is still writing — "approved — connecting" — long after the
    # pairing code was read and broken out on. It is only finished once the
    # approval above has landed and `wait()` has returned, which is the earliest
    # point this can be closed. Leaving it to the garbage collector raised
    # `ResourceWarning: unclosed file`, which pytest.ini's `filterwarnings =
    # error` turns into a failure attributed to whichever test happened to
    # trigger the collection rather than to the helper that leaked it.
    proc.stdout.close()
    return agent_id, stream


def _device_key(service: str, env: dict | None = None) -> str:
    """The sha256 of one agent's `device.key`, which is its identity.

    The one file that would be shared if two agent containers were not really
    two agents, and the one that must survive a restart if an agent is not
    silently re-enrolling. Both claims are made about this digest rather than
    about an `agents` row, because the row is what the server *believes* and
    this is what the agent actually presents.
    """
    return subprocess.run(
        [*COMPOSE, "exec", "-T", service, "sha256sum", "/var/lib/cb-agent/device.key"],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]


def _agent_attachments(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> set[str]:
    """The unprefixed compose-network names an agent container is attached to
    right now (`{"agent-net", "probe-net"}`), read from Docker rather than from
    the compose file — `docker network connect` at runtime is a legitimate part
    of this harness (see `_attach_agent_to_late_net`), so the file is not the
    authority on this and only the live container is."""
    container = subprocess.run(
        [*COMPOSE, "ps", "-q", service],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert container, f"{service} container is not running"
    return {name.rsplit("_", 1)[-1] for name in _container_networks(container)}


def _agent_network_name(
    env: dict | None = None, *, service: str = _AGENT_SERVICE
) -> tuple[str, str]:
    """Resolves the live container name + the (compose-project-prefixed) Docker
    network name that carries an agent's route to the SERVER, for the network
    disconnect/reconnect used by the rollback, partition and remote-probe tests.
    Looked up dynamically rather than hardcoded so this doesn't silently break
    if Compose's project/network naming ever changes.

    An agent sits on at least two networks (see docker-compose.yml's topology
    note): the one that reaches circuitbreaker, and one or more fixture subnets
    that circuitbreaker is deliberately not on. Only the server-facing one is
    returned, because every caller wants the route to the server specifically —
    cutting a fixture network as well would make "the vantage went away"
    indistinguishable from "the target went away", which is exactly the
    distinction the remote-probe and discovery tests exist to prove.

    The attached set is asserted rather than merely filtered, against
    `_AGENT_TOPOLOGY[service]`: see that table's comment for what each half of
    the assertion catches and why an exact-set assertion stopped being the
    right shape in Slice 4.
    """
    topology = _AGENT_TOPOLOGY[service]
    container = subprocess.run(
        [*COMPOSE, "ps", "-q", service],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert container, f"{service} container is not running"
    networks = _container_networks(container)
    suffixes = {name.rsplit("_", 1)[-1] for name in networks}
    missing = topology["required"] - suffixes
    assert not missing, (
        f"{service} has lost its attachment to {sorted(missing)} — the routes this "
        f"suite's isolation proofs depend on are gone, and the tests that use them "
        f"would fail (or pass) for reasons that have nothing to do with what they "
        f"assert. Attached: {sorted(networks)}"
    )
    unexpected = suffixes - topology["allowed"]
    assert not unexpected, (
        f"{service} is attached to unexpected network(s) {sorted(unexpected)} — the "
        f"isolation every 'the backend/the other agent could not have done this' "
        f"assertion rests on has been widened (see docker-compose.yml's topology "
        f"comment and _AGENT_TOPOLOGY). Attached: {sorted(networks)}"
    )
    server_net = next(
        name for name in networks if name.rsplit("_", 1)[-1] == topology["server_net"]
    )
    return container, server_net


def _container_networks(container: str) -> dict:
    return json.loads(
        subprocess.run(
            ["docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def _compose_network(suffix: str) -> str:
    """Resolves a compose network name (`agent-net`) to the live,
    project-prefixed Docker network (`cb-agent-e2e_agent-net`). Same reason as
    `_agent_network_name`'s lookup: the prefix is Compose's to choose, not
    this file's to assume."""
    names = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    matches = [name for name in names if name.rsplit("_", 1)[-1] == suffix]
    assert len(matches) == 1, (
        f"expected exactly one live Docker network named *_{suffix}, found {matches} — "
        f"either the network has not been created yet (compose creates a network only "
        f"when it brings up a service attached to it) or another compose project is "
        f"running alongside this one, which this harness's shared project name does "
        f"not survive"
    )
    return matches[0]


def _network_subnet(suffix: str) -> str:
    """The IPv4 subnet Docker actually gave a compose network.

    Read live rather than trusted from the compose file: an `ipam.config`
    entry that Docker silently declined (a pool collision, a stale network
    left behind by a previous run) would otherwise be discovered as an
    inexplicable discovery-scope mismatch several minutes later, instead of
    as a one-line assertion here."""
    network = _compose_network(suffix)
    subnets = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            network,
            "--format",
            "{{range .IPAM.Config}}{{.Subnet}} {{end}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    ipv4 = [s for s in subnets if ":" not in s]
    assert len(ipv4) == 1, f"{network} has IPv4 subnets {ipv4}, expected exactly one"
    return ipv4[0]


def _container_ipv4(container: str, network: str) -> str:
    return _container_networks(container)[network]["IPAddress"]


def _agent_route_networks(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> set[str]:
    """The IPv4 networks directly routable from inside an agent's OWN network
    namespace, as `a.b.c.d/len` strings, read from /proc/net/route.

    Deliberately not `docker inspect`: that reports host-side metadata about
    what Docker believes it attached. This reads the kernel routing table the
    agent process itself sees — the very same state `hostinfo.Networks()`
    enumerates on every `hello` and that `netscope.Derive` turns into
    `direct_private` scope. When a discovery assertion says "the agent had a
    route to this subnet and the backend did not", this is the half of that
    sentence about the agent.

    /proc/net/route rather than `ip route` because the agent image carries no
    iproute2 (e2e/Dockerfile installs ca-certificates and nothing else) — and
    keeping it that way is the point: the agent is not supposed to need a
    scanner or a network toolchain on the remote host.

    The default route (destination 0.0.0.0) is skipped: it is a gateway, not a
    directly connected network, and netscope excludes it for the same reason.
    """
    raw = subprocess.run(
        [*COMPOSE, "exec", "-T", service, "cat", "/proc/net/route"],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    networks = set()
    for line in raw.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        # Both columns are hex in host byte order; `to_bytes(4, "little")`
        # undoes that on any little-endian host, and popcount is byte-order
        # independent so the mask needs no such care.
        destination = int(fields[1], 16)
        mask = int(fields[7], 16)
        if destination == 0:
            continue
        address = ipaddress.IPv4Address(destination.to_bytes(4, "little"))
        networks.add(f"{address}/{bin(mask).count('1')}")
    return networks


def _up_fixture_target(service: str, env: dict | None = None) -> None:
    """Brings up one isolated fixture target (probe-target, probe-target-2 or
    late-target). Built separately from `_up_server` because each sits on a
    network the server is not, and because a test that does not use one should
    not pay for it — which is also what makes `late-target` able to arrive
    mid-test."""
    subprocess.run(
        [*COMPOSE, "up", "-d", "--build", service], check=True, cwd=E2E_DIR, env=env
    )


def _attach_agent_to_late_net(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> str:
    """Gives a already-running, already-enrolled agent a directly connected
    subnet it did not have when it started, and returns the network's live name.

    This is the zero-configuration trigger in its sharpest form (plan §8 step
    3): nothing is configured on the agent, no CIDR is typed anywhere, and the
    server is told nothing — a new interface simply appears in the agent's
    namespace, exactly as it would if someone plugged the host into another
    VLAN.

    What the caller must know: `hostinfo.Collect()` runs once per link
    connection (internal/link/link.go), so the new subnet reaches the server on
    the agent's NEXT `hello`, not immediately. A `docker compose restart` of the
    agent (or any other reconnect — `_cut_agent_network`, a backend outage)
    is what makes it observable server-side. `restart` specifically, never
    `up --force-recreate`: this attachment lives on the container, so recreating
    it would silently undo the very thing under test.
    """
    container, _ = _agent_network_name(env, service=service)
    network = _compose_network(_LATE_NET)
    subprocess.run(["docker", "network", "connect", network, container], check=True)
    return network


@contextlib.contextmanager
def _cut_agent_network(env: dict | None = None, *, service: str = _AGENT_SERVICE):
    """Severs an agent's only route to the server for the duration of the
    block, and restores it on the way out (including on failure).

    Only agent-net is detached (see _agent_network_name): cb-agent keeps
    probe-net and therefore keeps reaching the remote-probe target, which is
    what lets the remote-probe test tell "the vantage is unavailable" apart
    from "the target went down". agent-net is the container's only route to
    circuitbreaker AND the only place Docker's embedded DNS answers for the
    "circuitbreaker" service name, so detaching it makes every *new* dial fail
    immediately — which is precisely what the forced-rollback scenario needs: a
    re-exec'd daemon that can never complete its post-update hello.ack.

    A detached interface is a black hole, not a closed socket: no FIN or RST
    ever arrives, the already-established connection stays open from the
    agent's side, and its writes keep succeeding into the kernel send
    buffer. internal/link therefore cannot learn about this partition from a
    write error — it only learns from SILENCE, via the steady-state read
    deadline (readTimeout, 60s = three missed server pings). Until that
    deadline was added the agent never noticed at all: nothing spooled and
    every frame written into the void was lost, which is why this helper
    used to carry a warning against using it for outbound-spool tests.

    That warning no longer holds, but the ~60s detection lag it was really
    describing does. Any test using this helper must budget for it — see
    test_agent_black_hole_partition_is_detected_and_spools, which asserts
    the detection itself. `_backend_outage` remains the right stimulus when
    a test only wants a backlog quickly, since a closed socket fails the
    very next write.

    Factored into a context manager because the disconnect/reconnect pair
    MUST be try/finally-balanced: a test that fails inside the block while
    the network is still cut leaves a wedged container behind for `docker
    compose down` to clean up the hard way.
    """
    container, network = _agent_network_name(env, service=service)
    # Captured BEFORE the detach so it can be restored after: `docker network
    # connect` without `--ip` takes whatever the pool hands out, which silently
    # renumbers the container. A partition is not a renumbering — a real host
    # keeps its address across a WAN outage — and a test that moved the agent
    # deliberately (`_change_agent_address`) would otherwise have that move
    # undone by the next cut, with the failure surfacing much later as an
    # unrelated "the backend cannot reach the agent" positive control.
    address = _container_ipv4(container, network)
    subprocess.run(["docker", "network", "disconnect", network, container], check=True)
    try:
        yield container, network
    finally:
        _reattach_network(container, network, address)


def _reattach_network(container: str, network: str, address: str | None = None) -> None:
    """Re-attaches `network` to `container`, tolerating a container that is
    crash-looping rather than merely idle.

    This is the F-8 failure, and it is NOT the one previously recorded: the
    entry `docker network disconnect` succeeds. It is the reconnect, 150s
    later, that dies with "network sandbox for container ... not found".

    An agent severed from the server crash-loops for the whole cut, because
    runDaemon's enroll.Run is a network call whose failure is fatal
    (cmd/cb-agent/main.go) and the compose file sets `restart: on-failure` to
    mirror the real systemd unit. Docker's restart backoff is exponential, not
    the unit's fixed RestartSec=5s, so by the end of a 150s cut the container
    is spending minutes at a time in `restarting` — a state in which
    `.State.Running` is true but `.NetworkSettings.SandboxKey` is EMPTY, and
    there is therefore no sandbox to attach an endpoint to.

    Waiting for a running window does not work: those windows are measured in
    hundreds of milliseconds and the gaps grow past any sane timeout. Instead
    take the container out of the restart loop entirely — `docker stop` leaves
    it `exited`, where `network connect` takes Docker's config-only path,
    returns 0, and records the attachment for the next start. `docker start`
    then brings it up already on the network, which also resets the backoff.

    The partition itself is unaffected: by the time this runs the agent has
    already spent the full cut unable to reach the server, which is the whole
    point of the block.
    """
    connect = ["docker", "network", "connect"]
    if address:
        connect += ["--ip", address]
    connect += [network, container]
    if subprocess.run(connect).returncode == 0:
        return
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)
    subprocess.run(connect, check=True)
    subprocess.run(["docker", "start", container], check=True, capture_output=True)


@contextlib.contextmanager
def _backend_outage(client: httpx.Client, env: dict | None = None):
    """Takes the *server* away for the duration of the block and waits for it
    to answer again on the way out.

    This is what a *catch-up* test should use, and the difference from
    `_cut_agent_network` is not cosmetic — it is the difference between a
    closed socket and a black hole. Stopping the container sends a FIN, so
    the agent's very next write fails and spooling starts within one
    collection interval. A network detach sends nothing, so the agent can
    only infer the partition from silence and takes a full readTimeout (60s)
    to do it. Both are now detected — that is F-5's fix — but only this one
    produces a backlog promptly, which is what makes it the cheaper stimulus
    for a test whose subject is bounded catch-up rather than detection.

    Historically the choice was not about cost: before internal/link had a
    steady-state read deadline, a detach produced NO spooled frames at all
    (measured on this harness: a 60s detach at a 10s cadence gave zero
    spooled frames, no disconnect until the network came back, and six
    samples that simply never arrived). That is fixed; the cost argument is
    what survives it.

    Stopping the container instead closes the socket, so the agent's next
    write fails immediately, the link goes down, and every sample collected
    from then on is spooled — which is the scenario Task 13's paced catch-up
    burst was built for and names in its own doc comment ("a backend outage
    grows the backlog"). `stop`/`start`, not `down`/`up`: the Postgres data,
    the vault key and the agent's approval all have to survive.
    """
    subprocess.run([*COMPOSE, "stop", "circuitbreaker"], check=True, cwd=E2E_DIR, env=env)

    # The instant yielded is the first moment this process could not reach the
    # API at all — NOT the moment `docker compose stop` returned, and not a
    # timestamp the caller took beforehand (F-6.3). Between a caller-side stamp
    # and the server actually going away sit SIGTERM, supervisord's shutdown of
    # uvicorn and Postgres, and the kill grace; samples collected and delivered
    # LIVE in that span would otherwise fall inside a window the caller treats
    # as "these buckets can only have come out of the spool". At a 30s history
    # grain a slow stop can satisfy that floor entirely from pre-outage
    # buckets, which degrades the "collected_at preserved rather than rewritten
    # to reconnect time" proof into a tautology.
    #
    # Only a transport failure counts — a 5xx would mean the server is still
    # there. That is the same socket the agent's /link connection terminates
    # on, so this is a fact about the server rather than about docker's CLI.
    def _api_unreachable() -> bool:
        try:
            client.get("/api/v1/bootstrap/status", timeout=2.0)
        except httpx.HTTPError:
            return True
        return False

    _wait_until(_api_unreachable, timeout=60, interval=0.25)
    confirmed_down_at = datetime.now(timezone.utc)
    try:
        yield confirmed_down_at
    finally:
        subprocess.run([*COMPOSE, "start", "circuitbreaker"], check=True, cwd=E2E_DIR, env=env)
        _wait_until(
            lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=180
        )


def _agent_telemetry(client: httpx.Client, agent_id: int) -> dict:
    """GET /agents/{id}/telemetry — latest sample, collector readiness, the
    live capability grant, the agent's last-reported spool backlog, and the
    linked hardware id."""
    resp = client.get(f"/api/v1/agents/{agent_id}/telemetry")
    resp.raise_for_status()
    return resp.json()


def _readiness_states(telemetry: dict) -> dict[str, str]:
    return {row["collector"]: row["state"] for row in telemetry["readiness"]}


def _history_points(client: httpx.Client, agent_id: int, range_name: str = "1h") -> list[dict]:
    resp = client.get(
        f"/api/v1/agents/{agent_id}/telemetry/history", params={"range": range_name}
    )
    resp.raise_for_status()
    return resp.json()["points"]


def _parse_ts(value: str) -> datetime:
    """Parses one of this API's timestamps into an aware datetime.

    Every timestamp on these endpoints is a timezone-aware UTC column
    (`DateTime(timezone=True)` on AgentHostSample.collected_at), serialized
    by FastAPI's jsonable_encoder, so these compare directly against this
    test process's own `datetime.now(timezone.utc)` — the agent, the server
    and this test all share one kernel clock here.
    """
    return datetime.fromisoformat(value)


def _put_host_telemetry(
    client: httpx.Client, headers: dict, agent_id: int, grant: dict | bool
) -> dict:
    """PUT one host_telemetry grant. set_capability_grants merges against the
    stored config, so a partial `config` keeps every setting it omits."""
    resp = client.put(
        f"/api/v1/agents/{agent_id}/capabilities",
        json={"capabilities": {"host_telemetry": grant}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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
# AGT-04 / RC-08 forbid an unexplained xfail at sign-off, and this is the only
# one in the repo. Its original reason named three production bugs — all three
# have since been fixed, and the marker outlived them:
#
#   1. link.go Uninstall() read only one of the two frames the server queues.
#      Fixed in 4aab49d5: drainPending() now loops until the read errors, after
#      a real WS close handshake (link.go:1053-1061).
#   2. ws_agents.link_stream swallowed frame-decrypt failures silently.
#      Fixed in 4aab49d5: logged with agent id and exception (ws_agents.py:836).
#   3. A second concurrent /link teardown deregistered the first, still-live
#      connection. Fixed in ad197961: atomic compare-and-delete Lua scoped to
#      worker_id (agent_registry.py:1274, deregister_agent_connection).
#
# The fixes landed at 16:53 on 2026-08-05; this marker was written at 14:42 the
# same day in 6903d6db. With strict=False a now-passing test reported as xpass,
# which is why nobody noticed for two weeks.
#
# strict=True is deliberate and self-resolving: if the test now passes, pytest
# fails the run with XPASS(strict), which is the signal to delete this marker
# entirely. If it still fails, it fails for a NEW reason that needs recording
# here — not for the three above. Verifying that needs a Docker host, which the
# 2026-08-18 remediation pass did not have.
@pytest.mark.xfail(
    reason=(
        "Stale marker pending verification: the three bugs it originally named "
        "(link.go Uninstall drain, ws_agents decrypt-swallow, agent_registry "
        "cross-connection deregister) were all fixed in 4aab49d5 and ad197961. "
        "Run this test on a Docker host; XPASS(strict) means delete the marker."
    ),
    strict=True,
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
            # CB_AGENT_TEST_PRE_REEXEC_DELAY_MS (see cmd/cb-agent/main.go's
            # reExecDelayEnvOverride): on this harness's local Docker bridge
            # network, a freshly re-exec'd daemon can reconnect and
            # self-confirm an update in well under 100ms — faster than this
            # test's own log-poll-then-disconnect trigger below can reliably
            # beat without it. 1000ms gives a wide, reliable margin; it costs
            # this test 1 extra second per re-exec (step 7a's included) and
            # is completely inert in every real deployment (unset there).
            reexec_delay_env = {**os.environ, "CB_AGENT_TEST_PRE_REEXEC_DELAY_MS": "1000"}
            subprocess.run(
                [*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR, env=reexec_delay_env
            )
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
            # completes (watched via the daemon's own "updated to
            # <rollback_version> — re-executing" log line — see main.go's
            # onUpdate) — so the freshly re-exec'd binary can never complete
            # a post-update hello.ack, exactly the "update never confirms"
            # case internal/update's rollbackWindow (2 real minutes) guards
            # against. The predicate below matches specifically on
            # rollback_version, not the bare "re-executing" substring —
            # _agent_logs() returns the container's whole accumulated
            # stdout, and step 7a already logged its own "re-executing" line
            # earlier in this same container, so a bare-substring match
            # would return true on the very first poll here, long before
            # this update's actual re-exec, and race the binary *download*
            # instead. The 0.05s poll interval (rather than _wait_until's 1s
            # default) plus CB_AGENT_TEST_PRE_REEXEC_DELAY_MS (set above)
            # then close the race this step used to lose against a
            # same-host re-exec that can reconnect and self-confirm in well
            # under 100ms.
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
                lambda: f"updated to {rollback_version}" in _agent_logs(),
                timeout=30,
                interval=0.05,
            )

            with _cut_agent_network():
                # rollbackWindow is a real 2 minutes (internal/update, via
                # main.go) with no test-only override — Global Constraints
                # doesn't govern this value the way it governs the rekey
                # interval, so this test just pays the real cost once.
                time.sleep(150)

            # Wait on the ROLLBACK EVENT first, not on status.json's version.
            # status.json is written by startDaemonState, which runs after
            # runDaemon's fatal enroll.Run — so the partitioned 9.9.9 binary
            # never got to write one, and the file still holds the string the
            # *previous* (0.3.5) process left there. Asserting on it before
            # the agent has reconnected is therefore a tautology: it passes
            # whether or not the rollback ever happened, which is precisely
            # how this test could time out at the next line with nothing to
            # show for it. The audit event is the first thing here that can
            # only exist if the rollback really ran: the rolling-back process
            # has no live link, so it persists a rollback report
            # (update.WriteRollbackReport) that the re-exec'd binary sends as
            # update.status(rolled_back) once it reconnects — see
            # services/agent_link.py's "rolled_back" mapping.
            #
            # The budget is generous because the agent has to get there the
            # slow way: it crash-loops for the whole cut (enroll.Run cannot
            # succeed with agent-net detached), rolls back on the first start
            # after its durable deadline, and only then reconnects.
            def _rolled_back():
                events = client.get(f"/api/v1/agents/{agent_id}/events", headers=headers).json()
                return any(e["event_type"] == "update_rolled_back" for e in events)

            _wait_until(_rolled_back, timeout=180, interval=2.0)

            # Only now is this meaningful: the agent has reconnected, so
            # status.json is this process's own, and this process is the
            # rolled-back binary.
            _wait_until(lambda: _agent_status().get("version") == baked_version, timeout=60)
            assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active", (
                "enrollment must survive a rollback — the agent is the same identity it was"
            )
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


# ─────────────────────────────────────────────────────────────────────────
# Task 20: host telemetry acceptance, bounded catch-up, live cadence change,
# and disable
# ─────────────────────────────────────────────────────────────────────────

# D-13: the daemon is driven at the real production minimum
# (internal/capability/capability.go's 10s floor), not the 30s default, so
# the outage-catch-up step costs a minute rather than four. Cadence is pure
# configuration and its default path stays covered by the Go and backend
# suites. interval_s is restored to 30 before this test exits.
_TELEMETRY_INTERVAL_S = 10
# Floor on how many collection intervals the outage swallows. Six (60s)
# rather than the minimum four because the 1h history grain is 30s buckets:
# a 60s window contains at least one whole bucket regardless of where the
# outage starts inside one, so "samples landed with their original
# collected_at" is assertable on bucket boundaries. The real outage is
# longer than this — _backend_outage also has to wait out the container's
# own restart — which is why every assertion below is a floor, never an
# exact count.
_MISSED_INTERVALS = 6
_OUTAGE_SECONDS = _TELEMETRY_INTERVAL_S * _MISSED_INTERVALS
# The slower cadence the live grant change switches to (step 4).
_SLOW_INTERVAL_S = 60
# api/agents.py's _HISTORY_BUCKET_SECONDS["1h"].
_HISTORY_BUCKET_S = 30
# At a 10s cadence a 30s bucket holds 3 samples. 4 allows for ticker drift
# across a bucket boundary; 6 would mean every outage sample was ingested
# twice, which is exactly what this bound exists to catch. Delivery out of
# the spool is at-least-once by construction (frames are peeked, sent, and
# only then committed — see internal/link/outbound.go), so "no duplicate
# rows" is a property of the backend's (agent_id, sample_id, collected_at)
# dedupe, and this is the end-to-end check that it actually holds.
_MAX_SAMPLES_PER_BUCKET = 4
# Wall-clock budget for the whole backlog to land, measured from the moment
# the link is observably back up (not from the moment the server starts
# answering again, which the agent's reconnect backoff — 1s doubling to a 5m
# cap, internal/link/backoff.go — sits behind for up to a minute after an
# outage this long). Task 13's pacing is drainFramesPerTick=4 frames per
# drainTickInterval=100ms, bounded by drainBytesPerTick=256KiB — ~40
# frames/s, so a 6-frame backlog drains in well under a second. Those are
# unexported package vars in Go's internal/link and deliberately are NOT
# read from here; 30s is a bound generous enough to survive scheduling noise
# while still failing loudly if catch-up regressed to the old live-traffic-
# gated 1:4 interleave.
_CATCHUP_BUDGET_S = 30

# internal/link/backoff.go: backoffBase = 1s, doubling per attempt to a 5m cap,
# with up to 25% jitter added on top of each base duration.
_BACKOFF_BASE_S = 1.0
_BACKOFF_JITTER = 1.25
# Slack for the reconnect ATTEMPT itself once backoff releases it: TCP dial,
# TLS, and the Noise IK handshake whose single read is bounded by internal/link's
# handshakeTimeout (10s), retried once per server-key candidate.
_RECONNECT_ATTEMPT_SLACK_S = 30.0


def _reconnect_budget_s(outage_len_s: float) -> float:
    """How long the agent may legitimately stay away AFTER the server answers
    again — derived from internal/link/backoff.go rather than guessed.

    The pre-outage connection had been up for minutes, so it is `stable` by
    link.go's stabilityWindow and the backoff state resets to attempt 0 when it
    drops. Delays are then 1, 2, 4, 8, ... seconds. Because each delay is no
    larger than the sum of every delay before it, the one still in flight when
    the server returns is at most the whole elapsed outage — so the remaining
    wait is bounded by the outage length itself, plus jitter and one attempt.

    This is deliberately NOT folded into _CATCHUP_BUDGET_S. Reconnect backoff
    is not the property under test, and it can legitimately dwarf catch-up: one
    combined budget lets a regressed drain hide behind a slow dial, which is
    exactly what F-6.2 records.
    """
    return _BACKOFF_JITTER * (outage_len_s + _BACKOFF_BASE_S) + _RECONNECT_ATTEMPT_SLACK_S


def _last_connect_at(client: httpx.Client, agent_id: int, *, after: datetime):
    """When the SERVER last recorded this agent's link coming up, or None if
    that has not happened since `after`.

    This, and not a local time.monotonic() reading, is the instant a catch-up
    budget must be measured from (F-6.2). `agent_events` rows come back
    newest-first and a `connected` row is written once per accepted /link
    connection, in the same committed transaction as hello's spool-depth
    snapshot and strictly before the hello.ack that gates the drain. So it is
    at or before the moment the first spooled frame could have been sent, and
    any error in it makes the measured catch-up longer, never shorter.

    Agent.connected_since is deliberately not used: the column is never
    assigned anywhere in the backend and is always NULL.
    """
    for event in _agent_events(client, agent_id):
        if event["event_type"] != "connected":
            continue
        created = _parse_ts(event["created_at"])
        return created if created >= after else None
    return None

_HOST_TELEMETRY_FAST_CONFIG = {
    "interval_s": _TELEMETRY_INTERVAL_S,
    "include_filesystems": True,
    "include_disks": True,
    "include_network": True,
    "include_temperatures": True,
    "include_docker": False,
}


@pytest.mark.e2e
def test_agent_host_telemetry_first_sample_catchup_and_disable():
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

            try:
                # ---- 1. Approval -> first accepted sample ----------------
                # The approval already granted host_telemetry at the 30s
                # default; this PUT only changes the cadence (and pins the
                # include_* flags this test asserts on) and is delivered over
                # the live link as a capabilities.set control frame.
                grant_applied_at = datetime.now(timezone.utc)
                _put_host_telemetry(
                    client,
                    headers,
                    agent_id,
                    {"enabled": True, "config": _HOST_TELEMETRY_FAST_CONFIG},
                )

                # cpu_pct (and every rate-derived field) is a delta between
                # two /proc/stat snapshots, so the very first collection of
                # any freshly constructed collector — and applying a config
                # constructs one, see main.go's applyHostConfig — carries a
                # null cpu_pct. Requiring BOTH "collected after the grant
                # landed" and "carries a rate" therefore waits for the second
                # sample produced under the new cadence, which is what proves
                # the whole outbound path is running steadily rather than
                # having delivered exactly one frame.
                #
                # The whole response is captured by the predicate rather than
                # re-fetched afterwards: at a 10s cadence the next sample can
                # land between the two calls, and the config change's own
                # first (rate-less) sample would then be what the assertions
                # below ran against.
                def _rate_bearing_telemetry() -> dict | None:
                    current = _agent_telemetry(client, agent_id)
                    sample = current["latest"]
                    if sample is None or sample["summary"]["cpu_pct"] is None:
                        return None
                    if _parse_ts(sample["collected_at"]) <= grant_applied_at:
                        return None
                    return current

                telemetry = _wait_until_and_return(_rate_bearing_telemetry, timeout=45)
                latest = telemetry["latest"]
                summary = latest["summary"]
                assert summary["cpu_pct"] is not None, summary
                assert summary["mem_pct"] is not None, summary
                assert summary["uptime_s"] is not None, summary
                # root_disk_pct is deliberately NOT asserted non-null here.
                # host.Collector only sets it from a /proc/self/mounts entry
                # whose mountpoint is exactly "/" and whose fs type is not in
                # its pseudoFS deny-list — and "overlay" is in that list, so
                # in ANY container (this harness included) the root mount is
                # skipped by design. That is a property of running the
                # collector inside a container, not of the collector: on a
                # real host "/" is ext4/xfs and the field is populated. What
                # is assertable here is the capability behind it — real
                # statfs numbers for real mounts — so the filesystems list is
                # checked for a usable used_pct below instead.
                #
                # host.Collector stamps "healthy" and only downgrades to
                # "degraded"/"unavailable" on a real probe failure (see
                # internal/collect/host/host.go). "unavailable" would mean
                # core /proc telemetry itself failed.
                assert latest["status"] in ("healthy", "degraded"), latest["status"]
                payload = latest["payload"]
                assert payload["filesystems"], "no filesystem entries in the sample payload"
                assert payload["disks"], "no disk entries in the sample payload"
                assert payload["interfaces"], "no network interface entries in the sample payload"
                assert any(
                    isinstance(fs.get("used_pct"), (int, float)) for fs in payload["filesystems"]
                ), f"no filesystem carried a computed used_pct: {payload['filesystems']}"

                # ---- 2. Unlinked retention + collector readiness ---------
                states = _readiness_states(telemetry)
                assert states.get("host.core") == "ready", states
                # No Docker socket is mounted into cb-agent (see
                # docker-compose.yml's cb-agent volumes) and include_docker is
                # false in the grant above, so this collector must report
                # itself off rather than broken or healthy.
                assert states.get("host.docker") == "disabled", states
                # _enroll_agent approves with host_link_action "unlinked", so
                # there is no hardware row to project onto: the sample is
                # still persisted and served (retention is unconditional),
                # and projected_at stays null.
                assert telemetry["hardware_id"] is None, telemetry["hardware_id"]
                assert latest["projected"] is False, latest

                # ---- 3. Bounded catch-up without duplicates --------------
                def _history_sample_total() -> int:
                    return sum(p["sample_count"] for p in _history_points(client, agent_id))

                samples_before_outage = _history_sample_total()

                # outage_start comes from the manager, not from here: it is
                # the moment the API was CONFIRMED unreachable, so the sleep
                # below happens entirely inside a real outage and every bucket
                # this window selects was necessarily spooled (F-6.3).
                with _backend_outage(client) as outage_start:
                    # The daemon keeps collecting throughout: internal/link's
                    # Run routes data frames to the spool whenever the link
                    # is not live, so every sample produced in here is
                    # durably queued rather than dropped.
                    time.sleep(_OUTAGE_SECONDS)
                # The window closes only once the API answers again, so it
                # covers the backend's own restart too — the agent was
                # collecting into the spool for all of it.
                outage_end = datetime.now(timezone.utc)

                # Spool depth first, and immediately: the value the server
                # holds during catch-up comes from hello.spool_depth (D-12) —
                # it CANNOT have moved during the outage, because no frame
                # reached the server while the agent was disconnected — and
                # the very next heartbeat (20s) overwrites it with the
                # by-then-drained 0. Polling fast from here is what makes the
                # non-zero window observable at all.
                # Two properties, two clocks — the separation IS the
                # assertion (F-6.2). The old single 240s magic-number poll
                # bounded neither: it let a regressed drain hide behind a slow
                # reconnect, which is the very property D-5 exists to pin.
                #
                # (a) RECONNECT, bounded by internal/link's own backoff
                # progression and measured from the moment the server was
                # answering again.
                observed_depth = 0
                reconnect_budget_s = _reconnect_budget_s(
                    (outage_end - outage_start).total_seconds()
                )
                depth_deadline = time.monotonic() + reconnect_budget_s
                while time.monotonic() < depth_deadline:
                    spool = _agent_telemetry(client, agent_id)["spool"]
                    if spool["depth"]:
                        observed_depth = spool["depth"]
                        break
                    time.sleep(0.5)
                assert observed_depth > 0, (
                    "never observed a non-zero spool depth within "
                    f"{reconnect_budget_s:.0f}s of the server answering again "
                    f"after a {_OUTAGE_SECONDS}s outage — either the outage "
                    "samples were dropped instead of spooled, hello.spool_depth "
                    "is not being recorded, or reconnect backoff regressed"
                )

                # (b) CATCH-UP, measured from the server's OWN record of the
                # link coming up rather than from whenever this process
                # happened to notice a non-zero depth. Polling latency and any
                # remaining backoff land outside the budget, where they belong.
                link_restored_at = _last_connect_at(client, agent_id, after=outage_start)
                assert link_restored_at is not None, (
                    "the server recorded no `connected` event after the outage, so there is "
                    "no instant to measure a catch-up budget from"
                )

                bucket_width = timedelta(seconds=_HISTORY_BUCKET_S)

                def _outage_points() -> list[dict]:
                    """1h history buckets lying ENTIRELY inside the outage.

                    Every sample in them was collected while the server was
                    down, so their existence is proof the backlog was
                    delivered with its ORIGINAL collected_at rather than
                    restamped to reconnect time — a restamped backlog would
                    leave this window empty and pile up in the reconnect
                    bucket instead.

                    Whole buckets only, because a bucket straddling either
                    edge is still open: the one the outage ends in keeps
                    collecting live samples afterwards, so it would differ
                    between two reads for an entirely innocent reason and
                    make the duplicate check below meaningless.
                    """
                    return [
                        p
                        for p in _history_points(client, agent_id)
                        if outage_start <= _parse_ts(p["collected_at"])
                        and _parse_ts(p["collected_at"]) + bucket_width <= outage_end
                    ]

                # A window of at least 60s always contains at least one whole
                # 30s bucket wherever it starts, and a whole bucket holds 3
                # samples at a 10s cadence. A floor, not an equality — see
                # _MISSED_INTERVALS.
                min_outage_samples = 3

                def _caught_up() -> bool:
                    return (
                        sum(p["sample_count"] for p in _outage_points()) >= min_outage_samples
                        and _history_sample_total() >= samples_before_outage + _MISSED_INTERVALS
                    )

                # The deadline is the server's connect instant plus the
                # budget, so time already spent reconnecting is not spent here.
                catchup_deadline = link_restored_at + timedelta(seconds=_CATCHUP_BUDGET_S)
                _wait_until(
                    _caught_up,
                    timeout=max(1.0, (catchup_deadline - datetime.now(timezone.utc)).total_seconds()),
                    interval=1.0,
                )
                catchup_elapsed = (datetime.now(timezone.utc) - link_restored_at).total_seconds()
                assert catchup_elapsed <= _CATCHUP_BUDGET_S, (
                    f"the backlog took {catchup_elapsed:.1f}s to land, measured from the "
                    f"server's own `connected` event — budget is {_CATCHUP_BUDGET_S}s"
                )

                # The indicator has to clear on its own, from the heartbeat
                # (D-12) — hello alone could never lower it. Two heartbeat
                # intervals (20s each, internal/link) plus margin. This also
                # establishes that the backlog is fully drained, which is what
                # makes the duplicate check below a comparison of settled data
                # rather than a race against the tail of the burst.
                _wait_until(
                    lambda: _agent_telemetry(client, agent_id)["spool"]["depth"] == 0,
                    timeout=50,
                )

                # Duplicate check, two ways. (a) No outage bucket may hold
                # more samples than the cadence can physically produce.
                # (b) Re-issuing the same window must return byte-identical
                # buckets: they are closed and fully drained, so any change
                # between two reads would mean a row was ingested twice.
                first_read = _outage_points()
                for point in first_read:
                    assert point["sample_count"] <= _MAX_SAMPLES_PER_BUCKET, (
                        f"bucket {point['collected_at']} holds {point['sample_count']} samples "
                        f"at a {_TELEMETRY_INTERVAL_S}s cadence in a {_HISTORY_BUCKET_S}s bucket "
                        "— the spool's at-least-once redelivery was not deduped"
                    )

                # (c) Per-SAMPLE, not inferred from bucket aggregates (F-6.1).
                # The plan's requirement is that every sample_id appears once,
                # and no history endpoint can express that — see
                # _agent_host_samples. This also catches the one case the
                # unique constraint cannot: a redelivery whose collected_at was
                # rewritten satisfies (agent_id, sample_id, collected_at) and
                # lands as a second row under the same sample_id.
                outage_samples = _agent_host_samples(agent_id, outage_start, outage_end)
                assert outage_samples, (
                    "no raw agent_host_samples rows inside the confirmed outage window — the "
                    "backlog was either lost or restamped to reconnect time"
                )
                sample_ids = [sample_id for sample_id, _ in outage_samples]
                duplicates = sorted({sid for sid in sample_ids if sample_ids.count(sid) > 1})
                assert not duplicates, (
                    f"{len(duplicates)} sample_id(s) were persisted more than once inside the "
                    "outage window — the spool's at-least-once redelivery (peek/send/commit, "
                    f"internal/link/outbound.go) was not deduped: {duplicates}"
                )

                time.sleep(3)
                second_read = _outage_points()
                assert second_read == first_read, (
                    "the same closed history window returned different buckets on a "
                    f"second read — outage samples are being re-ingested as new rows.\n"
                    f"first:  {first_read}\nsecond: {second_read}"
                )

                # ---- 4. Cadence change without a reconnect ---------------
                connected_since_before = client.get(f"/api/v1/agents/{agent_id}").json()[
                    "connected_since"
                ]
                _put_host_telemetry(
                    client,
                    headers,
                    agent_id,
                    {"enabled": True, "config": {"interval_s": _SLOW_INTERVAL_S}},
                )
                # Let the switch settle past one *old* interval so the
                # baseline below is a sample the new runner produced, not the
                # last straggler from the 10s one.
                time.sleep(_TELEMETRY_INTERVAL_S * 2)

                def _latest_collected_at() -> datetime:
                    return _parse_ts(_agent_telemetry(client, agent_id)["latest"]["collected_at"])

                gap_base = _latest_collected_at()
                _wait_until(
                    lambda: _latest_collected_at() > gap_base,
                    timeout=_SLOW_INTERVAL_S + 30,
                    interval=2.0,
                )
                observed_gap = _latest_collected_at() - gap_base
                assert observed_gap >= timedelta(seconds=_SLOW_INTERVAL_S * 0.75), (
                    f"sample gap {observed_gap} does not reflect the new "
                    f"{_SLOW_INTERVAL_S}s cadence"
                )
                # Same proof shape as step 6 of the lifecycle test: the new
                # cadence arrived over the live control-frame push, so the
                # daemon's link never dropped and the server's
                # connected_since never moved. status.json carries grants as
                # bare booleans (see internal/status.Status.Grants), which is
                # why the cadence itself is verified from the observed sample
                # gap above rather than from the status file.
                status = _agent_status()
                assert status["link_state"] == "accepted", status
                assert status.get("grants", {}).get("host_telemetry") is True, status
                assert (
                    client.get(f"/api/v1/agents/{agent_id}").json()["connected_since"]
                    == connected_since_before
                )

                # ---- 5. Disable stops collection and reports it ----------
                _put_host_telemetry(client, headers, agent_id, {"enabled": False})

                # D-4: ingest_readiness only ever upserts, so the ONLY way
                # these rows stop claiming the collectors are live is the
                # agent actively republishing every name in
                # host.CollectorNames as "disabled" (Task 11).
                host_collectors = (
                    "host.core",
                    "host.filesystems",
                    "host.disks",
                    "host.network",
                    "host.thermal",
                    "host.docker",
                )

                def _all_host_collectors_disabled() -> bool:
                    states_now = _readiness_states(_agent_telemetry(client, agent_id))
                    return all(states_now.get(name) == "disabled" for name in host_collectors)

                _wait_until(_all_host_collectors_disabled, timeout=30)

                # Give any sample already in flight when the grant was
                # revoked time to land, then freeze the baseline.
                time.sleep(5)
                collected_at_at_disable = _latest_collected_at()
                assert _agent_status().get("grants", {}).get("host_telemetry") is False

                # Past two of the intervals that were in force before the
                # disable — if collection were still running, this window
                # would contain two more samples.
                time.sleep(_SLOW_INTERVAL_S * 2 + 5)
                assert _latest_collected_at() == collected_at_at_disable, (
                    "a new host sample arrived after host_telemetry was revoked"
                )
                assert _all_host_collectors_disabled(), _readiness_states(
                    _agent_telemetry(client, agent_id)
                )
            finally:
                # D-13: restore the production default cadence before
                # exiting, so nothing this test did to the grant outlives it.
                # Best-effort — the stack is torn down below regardless, and
                # a failure here must not mask the real assertion failure.
                with contextlib.suppress(Exception):
                    _put_host_telemetry(
                        client,
                        headers,
                        agent_id,
                        {"enabled": True, "config": {"interval_s": 30}},
                    )
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# F-5: black-hole network partition detection
# ─────────────────────────────────────────────────────────────────────────

# internal/link's readTimeout: 3 * the 20s heartbeatInterval, matching the
# backend's own _LINK_DEAD_SECONDS. Deliberately NOT overridden for this test.
# There is a precedent for shrinking a production interval from the harness
# (CB_AGENT_TEST_REKEY_INTERVAL_SECONDS) but it exists because 15 minutes is
# impractical to wait out; 60s is not, and paying the real value keeps this
# test an assertion about production behavior rather than about a test-only
# code path.
_PARTITION_DETECT_S = 60
# Slack on top of the deadline: the agent's reader is only released at the
# deadline itself, and status.json is written from the disconnect handler
# after that.
_PARTITION_DETECT_BUDGET_S = _PARTITION_DETECT_S + 30
# How long to keep collecting *after* detection, so there is a backlog whose
# delivery can be checked. Four intervals at the 10s cadence.
_PARTITION_SPOOL_S = 40


@pytest.mark.e2e
def test_agent_black_hole_partition_is_detected_and_spools():
    """A severed route — no FIN, no RST, just silence — must take the link
    down and divert collection into the spool.

    This is the scenario F-5 records as covered by no test. It is distinct
    from `test_agent_host_telemetry_first_sample_catchup_and_disable`'s
    outage in the one way that matters: `docker compose stop` closes the
    socket, so the agent's next write fails and the existing write-error
    path handles it. `docker network disconnect` closes nothing. Every
    write keeps succeeding into a kernel buffer that will never drain, so
    the ONLY evidence available to the agent is that nothing is coming back
    — which is what internal/link's steady-state read deadline exists to
    notice, and what nothing exercised before this test.

    Asserted from inside the partition, against the agent's own status.json
    (`docker compose exec` needs no container network, so this stays
    readable while the agent is unreachable over TCP):

      1. link_state flips to "disconnected" within the read deadline;
      2. last_error names the read deadline, not some incidental error —
         without this the test would still pass if the link dropped for an
         unrelated reason;
      3. spool_depth climbs above zero, i.e. samples collected during the
         partition are being kept rather than written into the void.

    And after the route is restored, that backlog is delivered.
    """
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
            _put_host_telemetry(
                client,
                headers,
                agent_id,
                {"enabled": True, "config": _HOST_TELEMETRY_FAST_CONFIG},
            )

            try:
                # Steady state first: the link is accepted, samples are
                # arriving, and the spool is empty. Without this the
                # assertions below could not tell "the partition diverted
                # traffic to the spool" from "the link was never up".
                _wait_until(
                    lambda: _agent_telemetry(client, agent_id)["latest"] is not None,
                    timeout=60,
                )
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted", timeout=30
                )
                assert _agent_status()["spool_depth"] == 0, (
                    "spool was already non-empty before the partition — the "
                    "backlog asserted below would not be attributable to it"
                )
                samples_before = sum(
                    p["sample_count"] for p in _history_points(client, agent_id)
                )

                with _cut_agent_network():
                    partition_start = time.monotonic()

                    def _link_down() -> bool:
                        return _agent_status()["link_state"] == "disconnected"

                    _wait_until(_link_down, timeout=_PARTITION_DETECT_BUDGET_S)
                    detected_after = time.monotonic() - partition_start

                    status = _agent_status()
                    # The link went down for the RIGHT reason. A partition
                    # detected via some other error would mean the read
                    # deadline is still not doing its job, and this test
                    # would be passing for the wrong reason.
                    assert "read deadline" in status.get("last_error", ""), (
                        "link dropped during the partition, but not on the "
                        f"read deadline: last_error={status.get('last_error')!r}"
                    )
                    # A floor as well as a ceiling: dropping the link far
                    # sooner than the deadline would mean something other
                    # than silence tore it down, which is a different
                    # behavior than the one under test.
                    assert detected_after >= _PARTITION_DETECT_S * 0.5, (
                        f"link dropped after only {detected_after:.0f}s of a "
                        f"{_PARTITION_DETECT_S}s read deadline — the drop "
                        "cannot have come from the deadline expiring"
                    )

                    # Now that the agent knows it is offline, everything it
                    # collects must be queued rather than written into the
                    # void — the actual product consequence of F-5.
                    time.sleep(_PARTITION_SPOOL_S)
                    spooled = _agent_status()["spool_depth"]
                    assert spooled > 0, (
                        f"spool_depth is still 0 after {_PARTITION_SPOOL_S}s of "
                        "collecting during a detected partition — samples are "
                        "being dropped instead of queued"
                    )

                # Route restored: the backlog drains and the history gains
                # the samples collected while the agent was cut off. The
                # budget covers reconnect backoff (1s doubling — a partition
                # this long leaves it partway up the progression) on top of
                # catch-up itself.
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted",
                    timeout=180,
                )
                _wait_until(
                    lambda: _agent_status()["spool_depth"] == 0,
                    timeout=_CATCHUP_BUDGET_S,
                )
                samples_after = sum(
                    p["sample_count"] for p in _history_points(client, agent_id)
                )
                assert samples_after > samples_before, (
                    "no new samples reached the server after the partition "
                    f"healed ({samples_before} -> {samples_after}) — the "
                    "spooled backlog was not delivered"
                )
            finally:
                with contextlib.suppress(Exception):
                    _put_host_telemetry(
                        client,
                        headers,
                        agent_id,
                        {"enabled": True, "config": {"interval_s": 30}},
                    )
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Slice 3 §9 steps 1-6 and 9-11: remote-probe acceptance
# ─────────────────────────────────────────────────────────────────────────

# probe-net's pinned addresses moved to the topology block at the top of this
# file when Slice 4 added a second agent, a second fixture subnet and a late
# one: _PROBE_NET_CIDR, _PROBE_TARGET_IP and _PROBE_TARGET_NAME are defined
# there alongside their siblings. Only the port numbers, which are properties
# of what probe-target *serves* rather than of the topology, stay here.
_PROBE_TARGET_HTTP_PORT = 8080
# Nothing listens here. A TCP check against it is a *target* failure — refused
# in microseconds, no execution error — which is what makes it the right
# stimulus for the retry/alert-parity monitor.
_PROBE_TARGET_CLOSED_PORT = 9999

# The four monitors under test poll on this cadence. Fast enough that a
# scheduler tick, a dispatch and a result are all observable inside a
# reasonable wait; slow enough that the assertions below are not racing a
# check that starts between two API calls.
_PROBE_INTERVAL_S = 30

# Everything before the first result has to happen once: capability grant ->
# probe readiness report -> readiness ingest -> scheduler tick -> dispatch ->
# check -> result. 180s is several times the worst observed path and is the
# same order as this file's other first-sample budgets.
_PROBE_FIRST_RESULT_BUDGET_S = 180

# `_cut_agent_network` produces a black hole, not a closed socket (see its
# docstring): the agent needs a full readTimeout (60s) to notice, and the
# server needs its own presence TTL to expire on top of that before dispatch
# starts refusing. Both are paid in series here, plus one monitor interval.
_PROBE_UNAVAILABLE_BUDGET_S = 300

# Reconnect after a partition of this length is dominated by internal/link's
# 1s-doubling backoff, not by anything under test.
_PROBE_RECONNECT_BUDGET_S = 300


def _backend_sh(command: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Runs a shell command inside the backend container. Deliberately not
    `check=True`: every caller below is asking whether something FAILS."""
    return subprocess.run(
        [*COMPOSE, "exec", "-T", "circuitbreaker", "sh", "-c", command],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def _create_monitor(client: httpx.Client, **body) -> dict:
    resp = client.post("/api/v1/monitors", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _monitor(client: httpx.Client, monitor_id: int) -> dict:
    resp = client.get(f"/api/v1/monitors/{monitor_id}")
    resp.raise_for_status()
    return resp.json()


def _monitor_samples(client: httpx.Client, monitor_id: int, metric: str) -> list[float]:
    """Every `metric` value in `telemetry_timeseries` for this monitor in the
    last hour — the same rows uptime and the history graph are computed from."""
    resp = client.get(
        f"/api/v1/monitors/{monitor_id}/history", params={"metric": metric, "hours": 1}
    )
    resp.raise_for_status()
    return [point["value"] for point in resp.json()]


def _monitor_events(client: httpx.Client, monitor_id: int) -> list[dict]:
    resp = client.get(f"/api/v1/monitors/{monitor_id}/events")
    resp.raise_for_status()
    return resp.json()


def _probe_runs(client: httpx.Client, monitor_id: int) -> list[dict]:
    """Newest first. `limit` is pinned at the route's maximum rather than left
    at its 20-row default: a monitor polling every 30s through a multi-minute
    outage produces more runs than that, and a silently truncated list would
    turn "the scheduler kept opening runs" into an assertion that stops being
    true for the wrong reason."""
    resp = client.get(f"/api/v1/monitors/{monitor_id}/probe-runs", params={"limit": 200})
    resp.raise_for_status()
    return resp.json()


def _probe_run(client: httpx.Client, monitor_id: int, run_id: str) -> dict:
    for run in _probe_runs(client, monitor_id):
        if run["run_id"] == run_id:
            return run
    raise AssertionError(f"run {run_id} is no longer in monitor {monitor_id}'s run history")


def _probe_eligible_row(
    client: httpx.Client, agent_id: int, *, host: str, check_type: str = "icmp"
) -> dict:
    """§7's eligible-agent listing, reduced to the one agent this stack has."""
    resp = client.get(
        "/api/v1/agents/probe-eligible", params={"host": host, "check_type": check_type}
    )
    resp.raise_for_status()
    for row in resp.json():
        if row["agent_id"] == agent_id:
            return row
    raise AssertionError(f"agent {agent_id} is absent from probe-eligible for {host}")


@pytest.mark.e2e
def test_remote_probe_assignment_execution_and_unavailability():
    """Slice 3 §9's acceptance list, steps 1-6 and 9-11, in one stack lifetime.

    The premise is step 1 and it is asserted before anything else: probe-target
    sits on probe-net, circuitbreaker does not, and Docker's inter-bridge
    isolation means the backend has no route to 10.77.0.10 at all. Every
    "the check succeeded" assertion below therefore has exactly one possible
    explanation — the agent ran it — and the check that closes the test (step
    10) proves the converse by returning a monitor to server execution and
    watching it go DOWN against the same address the agent had UP.

    Steps 7 (narrowing scope refuses on both ends) and 8 (fair sharing under
    concurrency) are not repeated here: both are pinned by named unit tests on
    both sides of the wire, and neither needs a container to be true. What
    genuinely needs this harness is the parts where a real agent, a real
    partition and a real scheduler interact.

    Step 9 is exercised with the vantage this single-agent stack has: the
    monitor is reassigned away from the agent while a run is genuinely in
    flight (an HTTP check against a CGI endpoint that sleeps past its own
    deadline), which retires the run through the same
    `CANCEL_MONITOR_REASSIGNED` path a hand-off to a second agent takes. The
    PATCH route is synchronous, so `_publish_soon` finds no running loop and
    the advisory `probe.cancel` is never delivered — the agent runs the check
    to its deadline and posts a result for a run the server has already closed,
    which is precisely the "old vantage's late result" §9 step 9 is about. What
    is observable is that the result changes nothing: the run row keeps the
    cancellation the server wrote, `outcome` stays NULL (it records what the
    agent reported, and the agent's report was refused), and the monitor's
    `probe_last_result_at` is never set.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        _up_fixture_target(_PROBE_TARGET_SERVICE)

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=20,
            )
            _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)

            # ---- Step 1: the backend genuinely cannot reach the target ----
            # Asserted first because it is the premise of every later
            # assertion. `getent` is checked too: the DNS monitor names
            # `probe-target` as the record to look up, and
            # probe_eligibility.evaluate_eligibility resolves any non-literal
            # host on the SERVER before it will dispatch. The name resolving
            # (docker-compose.yml's extra_hosts) while the address stays
            # unroutable is what makes that monitor dispatchable without
            # weakening the isolation this step exists to prove.
            getent = _backend_sh(f"getent hosts {_PROBE_TARGET_NAME}")
            assert getent.returncode == 0 and getent.stdout.split()[0] == _PROBE_TARGET_IP, (
                f"the backend cannot resolve {_PROBE_TARGET_NAME} — docker-compose.yml's "
                f"extra_hosts entry is missing: {getent.stdout!r} {getent.stderr!r}"
            )
            for description, command in (
                ("ICMP", f"ping -c 2 -W 2 {_PROBE_TARGET_IP}"),
                ("TCP", f"nc -z -w 3 {_PROBE_TARGET_IP} {_PROBE_TARGET_HTTP_PORT}"),
                ("DNS/TCP", f"nc -z -w 3 {_PROBE_TARGET_IP} 53"),
                ("HTTP", f"curl -sS -m 5 -o /dev/null http://{_PROBE_TARGET_IP}:{_PROBE_TARGET_HTTP_PORT}/"),
            ):
                probe = _backend_sh(command)
                assert probe.returncode != 0, (
                    f"the backend reached the probe target over {description} — probe-net is "
                    "not isolated from circuitbreaker, and every remote-probe assertion in "
                    "this test would be unable to tell an agent-executed check from a "
                    "server-executed one"
                )

            # ---- Step 11: eligible on the agent's own reported networks,
            # with no scope edit whatsoever ----
            # Nothing in this test ever PUTs /capabilities. The agent was
            # provisioned by _enroll_agent (the Slice 1 install path) and the
            # only thing that put 10.77.0.0/24 in its scope is the interface
            # facts it reported in `hello`.
            _wait_until(
                lambda: _probe_eligible_row(client, agent_id, host=_PROBE_TARGET_IP)["eligible"],
                timeout=_PROBE_FIRST_RESULT_BUDGET_S,
            )
            eligible = _probe_eligible_row(client, agent_id, host=_PROBE_TARGET_IP)
            assert eligible["in_scope"] is True, eligible
            assert eligible["reason"] is None, eligible
            assert eligible["granted"] is True and eligible["online"] is True, eligible
            assert eligible["readiness"] == "ready", eligible
            assert eligible["readiness_collector"] == "probe.icmp", eligible
            assert eligible["max_concurrent"] == 20, eligible
            assert _PROBE_NET_CIDR in eligible["scope_networks"], (
                f"{_PROBE_NET_CIDR} is not in the agent's derived scope {eligible['scope_networks']} "
                "— the directly-connected facts in `hello` did not produce it, and §9 step 11 "
                "(select the agent without first editing scope) does not hold"
            )
            grant = client.get(f"/api/v1/agents/{agent_id}").json()["capabilities"]["remote_probe"]
            assert grant == {
                "enabled": True,
                "config": {
                    "max_concurrent": 20,
                    "scope_mode": "direct_private",
                    "excluded_cidrs": [],
                    "additional_cidrs": [],
                    "additional_hostnames": [],
                },
            }, "the remote_probe grant is not the untouched approval default"

            # ---- Steps 2-3: one monitor per check type, all on the agent ----
            common = {
                "interval_secs": _PROBE_INTERVAL_S,
                "max_retries": 0,
                "enabled": True,
                "probe_agent_id": agent_id,
            }
            monitors = {
                "icmp": _create_monitor(
                    client,
                    name="e2e remote icmp",
                    check_type="icmp",
                    host=_PROBE_TARGET_IP,
                    config={"packet_count": 3, "timeout": 1.5},
                    **common,
                ),
                "tcp": _create_monitor(
                    client,
                    name="e2e remote tcp",
                    check_type="tcp",
                    host=_PROBE_TARGET_IP,
                    config={"port": _PROBE_TARGET_HTTP_PORT, "timeout": 2.0},
                    **common,
                ),
                "http": _create_monitor(
                    client,
                    name="e2e remote http",
                    check_type="http",
                    host=_PROBE_TARGET_IP,
                    config={"url": f"http://{_PROBE_TARGET_IP}:{_PROBE_TARGET_HTTP_PORT}/"},
                    **common,
                ),
                # The one monitor whose host is a NAME rather than a literal:
                # it is resolved on the server (extra_hosts) to decide scope,
                # resolved again on the agent (Docker DNS) immediately before
                # connecting, and the resolver it queries — probe-target's own
                # dnsmasq — is itself scope-checked by the agent (§3).
                "dns": _create_monitor(
                    client,
                    name="e2e remote dns",
                    check_type="dns",
                    host=_PROBE_TARGET_NAME,
                    config={
                        "record_type": "A",
                        "resolver": _PROBE_TARGET_IP,
                        "expected_values": [_PROBE_TARGET_IP],
                        "timeout": 5.0,
                    },
                    **common,
                ),
            }
            for check_type, monitor in monitors.items():
                assert monitor["probe_mode"] == "agent", (check_type, monitor)
                assert monitor["probe_agent_id"] == agent_id, (check_type, monitor)
                assert monitor["probe_agent"]["id"] == agent_id, (check_type, monitor)
                assert monitor["status"] == "pending", (check_type, monitor)

            # ---- Step 3: results enter the existing history/state pipeline
            # ---- Step 4 (first half): identical event and uptime semantics
            for check_type, created in monitors.items():
                monitor_id = created["id"]

                def _is_up(monitor_id: int = monitor_id) -> dict | None:
                    current = _monitor(client, monitor_id)
                    if current["status"] == "up" and current["probe_execution_status"] == "ready":
                        return current
                    return None

                current = _wait_until_and_return(_is_up, timeout=_PROBE_FIRST_RESULT_BUDGET_S)
                assert current["probe_execution_reason"] is None, (check_type, current)
                assert current["probe_last_dispatched_at"] is not None, (check_type, current)
                assert current["probe_last_result_at"] is not None, (check_type, current)

                # The samples are ordinary monitor telemetry — same table, same
                # metric names, same `source="monitor"` — which is what lets
                # uptime and the history graph aggregate agent-executed and
                # server-executed checks without splitting the denominator.
                avail = _monitor_samples(client, monitor_id, "avail")
                assert avail and set(avail) == {1.0}, (check_type, avail)
                assert _monitor_samples(client, monitor_id, "latency_ms"), check_type
                uptime = client.get(f"/api/v1/monitors/{monitor_id}/uptime").json()
                assert uptime["pct_24h"] == 100.0, (check_type, uptime)
                assert uptime["last_polled_at"] is not None, (check_type, uptime)

                # One transition, recorded by the shared state machine — not an
                # execution event and not a second "up" per check.
                events = _monitor_events(client, monitor_id)
                # `execution` events describe the vantage, never the target, so
                # they are filtered out of the transition log rather than
                # asserted absent — §7 is explicit that the two must not fold
                # into one another.
                transitions = [e for e in events if e["event_type"] != "execution"]
                assert [e["event_type"] for e in transitions] == ["up"], (check_type, events)
                assert transitions[0]["status_from"] == "pending", (check_type, events)
                assert transitions[0]["status_to"] == "up", (check_type, events)

                # And the vantage's own audit trail, which a server-executed
                # check has none of.
                runs = _probe_runs(client, monitor_id)
                assert runs, check_type
                completed = [r for r in runs if r["status"] == "completed"]
                assert completed, (check_type, runs)
                assert completed[0]["outcome"] == "completed", (check_type, completed[0])
                assert completed[0]["agent_id"] == agent_id, (check_type, completed[0])
                assert completed[0]["error_code"] is None, (check_type, completed[0])
                assert completed[0]["started_at"] is not None, (check_type, completed[0])

            # ---- Step 4 (second half): retries and the down/alert path are
            # the same code for both vantages ----
            # A closed port on the same target: a genuine target failure, not
            # an execution error, so it goes through `state.decide` exactly as a
            # server-executed failure does. DOWN is the transition that carries
            # `notify="down"` into result_service's alert publish, and that is
            # one implementation for both vantages rather than two that agree.
            retry_monitor = _create_monitor(
                client,
                name="e2e remote tcp closed port",
                check_type="tcp",
                host=_PROBE_TARGET_IP,
                config={"port": _PROBE_TARGET_CLOSED_PORT, "timeout": 2.0},
                interval_secs=_PROBE_INTERVAL_S,
                retry_interval_secs=10,
                max_retries=1,
                enabled=True,
                probe_agent_id=agent_id,
            )
            retry_id = retry_monitor["id"]

            def _is_down() -> dict | None:
                current = _monitor(client, retry_id)
                return current if current["status"] == "down" else None

            down = _wait_until_and_return(_is_down, timeout=_PROBE_FIRST_RESULT_BUDGET_S)
            assert down["probe_mode"] == "agent", down
            retry_events = [
                e for e in _monitor_events(client, retry_id) if e["event_type"] != "execution"
            ]
            # Exactly ONE transition, and it is the DOWN. `state.decide` records
            # a `pending` event only on a *change into* PENDING, and a freshly
            # created monitor already starts there — so the retry that
            # max_retries=1 buys is silent in the event log for a monitor that
            # has never been UP. That is pre-existing shared behaviour, not
            # something the agent vantage changes, which is the point: the event
            # log a remote check produces is the one a server check produces.
            assert [e["event_type"] for e in retry_events] == ["down"], retry_events
            assert retry_events[0]["status_from"] == "pending", retry_events
            assert retry_events[0]["status_to"] == "down", retry_events
            avail = _monitor_samples(client, retry_id, "avail")
            assert set(avail) == {0.0}, (retry_id, avail)
            # The retry itself, asserted where it IS observable: DOWN was not
            # declared on the first failure. With max_retries=1 the state
            # machine owes a second observation — pulled in to
            # retry_interval_secs rather than waiting a full interval — before
            # it may transition, so there has to be more than one sample behind
            # this transition.
            assert len(avail) >= 2, (
                "the monitor went DOWN on its first failed check; max_retries=1 was not "
                f"honoured for an agent-executed check ({avail})"
            )
            # Failure carries no latency sample (the parity contract's TCP row).
            assert _monitor_samples(client, retry_id, "latency_ms") == [], retry_id

            # ---- Step 5: the vantage goes away; the target's state does not
            icmp_id = monitors["icmp"]["id"]
            events_before_cut = _monitor_events(client, icmp_id)
            runs_before_cut = len(_probe_runs(client, icmp_id))
            result_at_before_cut = _monitor(client, icmp_id)["probe_last_result_at"]

            with _cut_agent_network():
                # The agent learns about a black hole only from silence — a
                # full readTimeout — and the server only after its presence
                # key expires. Both are paid here on purpose; see
                # _cut_agent_network's docstring and _PROBE_UNAVAILABLE_BUDGET_S.
                _wait_until(
                    lambda: _agent_status()["link_state"] == "disconnected",
                    timeout=_PROBE_UNAVAILABLE_BUDGET_S,
                )

                def _is_unavailable() -> dict | None:
                    current = _monitor(client, icmp_id)
                    return current if current["probe_execution_status"] == "unavailable" else None

                unavailable = _wait_until_and_return(
                    _is_unavailable, timeout=_PROBE_UNAVAILABLE_BUDGET_S
                )
                # §2's vocabulary: we know *why* the vantage cannot run the
                # check. Which of these lands depends only on whether the
                # presence key expired before or after the next scheduler tick.
                assert unavailable["probe_execution_reason"] in {
                    "agent_offline",
                    "no_link_owner",
                    "dispatch_failed",
                    "result_timeout",
                }, unavailable
                # The target is still up as far as anyone knows, and the
                # assignment is retained — an unavailable vantage never falls
                # back to the server (§2, and step 10 below is the only way
                # back).
                assert unavailable["status"] == "up", unavailable
                assert unavailable["probe_agent_id"] == agent_id, unavailable

                # Give it two more intervals so this is "no avail=0 sample for
                # the whole outage", not "none in the first second of it".
                time.sleep(_PROBE_INTERVAL_S * 2)

                during = _monitor(client, icmp_id)
                assert during["status"] == "up", during
                assert during["probe_agent_id"] == agent_id, during
                assert during["probe_last_result_at"] == result_at_before_cut, (
                    "probe_last_result_at moved while the agent was unreachable — something "
                    "wrote a result the agent cannot have produced"
                )
                assert set(_monitor_samples(client, icmp_id, "avail")) == {1.0}, (
                    "an avail=0 sample was written while the vantage was unavailable — §2/D-12 "
                    "forbid it: agent unavailability is not target downtime, and this sample "
                    "would corrupt uptime for the outage's whole duration"
                )
                assert client.get(f"/api/v1/monitors/{icmp_id}/uptime").json()["pct_24h"] == 100.0

                # No target transition was recorded either. The execution
                # condition may add `execution` events (one per change of
                # reason, §6) and those carry the target's state through
                # unchanged rather than rewriting it.
                events_during = _monitor_events(client, icmp_id)
                new_events = events_during[: len(events_during) - len(events_before_cut)]
                assert {e["event_type"] for e in new_events} <= {"execution"}, new_events
                for event in new_events:
                    assert event["status_from"] == "up" and event["status_to"] == "up", event

                # The runs the scheduler kept opening were all closed rather
                # than left in flight — a run stuck in `queued`/`dispatched`
                # holds the partial unique index and would wedge this monitor
                # for good. A run legitimately stays `dispatched` until
                # deadline_at (scheduled_at + 20s) plus the reconciliation
                # pass's 30s grace, so only rows well past that are evidence of
                # a wedge rather than of a lease still running its course.
                wedged = [
                    r
                    for r in _probe_runs(client, icmp_id)
                    if r["status"] in ("queued", "dispatched")
                    and _parse_ts(r["scheduled_at"])
                    < datetime.now(timezone.utc) - timedelta(seconds=120)
                ]
                assert not wedged, (
                    "a probe run is still in flight long past its lease after the agent "
                    f"vanished — the monitor is wedged behind the partial unique index: {wedged}"
                )
                assert len(_probe_runs(client, icmp_id)) > runs_before_cut, (
                    "the scheduler stopped opening runs for an assigned monitor whose agent is "
                    "offline — the monitor has to keep trying on its normal interval (§2)"
                )

            # ---- Step 6: the route comes back and the warning clears ----
            _wait_until(
                lambda: _agent_status()["link_state"] == "accepted",
                timeout=_PROBE_RECONNECT_BUDGET_S,
            )
            _wait_until(
                lambda: _probe_eligible_row(client, agent_id, host=_PROBE_TARGET_IP)["online"],
                timeout=_PROBE_RECONNECT_BUDGET_S,
            )

            # "Check now" is accepted again rather than answering D-14's 409.
            # It is retried because a scheduled run may legitimately be in
            # flight at any moment (409 `previous_run_in_flight`), which is a
            # different answer from "this vantage cannot take the check".
            refusals: list[str] = []
            deadline = time.monotonic() + 120
            while True:
                accepted = client.post(f"/api/v1/monitors/{icmp_id}/check")
                if accepted.status_code == 200:
                    break
                assert accepted.status_code == 409, accepted.text
                refusals.append(str(accepted.json().get("detail")))
                assert time.monotonic() < deadline, (
                    "check-now never stopped answering 409 after the route was restored; "
                    f"reasons seen: {sorted(set(refusals))}"
                )
                time.sleep(2)

            def _cleared() -> dict | None:
                current = _monitor(client, icmp_id)
                if current["probe_execution_status"] != "ready":
                    return None
                if current["probe_last_result_at"] == result_at_before_cut:
                    return None
                return current

            cleared = _wait_until_and_return(_cleared, timeout=_PROBE_RECONNECT_BUDGET_S)
            assert cleared["probe_execution_reason"] is None, cleared
            assert cleared["status"] == "up", cleared
            assert set(_monitor_samples(client, icmp_id, "avail")) == {1.0}, (
                "the outage left an avail=0 sample behind after all"
            )

            # ---- Step 9: reassignment retires the run; the old vantage's
            # late result is inert ----
            slow_monitor = _create_monitor(
                client,
                name="e2e remote http slow",
                check_type="http",
                host=_PROBE_TARGET_IP,
                # /cgi-bin/slow sleeps for two minutes, so this check cannot
                # finish before the run's own 20s deadline — which is what
                # gives the reassignment below a genuinely in-flight run to
                # take away instead of a race against a millisecond check.
                config={
                    "url": f"http://{_PROBE_TARGET_IP}:{_PROBE_TARGET_HTTP_PORT}/cgi-bin/slow",
                    "timeout": 100.0,
                },
                # Long enough that the scheduler opens exactly one run for it
                # during this test, and never a second one after the monitor
                # returns to server execution.
                interval_secs=600,
                max_retries=0,
                enabled=True,
                probe_agent_id=agent_id,
            )
            slow_id = slow_monitor["id"]

            def _dispatched_run() -> dict | None:
                for run in _probe_runs(client, slow_id):
                    if run["status"] == "dispatched":
                        return run
                return None

            in_flight = _wait_until_and_return(_dispatched_run, timeout=120)
            run_id = in_flight["run_id"]
            assert in_flight["agent_id"] == agent_id, in_flight
            assert in_flight["dispatched_at"] is not None, in_flight

            reassign = client.patch(
                f"/api/v1/monitors/{slow_id}", json={"probe_agent_id": None}
            )
            assert reassign.status_code == 200, reassign.text
            assert reassign.json()["probe_mode"] == "server", reassign.text
            assert reassign.json()["probe_agent_id"] is None, reassign.text
            # The previous vantage's condition is cleared with it: it says
            # nothing about the new one.
            assert reassign.json()["probe_execution_status"] is None, reassign.text

            cancelled = _probe_run(client, slow_id, run_id)
            assert cancelled["status"] == "cancelled", cancelled
            assert cancelled["error_code"] == "monitor_reassigned", cancelled
            assert cancelled["outcome"] is None, cancelled

            # The agent was never told (the PATCH route is synchronous, so the
            # advisory probe.cancel had no loop to publish on), so it keeps
            # running the check and posts a result for this run once its
            # deadline expires. Wait past that, with the link verifiably up and
            # nothing left in the spool, so the frame has demonstrably been
            # written to the server.
            time.sleep(60)
            assert _agent_status()["link_state"] == "accepted"
            assert _agent_status()["spool_depth"] == 0, (
                "the agent still has frames queued, so the result it posted for the retired run "
                "may not have reached the server yet and the assertion below would be vacuous"
            )

            after_late_result = _probe_run(client, slow_id, run_id)
            assert after_late_result == cancelled, (
                "the old vantage's result was applied to a run the server had already retired: "
                f"{cancelled} -> {after_late_result}"
            )
            slow_after = _monitor(client, slow_id)
            assert slow_after["probe_last_result_at"] is None, slow_after
            assert slow_after["probe_execution_status"] is None, slow_after
            assert _monitor_events(client, slow_id) == [], (
                "the retired run's result moved the monitor's target state"
            )

            # ---- Step 10: back to server execution, and only by asking ----
            # The HTTP monitor has been UP for the whole test from the agent's
            # vantage. The server cannot reach that address at all (step 1), so
            # flipping the vantage — and nothing else about the monitor — must
            # turn it DOWN. That is the sharpest available proof that the check
            # really did move, and the converse of every earlier assertion.
            http_id = monitors["http"]["id"]
            runs_before_return = len(_probe_runs(client, http_id))
            assert _monitor(client, http_id)["status"] == "up"

            returned = client.patch(f"/api/v1/monitors/{http_id}", json={"probe_agent_id": None})
            assert returned.status_code == 200, returned.text
            assert returned.json()["probe_mode"] == "server", returned.text
            assert returned.json()["probe_agent"] is None, returned.text

            def _server_executed() -> dict | None:
                current = _monitor(client, http_id)
                return current if current["status"] == "down" else None

            server_down = _wait_until_and_return(
                _server_executed, timeout=_PROBE_FIRST_RESULT_BUDGET_S
            )
            assert server_down["probe_execution_status"] is None, server_down
            assert 0.0 in _monitor_samples(client, http_id, "avail"), server_down
            assert _monitor_events(client, http_id)[0]["event_type"] == "down"
            assert len(_probe_runs(client, http_id)) == runs_before_return, (
                "a probe run was opened for a monitor that is back on server execution"
            )

            # ...and the vantage that was taken away is still working for the
            # monitors that kept it, which is what makes step 10 a per-monitor
            # user action rather than a global fallback.
            assert _monitor(client, icmp_id)["probe_mode"] == "agent"
            assert _monitor(client, icmp_id)["status"] == "up"
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Task 31: the harness itself (D-12)
# ─────────────────────────────────────────────────────────────────────────

# Long enough for hello -> registry -> readiness ingest to land, on the same
# order as this file's other first-signal budgets. Nothing here waits on a
# scheduler tick or a check, so it is well short of _PROBE_FIRST_RESULT_BUDGET_S.
_TOPOLOGY_PROPAGATION_BUDGET_S = 120

# The port nginx listens on INSIDE the mono container (repo-root
# docker-compose.yml maps ${CB_PORT_HTTPS} to it). Used only as the positive
# control for `nc` in the isolation loop below.
_BACKEND_HTTPS_PORT = 8443


@pytest.mark.e2e
def test_e2e_harness_topology_is_pinned_and_two_agents_stay_isolated():
    """Task 31 (D-12): the harness's own topology, asserted before Tasks 32-33
    are allowed to rest on it.

    This test pins the four properties every Slice 4 discovery assertion will
    quietly assume, and it exists because assuming them is exactly how an E2E
    test comes to prove nothing:

    1. **The subnets are the pinned ones.** `agent-net` was an unpinned bridge
       until D-12, so Docker handed it a /16 — 65 534 addresses, more than the
       local_discovery grant's `max_addresses_per_job` (1024) on its own, which
       means the agent's own directly connected subnet could never have been
       dispatched as a discovery target at all. Every subnet is now hand-pinned
       and read back LIVE from Docker here, not trusted from the compose file:
       an `ipam.config` entry Docker declined (a pool collision, a stale network
       from a previous run) would otherwise surface minutes later as an
       inexplicable scope mismatch inside a discovery test.

    2. **A host, and then a whole subnet, can appear after the agent is
       already running.** `probe-target-new` starts on probe-net with the
       topology otherwise untouched — the agent's routing table does not
       change, only the set of hosts answering on a subnet it has already
       scanned, which is plan §8 step 11's "genuinely new device". `late-net`
       does not exist when cb-agent starts. `late-target` is brought up
       mid-test and cb-agent is attached to it afterwards, so a directly
       connected network materializes on an already-enrolled, already-approved,
       already-connected agent — no CIDR typed, no agent-side file touched,
       nothing told to the server. The assertion that matters is not that the
       route appears in `docker inspect` (host-side metadata) but that it
       appears in the agent's own kernel routing table AND then in the scope
       the SERVER derives for it after one reconnect. That is the entire
       zero-configuration trigger, reduced to its mechanism.

    3. **`_agent_network_name` still identifies the route to the server once
       the topology grows.** Its assertion used to be `suffixes ==
       {"agent-net", "probe-net"}`, which step 2 above makes false and which a
       second agent makes false twice over. It is now required-subset plus
       allowed-superset (see `_AGENT_TOPOLOGY`), and this test exercises both
       the legitimate growth it must now permit and, via cb-agent-2, a
       completely different legal shape.

    4. **Two agents are genuinely two agents.** Separate outbound networks,
       separate fixture subnets, separate state volumes, separate device keys,
       separate agent ids — and, the part that actually matters for provenance,
       each one's kernel routing table contains its own fixture subnet and NOT
       the other's. Without that, "agent 2 discovered 10.78.0.10" is a claim
       about which row the backend happened to write, not about which host
       could see what.

    And throughout, the negative: the backend is made to try, and fail, to
    reach all three fixture subnets over both ICMP and TCP. Slice 4's central
    claim is that an agent discovers hosts the backend cannot reach; a
    discovery result in the database is evidence of that only for as long as
    this loop keeps failing. It is asserted here, in the harness test, so
    Tasks 32-33 inherit a topology whose isolation has already been
    demonstrated rather than assumed.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        # ---- (1) the pinned subnets, read back from the live networks ----
        # agent-net and agent-net-2 both exist as soon as circuitbreaker is up,
        # because it is attached to both; the fixture networks are created as
        # their targets are brought up below.
        assert _network_subnet(_AGENT_NET) == _AGENT_NET_CIDR, (
            f"agent-net is {_network_subnet(_AGENT_NET)}, not the pinned "
            f"{_AGENT_NET_CIDR} (D-12) — Docker declined the ipam.config entry, and "
            "the agent's own directly connected subnet is back to being too wide to "
            "dispatch as a discovery target"
        )
        assert _network_subnet(_AGENT_2_NET) == _AGENT_2_NET_CIDR

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        _up_fixture_target(_PROBE_TARGET_SERVICE)
        assert _network_subnet(_PROBE_NET) == _PROBE_NET_CIDR

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )
            _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)

            # ---- (3a) the relaxed helper on the topology it started with ----
            container, server_net = _agent_network_name()
            assert server_net.rsplit("_", 1)[-1] == _AGENT_NET, server_net
            assert _agent_attachments() == {_AGENT_NET, _PROBE_NET}

            agent_ip = _container_ipv4(container, server_net)
            assert ipaddress.ip_address(agent_ip) in ipaddress.ip_network(_AGENT_NET_CIDR), (
                f"cb-agent's address on agent-net is {agent_ip}, outside the pinned "
                f"{_AGENT_NET_CIDR}"
            )
            assert _agent_route_networks() == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                "cb-agent's own routing table — the state hostinfo.Networks() reports "
                "in every hello — does not match the pinned topology"
            )

            # The server's derived view of the same thing, with no scope edit
            # of any kind: both pinned subnets are directly connected private
            # networks, so `direct_private` must contain both and nothing that
            # was never plugged in.
            def _scope(aid: int) -> list[str]:
                return _probe_eligible_row(client, aid, host=_PROBE_TARGET_IP)["scope_networks"]

            _wait_until(
                lambda: _AGENT_NET_CIDR in _scope(agent_id),
                timeout=_TOPOLOGY_PROPAGATION_BUDGET_S,
            )
            assert set(_scope(agent_id)) == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, _scope(agent_id)

            # ---- (2a) a new host on a subnet the agent already has ----
            # No topology change at all: probe-net is unchanged, the agent's
            # routing table is unchanged, and only the set of hosts answering
            # on 10.77.0.0/24 is different. That is the stimulus plan §8 step
            # 11's "genuinely new device" needs, and it must stay unreachable
            # from the backend exactly as its neighbour is.
            routes_before_new_host = _agent_route_networks()
            _up_fixture_target(_PROBE_TARGET_NEW_SERVICE)
            assert _agent_route_networks() == routes_before_new_host, (
                "starting a second host on probe-net changed the agent's routing "
                "table — it is not on the subnet the agent already knows"
            )
            assert ipaddress.ip_address(_PROBE_TARGET_NEW_IP) in ipaddress.ip_network(
                _PROBE_NET_CIDR
            )

            # ---- (2b) a subnet that arrives after the agent is running ----
            _up_fixture_target(_LATE_TARGET_SERVICE)
            assert _network_subnet(_LATE_NET) == _LATE_NET_CIDR
            assert _LATE_NET not in _agent_attachments(), (
                "starting late-target attached cb-agent to late-net by itself — the "
                "'the agent did not have this subnet a moment ago' half of the trigger "
                "is not being exercised"
            )
            assert _LATE_NET_CIDR not in _agent_route_networks()

            _attach_agent_to_late_net()
            assert _agent_attachments() == {_AGENT_NET, _PROBE_NET, _LATE_NET}
            assert _agent_route_networks() == {
                _AGENT_NET_CIDR,
                _PROBE_NET_CIDR,
                _LATE_NET_CIDR,
            }, "the late subnet is not in the agent's own routing table"

            # ---- (3b) ...and the helper still finds the route to the server ----
            # This is the assertion the pre-Slice-4 exact-set version fails:
            # a third, entirely legitimate attachment made `_agent_network_name`
            # raise, which would have taken down _cut_agent_network and every
            # test built on it.
            assert _agent_network_name() == (container, server_net), (
                "_agent_network_name no longer resolves the route to the server once "
                "the agent legitimately gains a subnet"
            )

            # The server learns from the next hello and from nothing else:
            # hostinfo.Collect() runs per connection. `restart`, not
            # `up --force-recreate`, or the attachment under test is undone.
            assert _LATE_NET_CIDR not in _scope(agent_id), (
                "the server already has the late subnet in scope without a reconnect — "
                "then this test is not observing hello-carried network facts and "
                "something else is supplying them"
            )
            subprocess.run([*COMPOSE, "restart", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
            _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=60)
            _wait_until(
                lambda: _LATE_NET_CIDR in _scope(agent_id),
                timeout=_TOPOLOGY_PROPAGATION_BUDGET_S,
            )
            assert set(_scope(agent_id)) == {
                _AGENT_NET_CIDR,
                _PROBE_NET_CIDR,
                _LATE_NET_CIDR,
            }, _scope(agent_id)
            assert _agent_attachments() == {_AGENT_NET, _PROBE_NET, _LATE_NET}, (
                "the restart dropped the runtime attachment — the helper must use "
                "`compose restart`, never a recreate"
            )

            # ---- (4) the second agent, enrolled through the same one path ----
            _up_fixture_target(_PROBE_TARGET_2_SERVICE)
            assert _network_subnet(_PROBE_NET_2) == _PROBE_NET_2_CIDR

            agent2_id, stream2 = _enroll_agent(client, headers, service=_AGENT_2_SERVICE)
            try:
                subprocess.run(
                    [*COMPOSE, "up", "-d", _AGENT_2_SERVICE], check=True, cwd=E2E_DIR
                )
                _wait_until(
                    lambda: client.get(f"/api/v1/agents/{agent2_id}").json()["status"]
                    == "active",
                    timeout=30,
                )
                _wait_until(
                    lambda: _agent_status(service=_AGENT_2_SERVICE)["link_state"] == "accepted",
                    timeout=30,
                )

                assert agent2_id != agent_id
                assert client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active", (
                    "enrolling a second agent disturbed the first one"
                )

                # Separate state volumes, proven by the one file that would be
                # shared if they were not: the device key is the agent's
                # identity, so an identical digest here would mean the two
                # containers are one agent presenting the same certificate
                # twice, whatever the two agent ids suggest.
                assert _device_key(_AGENT_SERVICE) != _device_key(_AGENT_2_SERVICE), (
                    "both agent containers hold the same device.key — cb-agent-2 is "
                    "sharing cb-agent's state volume and is not a second agent at all"
                )

                # A different legal attachment shape entirely, through the same
                # relaxed helper.
                container2, server_net2 = _agent_network_name(service=_AGENT_2_SERVICE)
                assert container2 != container
                assert server_net2.rsplit("_", 1)[-1] == _AGENT_2_NET, server_net2
                assert _agent_attachments(service=_AGENT_2_SERVICE) == {
                    _AGENT_2_NET,
                    _PROBE_NET_2,
                }

                # The provenance-critical half: each agent's kernel sees its own
                # fixture subnet and not the other's. Without this, a finding
                # attributed to one agent could have been produced from either
                # vantage and the attribution would be unfalsifiable.
                assert _agent_route_networks(service=_AGENT_2_SERVICE) == {
                    _AGENT_2_NET_CIDR,
                    _PROBE_NET_2_CIDR,
                }
                assert _PROBE_NET_CIDR not in _agent_route_networks(service=_AGENT_2_SERVICE)
                assert _LATE_NET_CIDR not in _agent_route_networks(service=_AGENT_2_SERVICE)
                assert _PROBE_NET_2_CIDR not in _agent_route_networks()

                # ...and the server derives exactly that, per agent, from the
                # hello facts alone.
                _wait_until(
                    lambda: _PROBE_NET_2_CIDR in _scope(agent2_id),
                    timeout=_TOPOLOGY_PROPAGATION_BUDGET_S,
                )
                assert set(_scope(agent2_id)) == {_AGENT_2_NET_CIDR, _PROBE_NET_2_CIDR}
                assert _probe_eligible_row(client, agent2_id, host=_PROBE_TARGET_IP)[
                    "in_scope"
                ] is False, (
                    "the server considers agent 2 in scope for agent 1's fixture subnet"
                )
                assert _probe_eligible_row(client, agent_id, host=_PROBE_TARGET_2_IP)[
                    "in_scope"
                ] is False, (
                    "the server considers agent 1 in scope for agent 2's fixture subnet"
                )

                # ---- the negative, for all three fixture subnets ----
                # Every Slice 4 assertion of the form "the agent found a host
                # the backend cannot reach" is worth exactly as much as this
                # loop. Run last so it covers the topology as it finally
                # stands, including the subnet that arrived mid-test.
                #
                # Positive controls first, because a loop of `assert
                # returncode != 0` is satisfied just as well by a missing
                # binary, a dropped capability or a typo as by an absent
                # route — and the resulting test would pass forever while
                # proving nothing. The backend container drops ALL caps and
                # adds back NET_RAW (repo-root docker-compose.yml), so ICMP
                # is *supposed* to work from here; it is demonstrated against
                # cb-agent's own agent-net address, a network the backend IS
                # on. `nc` is demonstrated against the backend's own HTTPS
                # listener, the one open TCP port it can reach at all.
                reachable = _backend_sh(f"ping -c 2 -W 2 {agent_ip}")
                assert reachable.returncode == 0, (
                    "the backend cannot ICMP a host on a network it is attached to, so "
                    "every 'the backend could not reach it' assertion below would hold "
                    "even with no isolation at all: "
                    f"{reachable.stdout!r} {reachable.stderr!r}"
                )
                listening = _backend_sh(f"nc -z -w 3 127.0.0.1 {_BACKEND_HTTPS_PORT}")
                assert listening.returncode == 0, (
                    "`nc` cannot connect to the backend's own open port, so the TCP half "
                    "of the isolation loop below proves nothing: "
                    f"{listening.stdout!r} {listening.stderr!r}"
                )
                for subnet, address in (
                    (_PROBE_NET_CIDR, _PROBE_TARGET_IP),
                    (_PROBE_NET_CIDR, _PROBE_TARGET_NEW_IP),
                    (_LATE_NET_CIDR, _LATE_TARGET_IP),
                    (_PROBE_NET_2_CIDR, _PROBE_TARGET_2_IP),
                ):
                    for description, command in (
                        ("ICMP", f"ping -c 2 -W 2 {address}"),
                        ("TCP", f"nc -z -w 3 {address} {_PROBE_TARGET_HTTP_PORT}"),
                    ):
                        probe = _backend_sh(command)
                        assert probe.returncode != 0, (
                            f"the backend reached {address} on {subnet} over {description} "
                            "— that subnet is not isolated from circuitbreaker, and no "
                            "discovery result found there could be attributed to an agent "
                            f"rather than to the server: {probe.stdout!r} {probe.stderr!r}"
                        )
            finally:
                stream2.close()
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Slice 4 Task 32: zero-configuration discovery, plan §8 steps 1-7
# ─────────────────────────────────────────────────────────────────────────
#
# One install command, one ordinary approval, and no CIDR typed anywhere.
# The budgets below are wall-clock ceilings, not expectations — every one of
# them is `_wait_until`'s timeout, so a scenario that gets there sooner pays
# nothing.

# Approval -> the agent's first readiness frame -> `discovery_bootstrap`'s
# deferred pass. The hello that carries `networks` arrives before any collector
# readiness row exists, so the *first* pass is refused `readiness_unknown` and
# it is the readiness frame behind it that does the work (see
# discovery_bootstrap.run_bootstrap). Generous because that frame rides the
# agent's own reconcile ticker.
_DISCOVERY_BOOTSTRAP_BUDGET_S = 240

# The automatic first scan: `initial_scan_delay_s` is 5 + (agent_id % 60)
# seconds of deliberate jitter (D-7) before the dispatch is even published,
# then two /24 sweeps at the default `max_concurrent_hosts` of 64 and a
# 1500 ms per-host budget, which may or may not share a concurrency slot.
_INITIAL_SCAN_BUDGET_S = 420

# From "the backend answers again" to "the agent's spool is empty". Dominated
# by internal/link's reconnect backoff (1s doubling), not by the drain itself,
# which is paced at 4 frames per 100 ms.
_SPOOL_DRAIN_BUDGET_S = 240

# Plan §3: an agent profile carries exactly this scan type and nothing else.
_AGENT_SCAN_TYPE = "agent_connect"

# internal/spool's on-disk layout, read and (for the replay) rewound from the
# test. `queue.jsonl` is every line appended since the last compaction;
# `queue.head` records how many leading lines have been delivered *and
# committed*.
_SPOOL_QUEUE_PATH = "/var/lib/cb-agent/queue.jsonl"
_SPOOL_HEAD_PATH = "/var/lib/cb-agent/queue.head"

# The grant edit step 6 makes, and the only capability write in this test.
# See the test's docstring, "Why the replay needs a slower sweep".
_REPLAY_DISCOVERY_CONFIG = {
    "max_concurrent_hosts": 1,
    "host_timeout_ms": 3000,
    "job_timeout_seconds": 1800,
}


def _session_cookie() -> str:
    """A `cb_session` value for the WebSocket handshake.

    `/api/v1/discovery/stream` authenticates from the handshake cookie alone
    (api/ws_discovery.py's `token_from_websocket_scope`) — unlike
    `/api/v1/agents/stream`, which reads a bearer token as its first message,
    which is why `_AgentStreamListener` cannot be reused here. The suite's own
    client deliberately drops its cookie jar after bootstrap (see
    `_bootstrap_admin`) so that its REST traffic stays purely bearer
    authenticated and never trips CSRFMiddleware, so this logs in once more on
    a throwaway client purely to read the cookie back.
    """
    with _new_client() as cookie_client:
        resp = cookie_client.post(
            "/api/v1/auth/login",
            json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
        )
        resp.raise_for_status()
        cookie = cookie_client.cookies.get("cb_session")
    assert cookie, "login did not set a cb_session cookie"
    return cookie


class _DiscoveryStreamListener:
    """Records `WS /api/v1/discovery/stream` in arrival order, from a
    background thread.

    This is the stream the Discovery page itself subscribes to
    (`src/api/discovery.js`), and it is what makes "incremental progress" a
    property this test can *observe* rather than infer. Polling a job's result
    list cannot do that job honestly: an automatic /24 sweep at the default
    concurrency finishes in seconds, so a poller that happened to miss the
    window would report a job that went straight from queued to completed —
    indistinguishable from a backend that buffered every finding and wrote them
    all at the end, which is exactly the design the streaming ingest path
    exists to rule out. Order between two events on one channel is the
    assertion; wall-clock timing is not.

    `events` is append-only and read under the same lock it is written under.
    """

    def __init__(self, cookie: str):
        from websockets.sync.client import connect

        # Same two websockets deprecations as _AgentStreamListener — see the note
        # there for why the connection is held open through an ExitStack.
        self._stack = contextlib.ExitStack()
        self._ws = self._stack.enter_context(
            connect(
                f"{WS_BASE_URL}/api/v1/discovery/stream",
                ssl=_tls_context(),
                open_timeout=15,
                additional_headers={"Cookie": f"cb_session={cookie}"},
            )
        )
        ack = json.loads(self._ws.recv(timeout=10))
        assert ack.get("status") == "connected", f"discovery stream auth failed: {ack}"

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
            # `ping` is the server's own 30s keep-alive and says nothing about
            # a scan; everything else on this channel is a discovery event.
            if isinstance(msg, dict) and msg.get("type") not in (None, "ping", "pong"):
                with self._lock:
                    self.events.append(msg)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        try:
            # Unwinds the ExitStack the constructor opened, which is what closes
            # the socket; `self._ws.close()` would leave the stack un-exited.
            self._stack.close()
        except Exception:
            pass


def _discovery_profiles(client: httpx.Client, agent_id: int) -> list[dict]:
    """Every discovery profile pointed at this agent, automatic or not.

    Read from `GET /discovery/profiles` — the list the Discovery page renders —
    rather than from an agent-scoped route, because plan §8 step 3's claim is
    about what an operator finds in the *ordinary* profile list after doing
    nothing but approving an agent.
    """
    resp = client.get("/api/v1/discovery/profiles")
    resp.raise_for_status()
    return [p for p in resp.json() if p["scan_agent_id"] == agent_id]


def _discovery_view(client: httpx.Client, agent_id: int) -> dict:
    """`GET /agents/{id}/discovery` — Agent Detail's whole "Discovery scope" section.

    One request answers what a vantage point is discovering and, if nothing,
    why: the derived scope with each entry's provenance, the grant's limits,
    collector readiness, all three pause scopes, the active and recent jobs, and
    the profiles pointed at this agent. Every Slice 4 test asks "what does the
    SERVER believe about this agent" here and nowhere else, so two of them
    disagreeing can never be an artefact of two different endpoints.
    """
    resp = client.get(f"/api/v1/agents/{agent_id}/discovery")
    resp.raise_for_status()
    return resp.json()


def _automatic_scope(client: httpx.Client, agent_id: int) -> set[str]:
    """The CIDRs the server derived from this agent's own interface facts alone.

    `provenance == "automatic"` drops an administrator's routed overrides and
    `effective` drops anything policy then refused, so what is left is exactly
    "the subnets this agent is plugged into that the server will scan" — the set
    plan §8 step 3 requires to appear with no CIDR typed anywhere.
    """
    return {
        entry["cidr"]
        for entry in _discovery_view(client, agent_id)["scope"]
        if entry["provenance"] == "automatic" and entry["effective"]
    }


def _scan_jobs(client: httpx.Client, *, profile_id: int | None = None) -> list[dict]:
    resp = client.get("/api/v1/discovery/jobs")
    resp.raise_for_status()
    jobs = resp.json()
    if profile_id is not None:
        jobs = [j for j in jobs if j["profile_id"] == profile_id]
    return jobs


def _scan_job(client: httpx.Client, job_id: int) -> dict:
    resp = client.get(f"/api/v1/discovery/jobs/{job_id}")
    resp.raise_for_status()
    return resp.json()


def _job_results(client: httpx.Client, job_id: int) -> list[dict]:
    """One job's `ScanResult` rows, oldest first.

    Re-sorted by id here because the route orders by `created_at desc` and
    several agent findings can share a second, which would make "the same rows
    came back" compare two arbitrary permutations of one list.
    """
    resp = client.get(f"/api/v1/discovery/jobs/{job_id}/results", params={"limit": 500})
    resp.raise_for_status()
    return sorted(resp.json(), key=lambda r: r["id"])


def _review_queue(client: httpx.Client) -> list[dict]:
    """The ordinary review queue, exactly as the UI asks for it.

    `GET /discovery/results?status=pending` with no agent parameter, no job
    parameter and no execution-location filter — `src/api/discovery.js`'s
    `listPendingResults`. Plan §8 step 5 is satisfied only if an agent finding
    is here, and finding it through an agent-specific route instead would prove
    the opposite of what the step claims.
    """
    resp = client.get("/api/v1/discovery/results", params={"status": "pending"})
    resp.raise_for_status()
    return resp.json()


def _hardware_with_ip(client: httpx.Client, ip: str) -> list[dict]:
    resp = client.get("/api/v1/hardware")
    resp.raise_for_status()
    return [h for h in resp.json() if h.get("ip_address") == ip]


def _agent_events(client: httpx.Client, agent_id: int) -> list[dict]:
    resp = client.get(f"/api/v1/agents/{agent_id}/events")
    resp.raise_for_status()
    return resp.json()


def _put_local_discovery(
    client: httpx.Client, headers: dict, agent_id: int, config: dict
) -> dict:
    """PUT one `local_discovery` grant config. `set_capability_grants` merges
    against the stored config, so a partial `config` keeps every setting it
    omits — including the scope lists, which is what keeps this edit out of
    D-16's scope-version path (see `put_capabilities`: "an unrelated setting
    change (a smaller max_concurrent_hosts, say) retires nothing")."""
    resp = client.put(
        f"/api/v1/agents/{agent_id}/capabilities",
        json={"capabilities": {"local_discovery": {"enabled": True, "config": config}}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _spool_frames(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> list[dict]:
    """Every decodable frame currently on disk in the agent's spool.

    Read straight out of `queue.jsonl`, which is newline-delimited
    `frame.Frame` JSON (internal/spool's package doc) — plaintext, because the
    Noise session encrypts the wire and not the queue. Delivered frames stay in
    this file as a consumed prefix until compaction (512 entries), which is
    what makes the replay below possible at all.

    A torn final line is skipped exactly as `spool.load()` skips it: an unclean
    shutdown can leave one, and it is not a frame.
    """
    raw = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            service,
            "sh",
            "-c",
            f"cat {_SPOOL_QUEUE_PATH} 2>/dev/null || true",
        ],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    frames = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            frames.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return frames


def _spooled_findings(frames: list[dict], job_id: int) -> list[dict]:
    """The `discovery.finding` payloads in *frames* that belong to one job."""
    findings = []
    for frame in frames:
        if frame.get("type") != "discovery.finding":
            continue
        payload = frame.get("payload") or {}
        if payload.get("scan_job_id") == job_id:
            findings.append(payload)
    return findings


def _spool_head(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> int:
    """How many leading `queue.jsonl` lines the agent has delivered AND
    committed, from `queue.head`.

    A missing marker means zero — that is `spool.readHeadMarker`'s own reading
    of it, and it is the state a spool that has never drained is in.
    """
    raw = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            service,
            "sh",
            "-c",
            f"cat {_SPOOL_HEAD_PATH} 2>/dev/null || true",
        ],
        cwd=E2E_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return int(raw) if raw else 0


def _spool_fully_delivered(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> bool:
    """Every line on disk delivered *and* committed, and there is something
    on disk to have delivered.

    Read from the two spool files rather than from `status.json`'s
    `spool_depth` or the server's heartbeat-reported one, because both of
    those can read zero for an innocent reason — a spool that has never held
    anything reports zero too — and this has to distinguish "the backlog
    drained" from "there was never a backlog". `queue.head == len(queue.jsonl)`
    with a non-empty file says exactly the first.
    """
    frames = _spool_frames(env, service=service)
    return bool(frames) and _spool_head(env, service=service) == len(frames)


def _rewind_spool_head(env: dict | None = None, *, service: str = _AGENT_SERVICE) -> None:
    """Put the spool back into the one state that makes a delivered frame
    replay: everything on disk, nothing committed.

    This is not a synthetic state and it is not a second delivery path. It is
    exactly what internal/link's at-least-once contract already produces —
    `drainBurst` peeks, sends, and only *then* commits, so a process that dies
    between those two steps comes back with delivered frames still uncommitted
    and re-sends them (internal/spool's package doc: "A crash mid-burst
    therefore re-sends rather than loses"). Reproducing that window by racing a
    SIGKILL against a ~microsecond gap once per 100 ms tick is not something a
    test can do reliably, so the resulting *on-disk state* is written directly
    and the agent then does the entire replay itself: it reloads its own spool,
    re-encodes its own frames, sends them over a real Noise session, and the
    server ingests them through the ordinary `/link` path with nothing stubbed.
    Nothing here fabricates a frame, edits one, or speaks to the server.

    The marker is written before the process is killed, never after: a running
    agent rewrites it on every `Commit`, and SIGKILL (rather than a graceful
    `compose stop`) is what guarantees nothing overwrites the rewind on the way
    out.
    """
    subprocess.run(
        [*COMPOSE, "exec", "-T", service, "sh", "-c", f"printf '0\\n' > {_SPOOL_HEAD_PATH}"],
        cwd=E2E_DIR,
        env=env,
        check=True,
    )
    # Read back before the kill, because every assertion the replay rests on
    # assumes the process restarts with nothing committed — and a marker that
    # silently failed to move would leave the spool already drained, the
    # "everything is delivered" predicate true from the first poll, and the
    # whole replay a no-op that still passed.
    assert _spool_head(env, service=service) == 0, (
        "the spool head marker did not rewind; the agent would restart with its "
        "backlog already committed and nothing would be replayed"
    )
    subprocess.run([*COMPOSE, "kill", "-s", "SIGKILL", service], check=True, cwd=E2E_DIR, env=env)
    # `restart: on-failure` (docker-compose.yml) brings a SIGKILLed container
    # back on its own, exactly as the real systemd unit would; this is the
    # explicit, idempotent version of that so the test never depends on the
    # engine's timing.
    subprocess.run([*COMPOSE, "up", "-d", service], check=True, cwd=E2E_DIR, env=env)


def _assert_backend_cannot_reach(address: str, subnet: str) -> None:
    """The negative every assertion in this test is worth exactly as much as.

    Both transports, because a discovery finding names a host *and* its open
    TCP ports: a backend that could not ping the fixture but could connect to
    it would still be able to produce the same row.
    """
    for description, command in (
        ("ICMP", f"ping -c 2 -W 2 {address}"),
        ("TCP", f"nc -z -w 3 {address} {_PROBE_TARGET_HTTP_PORT}"),
    ):
        probe = _backend_sh(command)
        assert probe.returncode != 0, (
            f"the backend reached {address} on {subnet} over {description} — that subnet "
            "is not isolated from circuitbreaker, and no discovery result found there can "
            "be attributed to the agent rather than to the server: "
            f"{probe.stdout!r} {probe.stderr!r}"
        )


# `agent_discovery`'s two audit vocabularies for a finding the server refused.
# A *deduplicated* finding writes neither, which is what lets step 6 below tell
# "the idempotency key absorbed the replay" apart from "the dispatch had closed
# and every replayed frame was thrown away" — two outcomes that leave the
# `scan_results` table looking identical.
_FINDING_REJECTION_EVENTS = frozenset({"protocol_violation", "capability_violation"})


def _finding_rejections(client: httpx.Client, agent_id: int) -> list[int]:
    return sorted(
        e["id"] for e in _agent_events(client, agent_id)
        if e["event_type"] in _FINDING_REJECTION_EVENTS
    )


@pytest.mark.e2e
def test_agent_zero_configuration_discovery_import_and_replay():
    """Slice 4 §8 steps 1-7: the claim the whole slice exists to make.

    One install command, one ordinary approval with the server's own default
    grants, and **no CIDR typed anywhere** — then a host the backend cannot
    reach at all appears in the ordinary review queue, is imported as one
    Hardware row, and survives a replay of the agent's own findings without
    duplicating either.

    **The negative is the premise, and it is asserted first and again last.**
    `probe-target` sits on `probe-net`; `circuitbreaker` is deliberately not
    attached to it, and Docker's inter-bridge isolation drops forwarding between
    two bridge networks. `_backend_sh` is made to try ICMP *and* TCP against
    10.77.0.10 and to fail at both, behind positive controls that prove the two
    commands can succeed at all from inside that container — a loop of `assert
    returncode != 0` is satisfied just as well by a missing binary as by an
    absent route. Every "the agent discovered this" assertion below means
    nothing except while that loop keeps failing, so it runs before the agent is
    even eligible and once more after the import, over the topology as it
    finally stands.

    **Nothing in this test types a CIDR, creates a profile, or configures the
    agent.** The only writes it makes are: approve (with no `capabilities` body
    — `_enroll_agent` asserts the server applied its own defaults), accept one
    review-queue row, and — for step 6 alone, after every zero-configuration
    claim has already been proven — one ordinary capability edit and one "Run
    now" on a profile the *server* created. `agent.toml` carries a server URL,
    a static key and a TLS pin, and no scope, port, subnet or scanner setting
    exists anywhere in it.

    What each step pins:

    1. **The agent reports its directly connected subnets** (§8 step 3, first
       half). Both pinned /24s reach the server's derived scope with
       `provenance: automatic`, from the interface facts in `hello` alone.
       Asserted as an *equality*: a scope that also contained something never
       plugged in would mean the derivation is reading something other than the
       agent's own kernel.

    2. **The backend mints the system-managed profiles, D-12.** One enabled
       `managed_by="system"` profile per reported subnet — not "exactly one"
       overall, which cannot hold for a container on two networks (see D-12) —
       exactly one of them targeting the fixture subnet, each carrying the
       single `agent_connect` scan type and no `nmap_arguments`, and no
       user-created profile alongside them.

    3. **An initial scan starts by itself, and its findings stream.** The job is
       `triggered_by="bootstrap"`, `source_type="agent"`, and nobody asked for
       it. Progress is observed on `WS /api/v1/discovery/stream` — the stream
       the Discovery page itself subscribes to — because the point of
       incremental ingest is that an operator watches hosts *arrive*: the
       assertion is that a `result_added` naming the fixture is pushed **before**
       the terminal `job_update`, which a backend that buffered every finding
       and wrote them all at the end could not produce. Polling could not tell
       the two apart, since a /24 sweep at the default concurrency finishes in
       seconds and a poller that missed the window would see the same
       queued-then-completed job either way.

    4. **The fixture lands in the ordinary review queue.** Found through `GET
       /discovery/results?status=pending` with no agent parameter and no
       execution-location filter — plan §8's "no separate UI path" is a claim
       about *this* endpoint, so locating the row through an agent-scoped route
       would prove the opposite. Its open ports are 53 and 8080, both of which
       are in the grant's port list and neither of which anything but a connect
       scan from inside probe-net could have observed.

    5. **Importing it creates exactly one Hardware row**, through the same
       `POST /discovery/results/{id}/merge` the review queue posts, and the row
       leaves the queue.

    6. **Replaying the findings is free** — no duplicate `ScanResult`, no
       duplicate Hardware row. This is the claim `finding_id` exists for: it is
       a digest of `dispatch_id|kind|address` (not a fresh `collect.SampleID()`)
       precisely so that a batch re-sent after an outage collides with the rows
       it already wrote, on `uq_scan_results_job_finding`.

       *The replay is real.* The agent reloads its own spool, re-encodes its own
       frames, sends them over a real Noise session, and the server ingests them
       through the ordinary `/link` path — nothing is stubbed, no ingest
       function is called twice in-process, and no frame is fabricated or
       edited. What the test supplies is the *on-disk state* an unclean shutdown
       mid-burst leaves behind, because that window cannot be hit reliably any
       other way: `drainBurst` peeks, sends, and only then commits, so the gap
       in which a delivered frame is still uncommitted is microseconds wide once
       per 100 ms tick. `_rewind_spool_head` writes exactly that state — every
       line still on disk, nothing committed — and the agent does the rest.

       *Why the replay needs a slower sweep.* A replayed host finding is only
       *deduplicated* while its dispatch is still open; once the terminal
       summary has closed the job, the same frame is **refused** as
       `dispatch_closed` instead, which also leaves no duplicate row and would
       therefore let this step pass while proving nothing about the idempotency
       key. So the second scan is run with `max_concurrent_hosts: 1`, which
       stretches a 254-address sweep from seconds to minutes and makes the
       window between the fixture's finding and the terminal summary wide enough
       to drive a replay inside it deliberately rather than by winning a race.
       That is an ordinary central "scan depth" control (plan §6), it is applied
       only *after* every zero-configuration claim above has been proven, and it
       is provably not a scope change — `_scope_version` digests the scope's
       four dimensions and nothing else, so D-16's version check cannot be what
       admits or refuses these findings. The agent is killed before the sweep
       ends, so no summary is ever produced and the dispatch stays open on its
       own 1800 s lease.

       *How the test knows the replay actually happened.* "No new row" on its
       own is equally consistent with nothing having been sent, so four things
       are asserted together. The head marker is read back at zero *before* the
       process is killed, so the restart provably begins with nothing
       committed. The reconnecting agent's own `hello` reports a backlog to the
       server, which is the backend saying it came back carrying frames. The
       first N lines of `queue.jsonl` are then still byte-for-byte the batch
       that was already delivered once, and the marker again covers all of them
       — and `Commit` is only ever reached for frames `drainBurst` has written
       to the wire, so those exact frames went out a second time. Finally the
       job is still open, so a refusal was *possible*, and no
       `protocol_violation`/`capability_violation` was recorded, so none
       happened: what absorbed the redelivery was the idempotency key.

       These are not four spellings of one check. Measured against a build with
       the rewind removed, the `hello` backlog witness still passes — the
       restart gap spools a fresh telemetry frame or two — and it is the
       byte-for-byte comparison that fails, because a restart whose marker was
       never rewound compacts the delivered prefix away on load.

    7. **Plan §3's idempotency, incidentally but deliberately.** The agent
       connects three times over this test (start, post-outage, post-replay) and
       every `hello` re-runs the bootstrap pass. The profile set and the count
       of `triggered_by="bootstrap"` jobs are asserted unchanged at the end:
       "repeated hello/readiness frames must not create duplicate profiles or
       scans" is exactly the kind of claim that only an end-to-end run with real
       reconnections can falsify.

    Steps 8-11 of §8 (capability disable mid-scan, restart/address change,
    second agent, recurrence) are Task 33's; nothing here depends on them.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        _up_fixture_target(_PROBE_TARGET_SERVICE)

        # The pinned topology this test names literals from, read back live —
        # a subnet Docker declined would otherwise surface minutes later as an
        # inexplicable scope mismatch instead of as one line here.
        assert _network_subnet(_AGENT_NET) == _AGENT_NET_CIDR
        assert _network_subnet(_PROBE_NET) == _PROBE_NET_CIDR

        # Subscribed before the agent exists, so the automatic first scan — which
        # nobody triggers and which starts on its own jitter — cannot begin
        # before there is somebody watching it.
        events_stream = _DiscoveryStreamListener(_session_cookie())
        try:
            agent_id, stream = _enroll_agent(client, headers)
            try:
                subprocess.run([*COMPOSE, "up", "-d", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
                _wait_until(
                    lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                    timeout=30,
                )
                _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)

                # ---- The negative, with its positive controls ---------------
                container, server_net = _agent_network_name()
                agent_ip = _container_ipv4(container, server_net)
                reachable = _backend_sh(f"ping -c 2 -W 2 {agent_ip}")
                assert reachable.returncode == 0, (
                    "the backend cannot ICMP a host on a network it IS attached to, so the "
                    "isolation assertions below would hold even with no isolation at all: "
                    f"{reachable.stdout!r} {reachable.stderr!r}"
                )
                listening = _backend_sh(f"nc -z -w 3 127.0.0.1 {_BACKEND_HTTPS_PORT}")
                assert listening.returncode == 0, (
                    "`nc` cannot connect to the backend's own open port, so the TCP half of "
                    "the isolation check proves nothing: "
                    f"{listening.stdout!r} {listening.stderr!r}"
                )
                _assert_backend_cannot_reach(_PROBE_TARGET_IP, _PROBE_NET_CIDR)

                # ---- 1. The agent reports its directly connected subnets ----
                _wait_until(
                    lambda: {_AGENT_NET_CIDR, _PROBE_NET_CIDR}
                    <= _automatic_scope(client, agent_id),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                scope = _automatic_scope(client, agent_id)
                assert scope == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the agent's automatic scope is not exactly its two directly connected "
                    f"pinned subnets: {sorted(scope)}"
                )
                view = _discovery_view(client, agent_id)
                assert view["granted"] is True and view["eligible"] is True, view
                assert view["paused"] is False and view["globally_paused"] is False, view
                assert view["limits"]["scope_mode"] == "direct_private", view["limits"]

                # ---- 2. The system-managed profiles (D-12) ------------------
                _wait_until(
                    lambda: len(_discovery_profiles(client, agent_id)) >= 2,
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                profiles = _discovery_profiles(client, agent_id)
                assert {p["cidr"] for p in profiles} == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                    "the bootstrap did not create exactly one profile per directly connected "
                    f"subnet (D-12): {[(p['cidr'], p['managed_by']) for p in profiles]}"
                )
                assert all(p["managed_by"] == "system" for p in profiles), profiles
                assert all(p["enabled"] for p in profiles), profiles
                assert all(p["paused_at"] is None for p in profiles), profiles
                by_cidr = {p["cidr"]: p for p in profiles}
                probe_profile = by_cidr[_PROBE_NET_CIDR]
                assert probe_profile["scan_types"] == [_AGENT_SCAN_TYPE], probe_profile
                assert probe_profile["nmap_arguments"] is None, probe_profile
                assert probe_profile["schedule_cron"], (
                    "the automatic profile has no recurring cadence — plan §3 step 5 asks for "
                    "a six-hourly schedule with per-agent jitter"
                )

                # ---- 3. The initial scan, and progress that streams ---------
                initial_job = _wait_until_and_return(
                    lambda: next(iter(_scan_jobs(client, profile_id=probe_profile["id"])), None),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                job_id = initial_job["id"]
                assert initial_job["triggered_by"] == "bootstrap", initial_job
                assert initial_job["scan_agent_id"] == agent_id, initial_job
                assert initial_job["source_type"] == "agent", initial_job
                assert initial_job["target_cidr"] == _PROBE_NET_CIDR, initial_job

                _wait_until(
                    lambda: _scan_job(client, job_id)["status"] == "completed",
                    timeout=_INITIAL_SCAN_BUDGET_S,
                )
                completed = _scan_job(client, job_id)
                assert completed["error_reason"] is None, completed
                assert completed["hosts_found"] >= 1, completed

                pushed = events_stream.snapshot()
                streamed = [
                    e
                    for e in pushed
                    if e.get("type") == "result_added" and e.get("job_id") == job_id
                ]
                terminal = [
                    i
                    for i, e in enumerate(pushed)
                    if e.get("type") == "job_update"
                    and (e.get("job") or {}).get("id") == job_id
                    and (e.get("job") or {}).get("status") == "completed"
                ]
                assert streamed, (
                    "no result_added was pushed for the automatic scan — findings are not "
                    f"reaching the discovery stream at all. Saw: {[e.get('type') for e in pushed]}"
                )
                assert terminal, "no terminal job_update was pushed for the automatic scan"
                first_result = pushed.index(streamed[0])
                assert first_result < terminal[0], (
                    "every finding was pushed at or after the job's terminal event — the "
                    "operator never saw hosts arrive, which is the whole point of streaming "
                    "the findings rather than writing them in one batch at the end"
                )
                assert _PROBE_TARGET_IP in [
                    (e.get("result") or {}).get("ip_address") for e in streamed
                ], (
                    f"{_PROBE_TARGET_IP} was never pushed as an incremental result; only "
                    f"{[(e.get('result') or {}).get('ip_address') for e in streamed]}"
                )
                assert pushed[terminal[0]].get("pending_count", 0) >= 1, (
                    "the terminal event carried no pending review count, so the review badge "
                    "an operator watches never moved"
                )

                # ---- 4. The ordinary review queue ---------------------------
                queued = [r for r in _review_queue(client) if r["ip_address"] == _PROBE_TARGET_IP]
                assert len(queued) == 1, (
                    f"expected exactly one pending review row for {_PROBE_TARGET_IP}, got "
                    f"{queued}"
                )
                review_row = queued[0]
                assert review_row["scan_job_id"] == job_id, review_row
                assert review_row["merge_status"] == "pending", review_row
                assert review_row["state"] == "new", review_row
                ports = {p["port"] for p in json.loads(review_row["open_ports_json"] or "[]")}
                assert {53, _PROBE_TARGET_HTTP_PORT} <= ports, (
                    f"the finding for {_PROBE_TARGET_IP} reports open ports {sorted(ports)}; the "
                    "fixture answers TCP on 53 (dnsmasq) and 8080 (httpd) and both are in the "
                    "grant's port list, so a connect scan from inside probe-net must have seen "
                    "them"
                )
                assert review_row in _job_results(client, job_id), (
                    "the review queue and the job's own result list disagree about the row"
                )

                # ---- 5. Import: exactly one Hardware row --------------------
                assert _hardware_with_ip(client, _PROBE_TARGET_IP) == [], (
                    "a Hardware row for the fixture existed before it was imported — the scan "
                    "or the finalizer auto-merged it, which plan §5 forbids for an agent finding"
                )
                merged = client.post(
                    f"/api/v1/discovery/results/{review_row['id']}/merge",
                    json={"action": "accept", "entity_type": "hardware"},
                )
                assert merged.status_code == 200, merged.text
                hardware = _hardware_with_ip(client, _PROBE_TARGET_IP)
                assert len(hardware) == 1, (
                    f"import created {len(hardware)} Hardware rows: {hardware}"
                )
                hardware_id = hardware[0]["id"]
                assert merged.json().get("entity_id") == hardware_id, merged.json()
                assert not [
                    r for r in _review_queue(client) if r["id"] == review_row["id"]
                ], "the accepted row is still in the pending review queue"
                # Snapshotted *after* the import, not before: accepting a row
                # rewrites its own `merge_status`/`reviewed_*`/`matched_entity_*`
                # columns, and comparing against a pre-import copy would report
                # that ordinary review write as damage the replay did.
                imported_results = _job_results(client, job_id)

                # ---- 6. A real replay of the agent's own findings -----------
                # An ordinary scan-depth edit (plan §6) and an ordinary "Run
                # now" on the profile the *server* created. See the docstring:
                # this is not a scope change, so D-16's version check is not
                # what decides anything below.
                _put_local_discovery(client, headers, agent_id, _REPLAY_DISCOVERY_CONFIG)
                run = client.post(f"/api/v1/discovery/profiles/{probe_profile['id']}/run")
                assert run.status_code == 200, run.text
                replay_job_id = run.json()["id"]
                assert replay_job_id != job_id

                # Wait for the sweep to be demonstrably under way — a finding
                # already accepted live — before taking the server away, so the
                # outage lands mid-scan rather than before the request was even
                # delivered.
                _wait_until(
                    lambda: len(_job_results(client, replay_job_id)) >= 1,
                    timeout=_INITIAL_SCAN_BUDGET_S,
                    interval=0.3,
                )
                # The sweep runs one address at a time in ascending order, and
                # 10.77.0.1 (the bridge gateway) and the agent's own address both
                # answer well before 10.77.0.10 does, so the first accepted
                # finding is never the fixture's. Asserted rather than assumed:
                # if it ever were, the fixture's finding would go over the live
                # link and never enter the spool, and the wait inside the outage
                # below would spend its whole budget discovering that.
                assert not any(
                    r["ip_address"] == _PROBE_TARGET_IP
                    for r in _job_results(client, replay_job_id)
                ), (
                    f"{_PROBE_TARGET_IP} was the first host this sweep found, so its finding "
                    "went over the live link instead of through the spool — nothing earlier "
                    "in 10.77.0.0/24 answered, and this step needs a spooled finding for the "
                    "fixture specifically"
                )

                with _backend_outage(client):
                    # The server is gone, so every finding from here fails its
                    # live send and is durably enqueued instead (internal/link's
                    # dataFrameSender.sendLive). The fixture's own finding is
                    # the one this test needs on disk, so it waits for that
                    # address specifically rather than for any finding.
                    _wait_until(
                        lambda: any(
                            f["ip_address"] == _PROBE_TARGET_IP
                            for f in _spooled_findings(_spool_frames(), replay_job_id)
                        ),
                        timeout=_INITIAL_SCAN_BUDGET_S,
                        interval=2.0,
                    )

                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted",
                    timeout=_SPOOL_DRAIN_BUDGET_S,
                )
                _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)

                spooled = _spool_frames()
                fixture_findings = [
                    f
                    for f in _spooled_findings(spooled, replay_job_id)
                    if f["ip_address"] == _PROBE_TARGET_IP
                ]
                assert len(fixture_findings) == 1, fixture_findings
                assert fixture_findings[0]["finding_id"], fixture_findings[0]
                assert not any(
                    f.get("terminal") for f in _spooled_findings(spooled, replay_job_id)
                ), "the sweep already produced its terminal summary; see the docstring"
                assert _spool_head() == len(spooled), (
                    "the agent has not committed every line of its spool, so what follows "
                    "would be a first delivery of the remainder rather than a replay"
                )
                # The server's own view of the same thing, which it only ever
                # learns from the agent's 20s heartbeat (D-12) — so this lags
                # the on-disk truth above by up to one interval and is waited
                # for rather than asserted outright.
                _wait_until(
                    lambda: _agent_telemetry(client, agent_id)["spool"]["depth"] == 0,
                    timeout=60,
                )

                before = _scan_job(client, replay_job_id)
                assert before["status"] == "running", (
                    "the second scan closed before the replay could be driven, so a replayed "
                    "finding would be refused as `dispatch_closed` rather than deduplicated "
                    f"and the idempotency key would go untested: {before}"
                )
                delivered = _job_results(client, replay_job_id)
                replayed_addresses = sorted(
                    {f["ip_address"] for f in _spooled_findings(spooled, replay_job_id)}
                )
                assert _PROBE_TARGET_IP in replayed_addresses, replayed_addresses
                rows_per_address = {
                    address: [r["id"] for r in delivered if r["ip_address"] == address]
                    for address in replayed_addresses
                }
                assert all(len(ids) == 1 for ids in rows_per_address.values()), (
                    "a spooled finding did not land as exactly one row on its first delivery, "
                    f"so the replay below has nothing to be idempotent against: {rows_per_address}"
                )
                rejections_before = _finding_rejections(client, agent_id)

                # The replay itself: everything still on disk, nothing
                # committed — the state a crash between `send` and `Commit`
                # leaves — then the agent re-sends all of it by itself.
                _rewind_spool_head()
                # The server's own witness that the restarted agent came back
                # holding undelivered frames: `hello` carries the spool depth
                # (D-12), so this is the *backend* reporting a backlog rather
                # than the test reading the agent's disk. It says a backlog
                # existed, not which frames were in it — the identity of the
                # batch is what the on-disk comparison below establishes, and
                # both halves are needed: measured against a build with the
                # rewind removed, this wait still passes (the restart gap
                # spools a fresh telemetry frame or two) and the comparison
                # below is what fails.
                _wait_until(
                    lambda: _agent_telemetry(client, agent_id)["spool"]["depth"] > 0,
                    timeout=_SPOOL_DRAIN_BUDGET_S,
                    interval=0.5,
                )
                _wait_until(
                    lambda: _agent_status()["link_state"] == "accepted",
                    timeout=_SPOOL_DRAIN_BUDGET_S,
                )
                # The marker went back to zero and has now climbed to cover
                # every line on disk again. Paired with the byte-for-byte frame
                # comparison that follows, that is the replay: the identical N
                # frames were uncommitted at restart and are committed now, and
                # `Commit` is only ever reached for frames `drainBurst` has
                # already written to the wire.
                _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)
                replayed_on_disk = _spool_frames()
                assert replayed_on_disk[: len(spooled)] == spooled, (
                    "the spool no longer starts with the frames that were replayed — it was "
                    "compacted or rewritten, and this is not the same batch"
                )
                assert _spool_head() == len(replayed_on_disk), (
                    "the agent did not re-deliver and re-commit its whole spool"
                )

                after = _scan_job(client, replay_job_id)
                assert after["status"] == "running", (
                    "the dispatch closed during the replay — the replayed findings would have "
                    f"been refused as late rather than deduplicated: {after}"
                )
                assert _finding_rejections(client, agent_id) == rejections_before, (
                    "the server audited a rejection while the replay was draining, so the "
                    "frames were refused rather than absorbed by uq_scan_results_job_finding "
                    "— the idempotency claim this step exists for does not hold"
                )
                assert _job_results(client, replay_job_id) == delivered, (
                    "replaying the agent's own findings changed the job's result rows"
                )
                assert {
                    address: [
                        r["id"]
                        for r in _job_results(client, replay_job_id)
                        if r["ip_address"] == address
                    ]
                    for address in replayed_addresses
                } == rows_per_address, (
                    "a replayed finding wrote a second row for an address it had already "
                    "reported — uq_scan_results_job_finding did not absorb the redelivery, "
                    "which is the one thing the replay-stable finding_id digest exists for"
                )
                for counter in ("hosts_found", "hosts_new", "hosts_updated", "hosts_conflict"):
                    assert after[counter] == before[counter], (
                        f"the replay incremented {counter}: {before[counter]} -> {after[counter]}"
                    )
                assert _job_results(client, job_id) == imported_results, (
                    "the replay disturbed the first scan's results"
                )
                assert [h["id"] for h in _hardware_with_ip(client, _PROBE_TARGET_IP)] == [
                    hardware_id
                ], "the replay produced a second Hardware row for the fixture"

                # ---- 7. Three reconnections, no duplicated automatic work ---
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == {
                    p["id"] for p in profiles
                }, (
                    "a reconnect created or replaced a system profile; plan §3 requires "
                    "repeated hello/readiness frames to be a no-op"
                )
                bootstrap_jobs = [
                    j
                    for j in _scan_jobs(client, profile_id=probe_profile["id"])
                    if j["triggered_by"] == "bootstrap"
                ]
                assert len(bootstrap_jobs) == 1, (
                    "the agent reconnected three times in this test and a hello queued another "
                    f"automatic scan: {[j['id'] for j in bootstrap_jobs]}"
                )

                # ---- and the negative, over the topology as it stands -------
                _assert_backend_cannot_reach(_PROBE_TARGET_IP, _PROBE_NET_CIDR)
            finally:
                stream.close()
        finally:
            events_stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Slice 4 Task 33: cancellation, restart, a second agent, recurrence
# (plan §8 steps 8-11)
# ─────────────────────────────────────────────────────────────────────────
#
# Task 32 proves the slice's central claim on the happy path. These two tests
# attack the four ways that claim could be true by accident:
#
#   * work that keeps producing accepted results after it was cancelled,
#   * an agent that silently needs re-enrolling or re-configuring when either
#     end restarts or its address moves,
#   * findings attributed to whichever agent happened to report them last,
#   * a recurring cadence that cannot tell a device it has already seen from a
#     new one, or that lets an untrusted reporter rename inventory.
#
# As everywhere else in this file the budgets below are `_wait_until` ceilings,
# not expectations: a scenario that gets there sooner pays nothing.

# The scan-depth edit step 8 runs its doomed sweep under, and the reason it is
# this extreme is arithmetic rather than taste. Two things have to be true at
# once: the scan must still be running minutes after it starts (so "mid-scan"
# is not a race), and the agent must still be FINDING hosts after internal/
# link's 60s steady-state read deadline has taken the partitioned link down (so
# its late findings reach the server through the spool rather than vanishing
# into the black hole — see `_cut_agent_network`).
#
# `Liveness.probeHost` gives each address one shared wall-clock budget and
# `session.Ping` waits the whole of it for a reply, so an address nobody
# answers on costs a full `host_timeout_ms`. At the grant's 10 000 ms maximum
# and one host at a time, a 10.77.0.0/24 sweep answers for 10.77.0.1 and the
# agent's own address within a second and then spends ten seconds per dead
# address: 10.77.0.10 is not reached for ~70s and 10.77.0.20 not for ~160s,
# both comfortably past the deadline. `job_timeout_seconds` is the grant's
# maximum for the same reason — the dispatch must not expire on its own before
# the test has finished with it.
_CANCEL_DISCOVERY_CONFIG = {
    "max_concurrent_hosts": 1,
    "host_timeout_ms": 10_000,
    "job_timeout_seconds": 1800,
}

# From severing the link to a late finding sitting on the agent's disk: the 60s
# read deadline, then the sweep's ten-seconds-per-dead-address march to the next
# host that answers. Generous against the ~70s and ~160s computed above because
# both depend on how many addresses precede the fixtures, which is a property of
# Docker's IPAM rather than of anything under test.
_LATE_FINDING_BUDGET_S = 300

# Reconnect after a partition, and the restart of both ends. Dominated by
# internal/link's 1s-doubling backoff and by the backend's own start-up, neither
# of which is under test here.
_RECONNECT_BUDGET_S = 300

# One recurring sweep of an already-bootstrapped /24 at the grant's default
# depth (64 concurrent, 1500 ms), from "run now" to a terminal job status.
_RECURRING_SCAN_BUDGET_S = _INITIAL_SCAN_BUDGET_S

# Where cb-agent is moved to on agent-net. The subnet is deliberately unchanged:
# plan §8 step 9's profile-duplication risk is precisely an agent whose ADDRESS
# moves while the network it is directly connected to does not, because D-7's
# partial unique index is keyed on `(scan_agent_id, normalized_cidr)` and a
# bootstrap that keyed on anything address-shaped would mint a second profile
# for the same subnet here and nowhere else.
_AGENT_NET_MOVED_IP = "10.88.0.77"

# The name an operator gives the imported fixture, so that the hostname the
# agent keeps reporting (Docker's embedded-DNS PTR record for the container)
# stops agreeing with it. Plan §4 lists hostname among the agent's untrusted
# observations, so this disagreement must be a review and never a rename.
_OPERATOR_HARDWARE_NAME = "e2e-operator-named-fixture"

# The embedded cluster inside the mono container. Fixed by entrypoint-mono.sh;
# the password is the compose environment's own `CB_DB_PASSWORD`.
_BACKEND_DB_ROLE = "breaker"
_BACKEND_DB_NAME = "circuitbreaker"


def _backend_sql(query: str) -> list[list[str]]:
    """One read-only SQL query against the backend's own embedded Postgres.

    Reserved for the columns the product deliberately keeps off the wire, and in
    this file that means exactly one: `scan_results.discovery_agent_id`. It is
    the provenance column plan §2 adds and the column plan §8 step 10 is
    entirely about, and `ScanResultOut` omits it because nothing renders it — so
    "no finding was attributed to the wrong agent" is not a question any REST
    response can answer.

    Asking the job's `scan_agent_id` instead would answer a *different*
    question. The job's execution location and the row's reporter are written by
    two different code paths — `discovery_service.create_scan_job` and
    `agent_discovery._record_host_finding` — and a divergence between those two
    is precisely the shape cross-attribution would take. Reading only the job
    would make that divergence invisible, which is why both are read below and
    compared.

    Credentials come from the container's own environment rather than from this
    file, and `ON_ERROR_STOP` plus the returncode assertion mean a wrong role,
    a renamed column or a typo'd query fails here and says so, instead of
    returning an empty result set that several assertions later read as "no
    cross-attribution happened".
    """
    proc = _backend_sh(
        'PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 5432 '
        f"-U {_BACKEND_DB_ROLE} -d {_BACKEND_DB_NAME} "
        f"-v ON_ERROR_STOP=1 -At -F'|' -c {shlex.quote(query)}"
    )
    assert proc.returncode == 0, (
        f"reading the backend's own database failed for {query!r}: "
        f"{proc.stdout!r} {proc.stderr!r}"
    )
    return [line.split("|") for line in proc.stdout.splitlines() if line]


def _agent_host_samples(agent_id: int, start: datetime, end: datetime) -> list[tuple[str, float]]:
    """Every RAW agent host sample in a window, one tuple per sample.

    A direct DB read because no endpoint can answer this (F-6.1).
    `GET /agents/{id}/telemetry` serializes exactly one row — the newest — and
    `/telemetry/history` never materializes raw samples at all; it aggregates
    entirely in SQL over an epoch-aligned grid. `sample_id` is simply not on
    the wire for anything but `latest`, so bucket aggregates can only ever
    INFER uniqueness from counts. This asserts it.

    Checking `sample_id` alone is the point. The dedupe under test is
    `uq_agent_host_sample (agent_id, sample_id, collected_at)` — a redelivery
    that arrived with a REWRITTEN `collected_at` satisfies that constraint and
    is inserted as a second row under the same `sample_id`. That is exactly the
    failure the bucket check cannot see, and exactly the failure "collected_at
    is preserved rather than restamped to reconnect time" is about.

    `collected_at` comes back as epoch seconds rather than a rendered
    timestamp: psql -At prints a form whose offset and fractional digits vary,
    and this only ever needs ordering and window membership.
    """
    rows = _backend_sql(
        "SELECT sample_id, EXTRACT(EPOCH FROM collected_at) FROM agent_host_samples "
        f"WHERE agent_id = {int(agent_id)} "
        f"AND collected_at >= '{start.isoformat()}' AND collected_at <= '{end.isoformat()}' "
        "ORDER BY collected_at"
    )
    return [(row[0], float(row[1])) for row in rows]


def _result_provenance() -> list[dict]:
    """Every `scan_result`, with its own reporter *and* its job's executor.

    Both, never one: see `_backend_sql`. `discovery_agent_id` is NULL for a
    server-executed result and is rendered as the empty string by `psql -At`,
    which is why it is normalised to `None` here rather than left as `""` — a
    falsy string would make "this row names no agent" and "this row names agent
    0" compare equal in exactly the assertion that must tell them apart.
    """
    rows = _backend_sql(
        "select r.id, r.ip_address, coalesce(r.discovery_agent_id::text, ''), "
        "r.scan_job_id, coalesce(j.scan_agent_id::text, '') "
        "from scan_results r join scan_jobs j on j.id = r.scan_job_id order by r.id"
    )
    return [
        {
            "id": int(row[0]),
            "ip_address": row[1],
            "discovery_agent_id": int(row[2]) if row[2] else None,
            "scan_job_id": int(row[3]),
            "job_scan_agent_id": int(row[4]) if row[4] else None,
        }
        for row in rows
    ]


def _job_dispatch_state(job_id: int) -> tuple[str, str]:
    """One job's `(status, dispatch_status)`, the second of which is not on the wire.

    `dispatch_status` is what makes a late finding refusable at all — Task 21's
    `finalize_agent_job` and Task 22's `_close_jobs` both move it to a closed
    value in the same statement that closes the job, and `agent_discovery`'s
    ingest reads it — but `ScanJobOut` carries only `status`. A test that
    asserted the job was `cancelled` and stopped there would not have checked
    the column the refusal is actually made of.
    """
    rows = _backend_sql(
        "select status, coalesce(dispatch_status, '') from scan_jobs "
        f"where id = {int(job_id)}"
    )
    assert len(rows) == 1, f"scan job {job_id} is not in the database: {rows}"
    return rows[0][0], rows[0][1]


def _set_local_discovery_enabled(
    client: httpx.Client, headers: dict, agent_id: int, enabled: bool
) -> dict:
    """Turn `local_discovery` on or off, exactly as the Agent Detail toggle does.

    A bare boolean rather than an `{enabled, config}` object on purpose: that is
    what `CapabilityValue` accepts from the UI switch, and `set_capability_grants`
    keeps the stored config either way — so re-enabling later restores the same
    grant rather than resetting the scan depth an operator chose.
    """
    resp = client.put(
        f"/api/v1/agents/{agent_id}/capabilities",
        json={"capabilities": {"local_discovery": enabled}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capabilities"]["local_discovery"]["enabled"] is enabled, body["capabilities"]
    return body


def _agent_scan_jobs(client: httpx.Client, agent_id: int) -> list[dict]:
    """Every scan job whose execution location is this agent."""
    return [job for job in _scan_jobs(client) if job["scan_agent_id"] == agent_id]


# `agent_discovery._OPEN_JOB_STATUSES`: the two statuses a dispatch can still
# be cancelled, expired or answered from.
_OPEN_JOB_STATES = frozenset({"queued", "running"})


def _unfinished_agent_jobs(client: httpx.Client, agent_id: int) -> list[dict]:
    """This agent's jobs that are still queued or running.

    Used to reach quiescence before a test changes the grant underneath a scan:
    the bootstrap queues one initial scan per subnet (D-12), so an edit made
    while those are in flight would be cancelling or re-depthing work the test
    has said nothing about.
    """
    return [job for job in _agent_scan_jobs(client, agent_id) if job["status"] in _OPEN_JOB_STATES]


def _capability_violations(client: httpx.Client, agent_id: int, frame_type: str) -> list[int]:
    """The ids of this agent's `capability_violation` events for one frame type.

    `agent_link.dispatch_frame` writes exactly one of these per frame it drops
    for a withdrawn grant, with the frame's type in `detail`. Ids rather than a
    count so a "did any arrive while X was happening" comparison is a set
    difference and cannot be satisfied by an unrelated event of the same type
    arriving at the same moment.
    """
    return sorted(
        event["id"]
        for event in _agent_events(client, agent_id)
        if event["event_type"] == "capability_violation"
        and (event.get("detail") or {}).get("frame_type") == frame_type
    )


def _run_profile_now(client: httpx.Client, profile_id: int) -> dict:
    """"Run now" on a profile, waiting out the scan endpoint's own rate limit.

    `POST /discovery/profiles/{id}/run` is `@limiter.limit(get_limit("scan"))`,
    which is one per minute on the default profile. That is a property of the
    product an operator also lives with; a test that ran two recurring sweeps in
    quick succession and read the resulting 429 as a failure would be reporting
    the rate limiter as a discovery defect.

    This is the same job-creation path the six-hourly cron takes —
    `discovery_scheduler._run_profile_job_async` and this endpoint both call
    `create_scan_job` with the profile's CIDR, scan types and `scan_agent_id`,
    and differ only in `triggered_by`. Waiting out a real six-hour cadence is
    not something an E2E test can do, so what the recurrence assertions exercise
    is that path, on the profile the server itself created.
    """
    deadline = time.monotonic() + 180
    while True:
        resp = client.post(f"/api/v1/discovery/profiles/{profile_id}/run")
        if resp.status_code != 429:
            break
        assert time.monotonic() < deadline, (
            f"profile {profile_id} stayed rate-limited for 180s: {resp.text}"
        )
        time.sleep(10)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _change_agent_address(
    new_ip: str, *, service: str = _AGENT_SERVICE, env: dict | None = None
) -> tuple[str, str]:
    """Move an agent to a different address on the SAME directly connected subnet.

    Returns `(old_ip, new_ip)`. This is plan §8 step 9's "change the agent's
    address" in the form that can actually break something: the subnet the agent
    reports in every `hello` is unchanged, so the server's derived scope and the
    key of D-7's partial unique index are unchanged too, and the only thing that
    moved is the host part. An implementation that keyed a system profile, a
    dispatch lease or an identity on anything address-shaped produces a second
    profile for 10.88.0.0/24 here and nowhere else in this suite.

    `docker network disconnect` + `connect --ip` rather than a recreate: the
    container has to survive, because its state volume carries the enrollment
    whose survival is half of what the step is claiming.
    """
    container, network = _agent_network_name(env, service=service)
    old_ip = _container_ipv4(container, network)
    assert old_ip != new_ip, (
        f"{service} is already at {new_ip}; this helper would change nothing and the "
        "address-change half of plan §8 step 9 would go untested"
    )
    subprocess.run(["docker", "network", "disconnect", network, container], check=True)
    subprocess.run(["docker", "network", "connect", "--ip", new_ip, network, container], check=True)
    moved = _container_ipv4(container, network)
    assert moved == new_ip, f"{service} is at {moved} on {network}, not the requested {new_ip}"
    return old_ip, new_ip


def _hardware_row(client: httpx.Client, hardware_id: int) -> dict:
    resp = client.get(f"/api/v1/hardware/{hardware_id}")
    resp.raise_for_status()
    return resp.json()


def _rename_hardware(client: httpx.Client, hardware_id: int, name: str) -> dict:
    """The ordinary inventory rename — `PATCH /hardware/{id}` with a new name.

    An operator naming a device they just imported is the most ordinary write in
    the product, and it is what makes the agent's own reported hostname start
    disagreeing with the inventory. Nothing else about the row is touched, so
    the MAC and IP the matcher keys on are exactly what they were.
    """
    resp = client.patch(f"/api/v1/hardware/{hardware_id}", json={"name": name})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == name, body
    return body


def _discovery_status(client: httpx.Client) -> dict:
    resp = client.get("/api/v1/discovery/status")
    resp.raise_for_status()
    return resp.json()


def _system_profile_for(client: httpx.Client, agent_id: int, cidr: str) -> dict:
    """The one enabled system-managed profile for `(agent, cidr)`, asserting it is one.

    D-12's assertion in reusable form: the bootstrap mints one automatic profile
    per directly connected subnet, and "one" is the part that matters — a second
    row for the same subnet is what a duplicated upsert looks like, and it would
    otherwise show up only as two scans of the same /24 several minutes later.
    """
    matches = [
        profile
        for profile in _discovery_profiles(client, agent_id)
        if profile["cidr"] == cidr and profile["managed_by"] == "system"
    ]
    assert len(matches) == 1, (
        f"agent {agent_id} has {len(matches)} system-managed profiles for {cidr}, expected "
        f"exactly one (D-7's partial unique index keys them on this pair): {matches}"
    )
    return matches[0]


@pytest.mark.e2e
def test_agent_discovery_capability_disable_cancels_and_late_findings_die():
    """Slice 4 §8 step 8: the server enforces the cancellation; the agent's
    cooperation is not part of the mechanism.

    Disabling `local_discovery` mid-scan has to do two things — cancel the work,
    and refuse anything that arrives for it afterwards — and the second is the
    one that is hard to test honestly. `discovery.cancel` is best-effort by
    design (plan §4), so on the ordinary path the agent receives it, stops, and
    sends nothing more; the database then looks exactly the way it would if the
    backend were enforcing nothing at all. **A passing test on that path proves
    only that the agent is well behaved.**

    So this test takes the cancel away. The sweep is put under
    `_CANCEL_DISCOVERY_CONFIG` so it is still running minutes later, the agent's
    route to the server is severed with `_cut_agent_network` (a black hole — no
    FIN, no RST, nothing the agent can learn from a write), and the capability is
    turned off *while it is deaf*. The `discovery.cancel` the backend publishes
    is written into the void. The agent's own `status.json` is read inside the
    partition to prove it: it still holds `local_discovery: true`, so nothing
    that follows can be the agent obeying an instruction.

    It then goes on doing exactly what it was last told to do. Ten seconds per
    unanswered address (see `_CANCEL_DISCOVERY_CONFIG`) means it does not reach
    10.77.0.10 until well after internal/link's 60s read deadline has taken the
    link down, so those findings are no longer written into the void — they are
    durably spooled, and this test waits for one to appear on disk. That is the
    evidence the ordinary path cannot produce: **findings for a dispatch the
    server closed, produced by an agent that never learned it was closed, and
    physically present.**

    Restoring the route then delivers them over a real Noise session through the
    ordinary `/link` path, and the four things asserted afterwards are what
    server-side enforcement means:

    * the job is `cancelled` with `error_reason="capability_disabled"`, and its
      `dispatch_status` — the column the refusal is actually made of, and one
      `ScanJobOut` does not carry — is closed with it;
    * the job's result rows are byte-identical to what they were at the moment
      of the cut, so not one late finding became a row;
    * every address the agent reported late is absent from that job entirely;
    * a `capability_violation` was audited for each late frame, so the frames
      were *refused* rather than silently lost — which is the distinction
      between the backend enforcing the grant and the frames never having
      arrived, two outcomes with an identical `scan_results` table.

    Only then does the agent learn: reconnecting delivers `capabilities.set`,
    and `status.json` flips to `local_discovery: false`. The order is the point —
    the rejection happened first and did not depend on it.

    And underneath all of it, the premise this file's every discovery claim
    rests on: the backend is made to fail at reaching both fixtures over ICMP
    and TCP, behind positive controls, before the agent is eligible and again at
    the end.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        # Both fixtures up front, and both before the agent exists: the sweep
        # under test needs more than one address that answers *after* the link
        # goes down, and 10.77.0.20 sits nine dead addresses past 10.77.0.10, so
        # it is the one with real margin against the 60s read deadline.
        _up_fixture_target(_PROBE_TARGET_SERVICE)
        _up_fixture_target(_PROBE_TARGET_NEW_SERVICE)
        assert _network_subnet(_AGENT_NET) == _AGENT_NET_CIDR
        assert _network_subnet(_PROBE_NET) == _PROBE_NET_CIDR

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )
            _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)

            # ---- the negative, with its positive controls -------------------
            container, server_net = _agent_network_name()
            agent_ip = _container_ipv4(container, server_net)
            reachable = _backend_sh(f"ping -c 2 -W 2 {agent_ip}")
            assert reachable.returncode == 0, (
                "the backend cannot ICMP a host on a network it IS attached to, so the "
                "isolation assertions below would hold even with no isolation at all: "
                f"{reachable.stdout!r} {reachable.stderr!r}"
            )
            listening = _backend_sh(f"nc -z -w 3 127.0.0.1 {_BACKEND_HTTPS_PORT}")
            assert listening.returncode == 0, (
                "`nc` cannot connect to the backend's own open port, so the TCP half of "
                f"the isolation check proves nothing: {listening.stdout!r} {listening.stderr!r}"
            )
            for address in (_PROBE_TARGET_IP, _PROBE_TARGET_NEW_IP):
                _assert_backend_cannot_reach(address, _PROBE_NET_CIDR)

            # ---- zero-configuration bootstrap, as Task 32 establishes it ----
            _wait_until(
                lambda: {_AGENT_NET_CIDR, _PROBE_NET_CIDR} <= _automatic_scope(client, agent_id),
                timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
            )
            _wait_until(
                lambda: len(_discovery_profiles(client, agent_id)) >= 2,
                timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
            )
            probe_profile = _system_profile_for(client, agent_id, _PROBE_NET_CIDR)

            # Quiescence before the grant edit: the bootstrap queues one initial
            # scan per subnet, and re-depthing or cancelling those would be
            # doing it to work this test has said nothing about.
            _wait_until(
                lambda: _agent_scan_jobs(client, agent_id)
                and not _unfinished_agent_jobs(client, agent_id),
                timeout=_INITIAL_SCAN_BUDGET_S,
            )

            # ---- a sweep slow enough to still be running in five minutes ----
            _put_local_discovery(client, headers, agent_id, _CANCEL_DISCOVERY_CONFIG)
            job_id = _run_profile_now(client, probe_profile["id"])["id"]
            _wait_until(
                lambda: _scan_job(client, job_id)["status"] == "running"
                and len(_job_results(client, job_id)) >= 1,
                timeout=_INITIAL_SCAN_BUDGET_S,
                interval=0.5,
            )
            assert _agent_status()["grants"]["local_discovery"] is True, (
                "the agent does not believe it holds local_discovery before the grant is "
                "even withdrawn, so the status.json witness below would say nothing"
            )
            violations_before = _capability_violations(client, agent_id, "discovery.finding")

            with _cut_agent_network():
                # The agent is deaf from here. Everything the backend does next
                # it does alone.
                _set_local_discovery_enabled(client, headers, agent_id, False)

                cancelled = _scan_job(client, job_id)
                assert cancelled["status"] == "cancelled", (
                    "PROPERTY 1 (cancellation): disabling local_discovery left the running "
                    f"dispatch open — D-14 requires it closed in the same transaction: {cancelled}"
                )
                assert cancelled["error_reason"] == "capability_disabled", (
                    "PROPERTY 1 (cancellation): the job was closed for the wrong reason, so an "
                    f"operator reading the history cannot tell why it stopped: {cancelled}"
                )
                status, dispatch_status = _job_dispatch_state(job_id)
                assert (status, dispatch_status) == ("cancelled", "cancelled"), (
                    "PROPERTY 1 (cancellation): the job's `dispatch_status` did not close with "
                    "it, and that column is what `agent_discovery` reads to refuse a late "
                    f"finding: {(status, dispatch_status)}"
                )

                # The cancel could not have been delivered — and this is what
                # says so, rather than an inference from the topology.
                assert _agent_status()["grants"]["local_discovery"] is True, (
                    "the agent already knows its grant was withdrawn while its only route to "
                    "the server is severed, so this test is not proving server-side "
                    "enforcement — it is watching a cooperative agent stop"
                )

                # Nothing else can reach the server now, so this is the last
                # word on what the job accepted while it was authorised.
                results_at_cut = _job_results(client, job_id)
                addresses_at_cut = {row["ip_address"] for row in results_at_cut}

                # ...and the agent, knowing nothing, keeps going. Ten seconds
                # per dead address is what puts the next responsive host past
                # the 60s read deadline, so what lands here is durably spooled
                # rather than written into the black hole.
                def _late_host_findings() -> list[dict]:
                    return [
                        finding
                        for finding in _spooled_findings(_spool_frames(), job_id)
                        if finding.get("kind") == "host"
                        and finding.get("ip_address") not in addresses_at_cut
                    ]

                _wait_until(
                    lambda: _late_host_findings(),
                    timeout=_LATE_FINDING_BUDGET_S,
                    interval=2.0,
                )
                late_findings = _late_host_findings()
                late_addresses = sorted({f["ip_address"] for f in late_findings})
                assert _agent_status()["grants"]["local_discovery"] is True, (
                    "the agent learned about the withdrawal part-way through the partition, so "
                    "the findings it spooled are not unambiguously post-cancellation work"
                )

            # ---- the link comes back and the agent delivers all of it -------
            _wait_until(
                lambda: _agent_status()["link_state"] == "accepted", timeout=_RECONNECT_BUDGET_S
            )
            _wait_until(_spool_fully_delivered, timeout=_SPOOL_DRAIN_BUDGET_S)

            status, dispatch_status = _job_dispatch_state(job_id)
            assert (status, dispatch_status) == ("cancelled", "cancelled"), (
                "PROPERTY 1 (cancellation): delivering the spooled findings reopened the job — "
                f"a closed dispatch must stay closed: {(status, dispatch_status)}"
            )

            # The refusals first, and waited for rather than read once: the
            # agent commits a spooled frame as soon as it has written it to the
            # wire, so the disk can be drained a moment before the server has
            # finished refusing what came off it. Reading the result rows before
            # that would be asking whether a frame the backend has not looked at
            # yet was accepted.
            def _new_violations() -> list[int]:
                return sorted(
                    set(_capability_violations(client, agent_id, "discovery.finding"))
                    - set(violations_before)
                )

            _wait_until(
                lambda: len(_new_violations()) >= len(late_findings), timeout=_RECONNECT_BUDGET_S
            )
            assert len(_new_violations()) >= len(late_findings), (
                "PROPERTY 3 (server-side enforcement): the backend audited "
                f"{len(_new_violations())} refusals for the {len(late_findings)} late "
                "discovery.finding frames the agent delivered. Without one refusal per frame, "
                "'no new rows' is equally consistent with the frames never having arrived — "
                "and the two leave an identical scan_results table"
            )

            delivered = _job_results(client, job_id)
            assert delivered == results_at_cut, (
                "PROPERTY 2 (late findings rejected): the cancelled job's result rows changed "
                "when the agent delivered its backlog. Every one of those frames was produced "
                f"after the dispatch was closed. Before: {[r['id'] for r in results_at_cut]}; "
                f"after: {[r['id'] for r in delivered]}"
            )
            assert not [row for row in delivered if row["ip_address"] in late_addresses], (
                "PROPERTY 2 (late findings rejected): an address the agent reported only AFTER "
                f"the cancellation ({late_addresses}) has a result row on the cancelled job — "
                "the backend accepted work from a dispatch it had already closed"
            )

            # Only now, and only because it reconnected, does the agent find out.
            _wait_until(
                lambda: _agent_status()["grants"]["local_discovery"] is False,
                timeout=_RECONNECT_BUDGET_S,
            )
            assert _discovery_view(client, agent_id)["granted"] is False, (
                "PROPERTY 4 (the grant is really off): the server still reports "
                "local_discovery as granted after the capability was disabled"
            )

            # ---- and the negative, over the topology as it finally stands ---
            for address in (_PROBE_TARGET_IP, _PROBE_TARGET_NEW_IP):
                _assert_backend_cannot_reach(address, _PROBE_NET_CIDR)
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


def _agents(client: httpx.Client) -> list[dict]:
    resp = client.get("/api/v1/agents")
    resp.raise_for_status()
    return resp.json()


def _all_profiles(client: httpx.Client) -> list[dict]:
    """Every discovery profile in the installation, agent-owned or not."""
    resp = client.get("/api/v1/discovery/profiles")
    resp.raise_for_status()
    return resp.json()


def _enrolled_event_ids(client: httpx.Client, agent_id: int) -> list[int]:
    return sorted(
        event["id"]
        for event in _agent_events(client, agent_id)
        if event["event_type"] == "enrolled"
    )


def _in_any(address: str, cidrs) -> bool:
    parsed = ipaddress.ip_address(address)
    return any(parsed in ipaddress.ip_network(cidr) for cidr in cidrs)


@pytest.mark.e2e
def test_agent_discovery_reconnects_per_agent_and_requeues_only_changes():
    """Slice 4 §8 steps 9-11, in one stack lifetime.

    Three claims that only a real restart, a real second host and a real second
    agent can falsify, and each one has an obvious way of being true for the
    wrong reason:

    **Step 9 — both ends restart, and the agent's address moves.** "It
    reconnected" is easy; "it reconnected without re-enrolling and without
    duplicating anything" is the claim. The address change is what makes the
    duplication half real rather than decorative: `cb-agent` is moved to
    10.88.0.77 on the same `agent-net`, so the subnet it reports in every
    `hello` — and therefore the `normalized_cidr` half of D-7's partial unique
    index — is *unchanged* while its host address is not. A bootstrap that
    keyed a system profile on anything address-shaped mints a second profile
    for 10.88.0.0/24 exactly here. That the address really moved is asserted
    from the backend's own network namespace (it can ping the new address and
    cannot ping the old one), and that it moved *within* the subnet is asserted
    from the agent's own kernel routing table. No re-enrollment is four
    independent things: one `agents` row, the same id, the same `enrolled_at`
    and `device_pk`, the same on-disk `device.key` digest, and no second
    `enrolled` event. And "resumes recurring discovery" is the derived
    six-hourly cron still on the profile *and* still registered with
    APScheduler after the backend process that registered it was replaced —
    `_register_discovery_profile_crons` runs at start-up and a hold or a cron
    that only lived in the old process's scheduler state would be gone.

    **Step 11 — the recurring sweep tells three cases apart.** Run through
    `_run_profile_now`, which is the same `create_scan_job` path
    `discovery_scheduler._run_profile_job_async` takes when the cron fires
    (they differ only in `triggered_by`); a six-hour cadence is not something
    an E2E test can wait out, so the *path* is what is exercised, on the
    profile the server itself created.

      * a device the inventory already knows (10.77.0.10, imported after the
        first scan) comes back `matched`, pointing at the same Hardware row,
        and produces no second one;
      * a device that genuinely just appeared (10.77.0.20, started between the
        two sweeps) comes back `new` and lands in the ordinary review queue;
      * a device whose agent-reported hostname disagrees with the name an
        operator gave it comes back `conflict`, stays `pending`, names both
        halves of the disagreement in `conflicts_json` — and **the stored name
        is not touched**. Plan §4 lists hostname among the agent's untrusted
        observations, and the disagreement is manufactured the way it happens
        in real life: an operator renames the device in the inventory while the
        agent keeps reporting the PTR record it reads off the subnet.

      The half of step 11 that this deliberately does **not** assert is the
      `last_seen` auto-update. `_auto_merge_known_devices` — the function
      Task 25 hardened for exactly this case — is reachable only from
      `_scan_finalize`, and an agent job is closed by `finalize_agent_job`,
      which states in its own docstring that it never calls it at any setting
      (`tests/services/test_agent_discovery_ingest.py::
      test_finalization_never_auto_merges_however_the_setting_is_left` pins
      that). So on the agent path an unchanged known device is re-queued and
      its `last_seen` is not refreshed. Both are asserted below **as the
      current contract**, with messages that say so: if either ever changes,
      this test fails and points at the decision that changed rather than
      silently blessing it.

    **Step 10 — a second agent stays a second agent.** `cb-agent-2` has its own
    outbound network, its own fixture subnet, its own state volume and its own
    device key, and neither agent's kernel has a route to the other's fixture
    subnet — so "agent 2 found 10.78.0.10" is a statement about vantage points
    and not about which row the backend happened to write. Provenance is then
    checked on `scan_results.discovery_agent_id`, read straight out of the
    database because that column is deliberately not on the wire (see
    `_backend_sql`): every result row is compared against **both** its own
    reporter and its job's executor, and against the subnets that reporter can
    actually reach. A row naming an agent with no route to its address is
    cross-attribution however consistent the rest of the table looks.

    Throughout, the negative: the backend is made to fail at reaching all three
    fixtures over ICMP and TCP, behind positive controls, before anything is
    discovered and again at the end.
    """
    _up_server()
    try:
        client = _new_client()
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)
        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        material = _fetch_install_material(client, headers)
        _write_agent_toml(material["server_pk"], material["tls_pin"])
        # Only probe-target at stack start. probe-target-new is what makes
        # "genuinely new device" mean something, and it can only mean it if the
        # first sweep provably never saw it.
        _up_fixture_target(_PROBE_TARGET_SERVICE)
        assert _network_subnet(_AGENT_NET) == _AGENT_NET_CIDR
        assert _network_subnet(_PROBE_NET) == _PROBE_NET_CIDR

        agent_id, stream = _enroll_agent(client, headers)
        try:
            subprocess.run([*COMPOSE, "up", "-d", _AGENT_SERVICE], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=30,
            )
            _wait_until(lambda: _agent_status()["link_state"] == "accepted", timeout=30)

            # ---- the negative, with its positive controls -------------------
            container, server_net = _agent_network_name()
            agent_ip = _container_ipv4(container, server_net)
            reachable = _backend_sh(f"ping -c 2 -W 2 {agent_ip}")
            assert reachable.returncode == 0, (
                "the backend cannot ICMP a host on a network it IS attached to, so the "
                "isolation assertions below would hold even with no isolation at all: "
                f"{reachable.stdout!r} {reachable.stderr!r}"
            )
            listening = _backend_sh(f"nc -z -w 3 127.0.0.1 {_BACKEND_HTTPS_PORT}")
            assert listening.returncode == 0, (
                "`nc` cannot connect to the backend's own open port, so the TCP half of "
                f"the isolation check proves nothing: {listening.stdout!r} {listening.stderr!r}"
            )
            _assert_backend_cannot_reach(_PROBE_TARGET_IP, _PROBE_NET_CIDR)

            # ---- the baseline every later claim is measured against ---------
            _wait_until(
                lambda: {_AGENT_NET_CIDR, _PROBE_NET_CIDR} <= _automatic_scope(client, agent_id),
                timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
            )
            _wait_until(
                lambda: len(_discovery_profiles(client, agent_id)) >= 2,
                timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
            )
            probe_profile = _system_profile_for(client, agent_id, _PROBE_NET_CIDR)
            _system_profile_for(client, agent_id, _AGENT_NET_CIDR)
            expected_cron = f"{agent_id % 60} */6 * * *"
            assert probe_profile["schedule_cron"] == expected_cron, (
                "the automatic profile does not carry D-7's derived six-hourly cadence, so "
                f"there is no recurrence for the restart to resume: {probe_profile}"
            )

            initial_job = _wait_until_and_return(
                lambda: next(iter(_scan_jobs(client, profile_id=probe_profile["id"])), None),
                timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
            )
            initial_job_id = initial_job["id"]
            _wait_until(
                lambda: _scan_job(client, initial_job_id)["status"] == "completed",
                timeout=_INITIAL_SCAN_BUDGET_S,
            )

            pending = [r for r in _review_queue(client) if r["ip_address"] == _PROBE_TARGET_IP]
            assert len(pending) == 1, (
                f"expected exactly one pending review row for {_PROBE_TARGET_IP}: {pending}"
            )
            fixture_row = pending[0]
            observed_hostname = fixture_row["hostname"]
            assert observed_hostname, (
                "the agent reported no hostname for the fixture, so the untrusted-hostname "
                "half of plan §8 step 11 has nothing to disagree about. probe-net's resolver "
                "is Docker's embedded DNS, which answers PTR for containers on a user-defined "
                "network; if it has stopped doing so this test needs a fixture that supplies "
                f"a name some other way. Row: {fixture_row}"
            )
            assert not _hardware_with_ip(client, _PROBE_TARGET_IP), (
                "a Hardware row for the fixture existed before anybody imported it"
            )
            merged = client.post(
                f"/api/v1/discovery/results/{fixture_row['id']}/merge",
                json={"action": "accept", "entity_type": "hardware"},
            )
            assert merged.status_code == 200, merged.text
            hardware = _hardware_with_ip(client, _PROBE_TARGET_IP)
            assert len(hardware) == 1, f"import created {len(hardware)} Hardware rows: {hardware}"
            hardware_id = hardware[0]["id"]
            assert hardware[0]["name"] == observed_hostname, (
                "the imported row is not named after the hostname the agent reported, so the "
                f"rename below would not create a disagreement: {hardware[0]}"
            )

            # Quiescence: the bootstrap queued one scan per subnet and the
            # restart below must not land on top of one still running.
            _wait_until(
                lambda: not _unfinished_agent_jobs(client, agent_id),
                timeout=_INITIAL_SCAN_BUDGET_S,
            )

            # ---- STEP 9: both ends restart and the address moves ------------
            agents_before = _agents(client)
            agent_before = client.get(f"/api/v1/agents/{agent_id}").json()
            device_key_before = _device_key(_AGENT_SERVICE)
            enrolled_before = _enrolled_event_ids(client, agent_id)
            profiles_before = _discovery_profiles(client, agent_id)
            all_profiles_before = _all_profiles(client)

            subprocess.run([*COMPOSE, "restart", "circuitbreaker"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=240
            )
            old_ip, new_ip = _change_agent_address(_AGENT_NET_MOVED_IP)
            # Read *here*, immediately before the restart, and from the agent's
            # own status file rather than from the server. `compose restart`
            # keeps the state volume, so the container comes back to the
            # status.json it left behind — a bare `link_state == "accepted"`
            # would be satisfied by the stale value already in that file, and
            # the assertions below would be describing the connection this test
            # has just broken rather than the one it is waiting for.
            #
            # (`AgentRead.connected_since` looks like the obvious server-side
            # witness and is not one: presence lives in Redis, and the ORM
            # column that field is validated from is never written, so it reads
            # NULL for a connected agent.)
            status_before = _agent_status()["updated_at"]
            # `restart`, never `up --force-recreate`: the state volume carries
            # the enrollment whose survival is half of what this step claims,
            # and a recreate would also undo the address change under test.
            subprocess.run([*COMPOSE, "restart", _AGENT_SERVICE], check=True, cwd=E2E_DIR)

            # A *fresh* `accepted` is the hello landing, and that is what makes
            # the no-duplication assertions below about a bootstrap pass that
            # actually ran: `ws_agents` applies the hello's facts —
            # `agent_registry.record_network_facts`, which is what defers
            # `discovery_bootstrap.schedule_bootstrap` — before it writes the
            # `hello.ack` the agent needs to reach this state at all.
            def _reconnected() -> bool:
                status = _agent_status()
                return (
                    status["link_state"] == "accepted" and status["updated_at"] != status_before
                )

            _wait_until(_reconnected, timeout=_RECONNECT_BUDGET_S)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=_RECONNECT_BUDGET_S,
            )

            moved = _backend_sh(f"ping -c 2 -W 2 {new_ip}")
            assert moved.returncode == 0, (
                "PROPERTY 9 (address change): the backend cannot reach the agent at its new "
                f"address {new_ip}, so the move did not take: {moved.stdout!r} {moved.stderr!r}"
            )
            vacated = _backend_sh(f"ping -c 2 -W 2 {old_ip}")
            assert vacated.returncode != 0, (
                f"PROPERTY 9 (address change): {old_ip} still answers, so the agent did not "
                f"actually leave its old address: {vacated.stdout!r} {vacated.stderr!r}"
            )
            assert _agent_route_networks() == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                "PROPERTY 9 (address change): the agent's own routing table changed, so this "
                "is a subnet change rather than the address change the profile-duplication "
                f"risk is about: {sorted(_agent_route_networks())}"
            )

            agent_after = client.get(f"/api/v1/agents/{agent_id}").json()
            assert len(_agents(client)) == len(agents_before) == 1, (
                "PROPERTY 9 (no re-enrollment): the fleet gained an agent across the restart — "
                f"{[a['id'] for a in _agents(client)]}"
            )
            assert agent_after["device_pk"] == agent_before["device_pk"], (
                "PROPERTY 9 (no re-enrollment): the agent presented a different device key "
                "after the restart, so it enrolled again rather than resuming"
            )
            assert agent_after["enrolled_at"] == agent_before["enrolled_at"], (
                "PROPERTY 9 (no re-enrollment): `enrolled_at` moved, so the server treated "
                f"this as a fresh enrollment: {agent_before['enrolled_at']} -> "
                f"{agent_after['enrolled_at']}"
            )
            assert _device_key(_AGENT_SERVICE) == device_key_before, (
                "PROPERTY 9 (no re-enrollment): the agent's on-disk device.key changed, so it "
                "lost its state volume and generated a new identity"
            )
            assert _enrolled_event_ids(client, agent_id) == enrolled_before, (
                "PROPERTY 9 (no re-enrollment): a second `enrolled` event was recorded for "
                "this agent"
            )

            assert _automatic_scope(client, agent_id) == {_AGENT_NET_CIDR, _PROBE_NET_CIDR}, (
                "PROPERTY 9 (scope survives): the server's derived scope changed when only the "
                f"agent's host address did: {sorted(_automatic_scope(client, agent_id))}"
            )
            profiles_after = _discovery_profiles(client, agent_id)
            assert {p["id"] for p in profiles_after} == {p["id"] for p in profiles_before}, (
                "PROPERTY 9 (no profile duplication): the bootstrap pass that ran on the "
                "reconnect created or replaced a system profile. An address change must be a "
                f"no-op: {[(p['id'], p['cidr']) for p in profiles_after]}"
            )
            # Re-asserts "exactly one" for the subnet whose ADDRESS moved, which
            # is the row a duplicated upsert would have doubled.
            _system_profile_for(client, agent_id, _AGENT_NET_CIDR)
            probe_profile = _system_profile_for(client, agent_id, _PROBE_NET_CIDR)
            assert len(_all_profiles(client)) == len(all_profiles_before), (
                "PROPERTY 9 (no profile duplication): the installation gained a discovery "
                "profile across the restart and address change"
            )
            assert probe_profile["schedule_cron"] == expected_cron, (
                "PROPERTY 9 (recurrence resumes): the derived six-hourly cadence did not "
                f"survive the restart: {probe_profile}"
            )
            assert probe_profile["enabled"] and probe_profile["paused_at"] is None, probe_profile
            next_scheduled = _discovery_status(client)["next_scheduled"]
            assert next_scheduled is not None, (
                "PROPERTY 9 (recurrence resumes): no discovery profile is registered with "
                "APScheduler after the backend restarted, so the six-hourly cadence exists "
                "only as a column and will never fire again"
            )
            assert _parse_ts(next_scheduled) > datetime.now(timezone.utc), (
                f"the next scheduled discovery run is in the past: {next_scheduled}"
            )
            bootstrap_jobs = [
                job
                for job in _scan_jobs(client, profile_id=probe_profile["id"])
                if job["triggered_by"] == "bootstrap"
            ]
            assert len(bootstrap_jobs) == 1, (
                "PROPERTY 9 (no duplicated automatic work): the reconnect queued another "
                f"automatic first scan: {[j['id'] for j in bootstrap_jobs]}"
            )

            # ---- STEP 11a: known device vs genuinely new device -------------
            _up_fixture_target(_PROBE_TARGET_NEW_SERVICE)
            # Doubles as a settle: two rounds of pings and a connect attempt is
            # long enough for the fixture's netns to be answering by the time
            # the sweep below reaches it.
            _assert_backend_cannot_reach(_PROBE_TARGET_NEW_IP, _PROBE_NET_CIDR)
            assert not [
                row
                for row in _job_results(client, initial_job_id)
                if row["ip_address"] == _PROBE_TARGET_NEW_IP
            ], (
                f"the first sweep already reported {_PROBE_TARGET_NEW_IP}, so it is not the "
                "genuinely-new device this step needs"
            )

            recurring_id = _run_profile_now(client, probe_profile["id"])["id"]
            assert recurring_id != initial_job_id
            _wait_until(
                lambda: _scan_job(client, recurring_id)["status"] == "completed",
                timeout=_RECURRING_SCAN_BUDGET_S,
            )
            recurring = _scan_job(client, recurring_id)
            assert recurring["scan_agent_id"] == agent_id, recurring
            rows = {row["ip_address"]: row for row in _job_results(client, recurring_id)}
            assert _PROBE_TARGET_IP in rows and _PROBE_TARGET_NEW_IP in rows, (
                "PROPERTY 11 (recurrence): the recurring sweep did not report both fixtures — "
                f"saw {sorted(rows)}"
            )

            known = rows[_PROBE_TARGET_IP]
            assert known["state"] == "matched", (
                "PROPERTY 11 (known device): a device already in the inventory came back as "
                f"{known['state']!r} rather than `matched`, so a recurring cadence cannot tell "
                f"it from a new one: {known}"
            )
            assert (known["matched_entity_type"], known["matched_entity_id"]) == (
                "hardware",
                hardware_id,
            ), (
                "PROPERTY 11 (known device): the recurring finding matched a different "
                f"Hardware row than the one it was imported as: {known}"
            )
            assert known["hostname"] == observed_hostname, known

            fresh = rows[_PROBE_TARGET_NEW_IP]
            assert fresh["state"] == "new" and fresh["matched_entity_id"] is None, (
                "PROPERTY 11 (new device): a host the inventory has never seen came back as "
                f"{fresh['state']!r}: {fresh}"
            )
            assert fresh["merge_status"] == "pending", fresh
            assert any(row["id"] == fresh["id"] for row in _review_queue(client)), (
                "PROPERTY 11 (new device): the genuinely new device is not in the ordinary "
                "review queue, which is the one place an operator is asked to look"
            )
            assert recurring["hosts_new"] >= 1 and recurring["hosts_updated"] >= 1, (
                "PROPERTY 11 (recurrence): the job counters do not separate new hosts from "
                f"ones the inventory already knew: {recurring}"
            )
            assert recurring["hosts_conflict"] == 0, (
                "PROPERTY 11 (recurrence): the sweep flagged a conflict although nothing about "
                f"any known device changed: {recurring}"
            )
            assert [h["id"] for h in _hardware_with_ip(client, _PROBE_TARGET_IP)] == [
                hardware_id
            ], "PROPERTY 11 (known device): the recurring sweep created a second Hardware row"
            assert not _hardware_with_ip(client, _PROBE_TARGET_NEW_IP), (
                "PROPERTY 11 (new device): the recurring sweep imported the new device by "
                "itself — plan §5 requires an agent-authored row to reach the inventory only "
                "when a user accepts it"
            )
            # The current contract, stated as such. Plan §8 step 11 also asks
            # for an unchanged known device to be auto-updated out of the queue
            # with a refreshed `last_seen`; `_auto_merge_known_devices` is
            # reachable only from `_scan_finalize`, and an agent job is closed
            # by `finalize_agent_job`, which never calls it. If this assertion
            # ever fails, that decision has changed and this test should assert
            # the refresh instead of pinning its absence.
            assert known["merge_status"] == "pending", (
                "an agent-executed recurring scan auto-updated a known unchanged device out "
                "of the review queue. That is what plan §8 step 11 asks for, and it is NOT "
                "what `finalize_agent_job` does today (it documents never calling "
                "`_auto_merge_known_devices` at any setting). Something has changed on "
                f"purpose: update this test rather than reverting it. Row: {known}"
            )

            # ---- STEP 11b: an untrusted hostname never renames inventory ----
            _rename_hardware(client, hardware_id, _OPERATOR_HARDWARE_NAME)
            renamed = _hardware_row(client, hardware_id)
            last_seen_before = renamed["last_seen"]

            conflict_id = _run_profile_now(client, probe_profile["id"])["id"]
            _wait_until(
                lambda: _scan_job(client, conflict_id)["status"] == "completed",
                timeout=_RECURRING_SCAN_BUDGET_S,
            )
            conflict_job = _scan_job(client, conflict_id)
            conflict_rows = {row["ip_address"]: row for row in _job_results(client, conflict_id)}
            conflicted = conflict_rows[_PROBE_TARGET_IP]
            assert conflicted["state"] == "conflict", (
                "PROPERTY 11 (untrusted hostname): the agent reported a hostname that "
                f"disagrees with the inventory and the result came back {conflicted['state']!r} "
                f"rather than `conflict`: {conflicted}"
            )
            assert conflicted["merge_status"] == "pending", (
                "PROPERTY 11 (untrusted hostname): the disagreement was resolved without an "
                f"operator; plan §4 requires it to be a review: {conflicted}"
            )
            fields = {
                entry["field"]: entry
                for entry in json.loads(conflicted["conflicts_json"] or "[]")
            }
            assert "hostname" in fields, (
                "PROPERTY 11 (untrusted hostname): the conflict does not name the hostname, so "
                f"an operator cannot see what the two sources disagree about: {fields}"
            )
            assert fields["hostname"]["stored"] == _OPERATOR_HARDWARE_NAME, fields["hostname"]
            assert fields["hostname"]["discovered"] == observed_hostname, fields["hostname"]
            assert conflict_job["hosts_conflict"] >= 1, conflict_job
            after_rename = _hardware_row(client, hardware_id)
            assert after_rename["name"] == _OPERATOR_HARDWARE_NAME, (
                "PROPERTY 11 (untrusted hostname): the agent's reported hostname overwrote the "
                "name an operator gave the device. Plan §4 lists hostname among the agent's "
                f"untrusted observations: {after_rename}"
            )
            assert any(row["id"] == conflicted["id"] for row in _review_queue(client)), (
                "PROPERTY 11 (untrusted hostname): the conflicting row is not in the review "
                "queue, so nobody is ever told the two sources disagree"
            )
            # The other half of the contract pinned above: no auto-update means
            # no `last_seen` refresh either, on the conflicting row or on any
            # other agent-reported one.
            assert after_rename["last_seen"] == last_seen_before, (
                "an agent-executed scan refreshed Hardware.last_seen. Plan §8 step 11 asks "
                "for exactly that, and `finalize_agent_job` does not do it today — see the "
                f"note on `merge_status` above: {last_seen_before} -> {after_rename['last_seen']}"
            )

            # ---- STEP 10: a second agent, and provenance that stays put -----
            _up_fixture_target(_PROBE_TARGET_2_SERVICE)
            assert _network_subnet(_AGENT_2_NET) == _AGENT_2_NET_CIDR
            assert _network_subnet(_PROBE_NET_2) == _PROBE_NET_2_CIDR
            _assert_backend_cannot_reach(_PROBE_TARGET_2_IP, _PROBE_NET_2_CIDR)

            agent2_id, stream2 = _enroll_agent(client, headers, service=_AGENT_2_SERVICE)
            try:
                subprocess.run(
                    [*COMPOSE, "up", "-d", _AGENT_2_SERVICE], check=True, cwd=E2E_DIR
                )
                _wait_until(
                    lambda: client.get(f"/api/v1/agents/{agent2_id}").json()["status"] == "active",
                    timeout=30,
                )
                _wait_until(
                    lambda: _agent_status(service=_AGENT_2_SERVICE)["link_state"] == "accepted",
                    timeout=30,
                )
                assert agent2_id != agent_id
                assert _device_key(_AGENT_SERVICE) != _device_key(_AGENT_2_SERVICE), (
                    "PROPERTY 10 (two agents): both containers hold the same device.key, so "
                    "this is one agent wearing two hats and every attribution claim below is "
                    "vacuous"
                )
                # The provenance-critical half: each kernel sees its own fixture
                # subnet and not the other's.
                assert _agent_route_networks(service=_AGENT_2_SERVICE) == {
                    _AGENT_2_NET_CIDR,
                    _PROBE_NET_2_CIDR,
                }
                assert _PROBE_NET_2_CIDR not in _agent_route_networks()
                assert _PROBE_NET_CIDR not in _agent_route_networks(service=_AGENT_2_SERVICE)

                _wait_until(
                    lambda: {_AGENT_2_NET_CIDR, _PROBE_NET_2_CIDR}
                    <= _automatic_scope(client, agent2_id),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                assert _automatic_scope(client, agent2_id) == {
                    _AGENT_2_NET_CIDR,
                    _PROBE_NET_2_CIDR,
                }, (
                    "PROPERTY 10 (no scope leakage): agent 2's derived scope is not exactly its "
                    f"own two subnets: {sorted(_automatic_scope(client, agent2_id))}"
                )
                assert _automatic_scope(client, agent_id) == {
                    _AGENT_NET_CIDR,
                    _PROBE_NET_CIDR,
                }, (
                    "PROPERTY 10 (no scope leakage): enrolling a second agent changed the "
                    f"first one's scope: {sorted(_automatic_scope(client, agent_id))}"
                )

                _wait_until(
                    lambda: len(_discovery_profiles(client, agent2_id)) >= 2,
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                probe2_profile = _system_profile_for(client, agent2_id, _PROBE_NET_2_CIDR)
                _system_profile_for(client, agent2_id, _AGENT_2_NET_CIDR)
                assert {p["id"] for p in _discovery_profiles(client, agent_id)} == {
                    p["id"] for p in profiles_after
                }, (
                    "PROPERTY 10 (two agents): the second agent's bootstrap disturbed the "
                    "first agent's profiles"
                )

                job2 = _wait_until_and_return(
                    lambda: next(iter(_scan_jobs(client, profile_id=probe2_profile["id"])), None),
                    timeout=_DISCOVERY_BOOTSTRAP_BUDGET_S,
                )
                _wait_until(
                    lambda: _scan_job(client, job2["id"])["status"] == "completed",
                    timeout=_INITIAL_SCAN_BUDGET_S,
                )
                assert any(
                    row["ip_address"] == _PROBE_TARGET_2_IP
                    for row in _job_results(client, job2["id"])
                ), (
                    "PROPERTY 10 (two agents): agent 2 did not find its own fixture, so there "
                    "is nothing whose attribution can be checked"
                )

                # ---- the provenance column itself -----------------------
                reach = {
                    agent_id: (_AGENT_NET_CIDR, _PROBE_NET_CIDR),
                    agent2_id: (_AGENT_2_NET_CIDR, _PROBE_NET_2_CIDR),
                }
                provenance = _result_provenance()
                agent_rows = [r for r in provenance if r["job_scan_agent_id"] is not None]
                assert agent_rows, "no agent-executed results at all; nothing to attribute"
                for row in agent_rows:
                    assert row["discovery_agent_id"] == row["job_scan_agent_id"], (
                        "PROPERTY 10 (no cross-attribution): a result's own reporter "
                        f"({row['discovery_agent_id']}) is not the agent its job was "
                        f"dispatched to ({row['job_scan_agent_id']}). Those two columns are "
                        f"written by different code paths and must never disagree: {row}"
                    )
                    assert _in_any(row["ip_address"], reach[row["discovery_agent_id"]]), (
                        "PROPERTY 10 (no cross-attribution): result "
                        f"{row['id']} names {row['ip_address']} as reported by agent "
                        f"{row['discovery_agent_id']}, which has no route to that address "
                        f"(its subnets are {list(reach[row['discovery_agent_id']])})"
                    )
                for address in (_PROBE_TARGET_IP, _PROBE_TARGET_NEW_IP, _PROBE_TARGET_2_IP):
                    reporters = {
                        row["discovery_agent_id"]
                        for row in provenance
                        if row["ip_address"] == address
                    }
                    expected = {agent2_id} if address == _PROBE_TARGET_2_IP else {agent_id}
                    assert reporters == expected, (
                        f"PROPERTY 10 (no cross-attribution): {address} is attributed to "
                        f"{sorted(reporters)}, expected {sorted(expected)}"
                    )

                # ---- and the negative, over the topology as it stands ----
                for subnet, address in (
                    (_PROBE_NET_CIDR, _PROBE_TARGET_IP),
                    (_PROBE_NET_CIDR, _PROBE_TARGET_NEW_IP),
                    (_PROBE_NET_2_CIDR, _PROBE_TARGET_2_IP),
                ):
                    _assert_backend_cannot_reach(address, subnet)
            finally:
                stream2.close()
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# Slice 4.1 (F4): a certificate change must not strand the fleet
# ─────────────────────────────────────────────────────────────────────────


def _tls_pin_status(client: httpx.Client) -> dict:
    resp = client.get("/api/v1/agents/tls-pin/status")
    resp.raise_for_status()
    return resp.json()


def _create_selfsigned_certificate(client: httpx.Client, domain: str) -> int:
    """Stage a new self-signed certificate without activating it. The server
    generates a fresh keypair, so its SPKI digest genuinely differs from the
    one nginx is serving — which is what makes this a real cutover rather
    than a re-advertisement of the pin the agent already holds."""
    resp = client.post(
        "/api/v1/certificates",
        json={"domain": domain, "type": "selfsigned", "auto_renew": False},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_certificate_rotation_does_not_strand_the_fleet():
    """F4 end to end: replace the server certificate, and the enrolled agent
    must still be there afterwards — and still be there on the reconnect
    after that.

    This is the scenario that made F4 fleet-bricking rather than
    inconvenient: the agent's pin gates its update download too, so an agent
    stranded here cannot be repaired by pushing it a new binary. Both halves
    are asserted, because each was independently broken:

      * activation is refused until the fleet holds the successor, and
      * a promoted agent keeps working past the single connection that
        immediately follows the cutover.
    """
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
                timeout=30,
            )

            new_cert_id = _create_selfsigned_certificate(client, "rotated.cb-e2e.invalid")

            # Before the advertisement, activation must be refused. Nothing
            # has told the agent about the leaf it is about to be handed, and
            # this is the likeliest way to hit F4 in the field: swapping the
            # certificate without knowing the mechanism exists at all.
            premature = client.post(f"/api/v1/certificates/{new_cert_id}/activate")
            assert premature.status_code == 409, (
                f"activation was allowed with an unprepared fleet: "
                f"{premature.status_code} {premature.text}"
            )
            assert "no rotation has advertised" in premature.json()["detail"]

            rotate = client.post(
                "/api/v1/agents/tls-pin/rotate", json={"certificate_id": new_cert_id}
            )
            assert rotate.status_code == 201, rotate.text

            # The agent confirms it holds the successor while the OLD
            # certificate is still being served — the whole point of the
            # readiness signal. A live socket is pushed the frame directly,
            # so this does not wait on a reconnect.
            _wait_until(
                lambda: _tls_pin_status(client)["unconverged"] == 0,
                timeout=90,
                interval=2.0,
            )
            assert _tls_pin_status(client)["converged"] == 1

            activate = client.post(f"/api/v1/certificates/{new_cert_id}/activate")
            assert activate.status_code == 200, activate.text

            # nginx now serves a leaf the agent was never installed with.
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=120,
                interval=2.0,
            )
            assert _tls_pin_status(client)["active"] is False

            # The second half. Promotion clears the advertised successor, so
            # a reconnect from here resolves the agent's *promoted* policy
            # alone. Force one and require the agent back: the earlier defect
            # survived exactly the connection above and stranded on this one.
            _wait_until(
                lambda: "promoted the successor TLS trust policy" in _agent_logs(),
                timeout=90,
                interval=2.0,
            )
            subprocess.run([*COMPOSE, "restart", "cb-agent"], check=True, cwd=E2E_DIR)
            _wait_until(
                lambda: client.get(f"/api/v1/agents/{agent_id}").json()["status"] == "active",
                timeout=120,
                interval=2.0,
            )
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)


def test_activation_is_refused_while_an_agent_cannot_confirm():
    """The gate itself: an agent that is not running cannot be told about the
    successor, so activating would strand it. The refusal is what makes the
    ordering in docs/tls-trust-rotation.md enforceable rather than advisory."""
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
                timeout=30,
            )

            new_cert_id = _create_selfsigned_certificate(client, "ungated.cb-e2e.invalid")
            subprocess.run([*COMPOSE, "stop", "cb-agent"], check=True, cwd=E2E_DIR)

            rotate = client.post(
                "/api/v1/agents/tls-pin/rotate", json={"certificate_id": new_cert_id}
            )
            assert rotate.status_code == 201, rotate.text

            resp = client.post(f"/api/v1/certificates/{new_cert_id}/activate")
            assert resp.status_code == 409, f"{resp.status_code} {resp.text}"

            pending = client.get("/api/v1/agents/tls-pin/pending").json()
            assert [row["id"] for row in pending] == [agent_id]

            # And the override is available, audited, for the operator who
            # decides the stranded agent is acceptable collateral.
            forced = client.post(f"/api/v1/certificates/{new_cert_id}/activate?force=true")
            assert forced.status_code == 200, forced.text
        finally:
            stream.close()
    finally:
        _down()
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)
