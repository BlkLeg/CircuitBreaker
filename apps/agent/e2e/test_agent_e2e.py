"""End-to-end: copy-command -> enroll -> approve -> online -> revoke closes
the socket. Requires Docker; not run by default pytest invocations.

Run explicitly:
    cd apps/agent/e2e && pytest test_agent_e2e.py -v -m e2e
"""

import hashlib
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

BASE_URL = "https://localhost:8443"
COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "docker-compose.yml")]
E2E_DIR = Path(__file__).parent


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
                "email": "e2e@example.com",
                "password": "E2eTest1234!",
                "theme_preset": "one-dark",
            },
        )
    else:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "e2e@example.com", "password": "E2eTest1234!"},
        )
    resp.raise_for_status()
    # bootstrap/login also sets a cb_session cookie; if this client kept it,
    # every subsequent mutating request would be treated as cookie-authenticated
    # and rejected by CSRFMiddleware for lacking an X-CSRF-Token header. Clearing
    # it here keeps this client purely bearer-token-authenticated, matching how
    # a real API consumer (not the browser UI) talks to these endpoints.
    client.cookies.clear()
    return resp.json()["token"]


@pytest.mark.e2e
def test_agent_enrolls_approves_goes_online_and_revoke_closes_link():
    subprocess.run([*COMPOSE, "up", "-d", "--build", "circuitbreaker"], check=True, cwd=E2E_DIR)
    try:
        # verify=False is deliberate and test-scoped: the mono container generates
        # a fresh self-signed cert per run with no stable CA to pin/trust here,
        # and this harness never leaves localhost. Do not carry this pattern into
        # any production code path — agent_install.py's tls_pin mechanism (Task 17)
        # is the real integrity anchor for actual installs.
        client = httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0)
        _wait_until(lambda: client.get("/api/v1/bootstrap/status").status_code == 200, timeout=60)

        token = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {token}"}

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
        (E2E_DIR / "agent.toml").write_text(
            f'server_url = "{BASE_URL}"\n'
            f'server_static_pk = "{server_pk}"\n'
            f'tls_pin = "{tls_pin}"\n'
            f'log_level = "info"\n'
            f"spool_cap_bytes = 67108864\n"
        )

        subprocess.run([*COMPOSE, "build", "cb-agent"], check=True, cwd=E2E_DIR)
        proc = subprocess.Popen(
            [*COMPOSE, "run", "--rm", "cb-agent", "enroll"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=E2E_DIR,
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

        approve = client.post(f"/api/v1/agents/{agent_id}/approve", json={}, headers=headers)
        assert approve.status_code == 200, approve.text

        assert proc.wait(timeout=15) == 0, "enroll process did not exit 0 after approval"

        subprocess.run([*COMPOSE, "up", "-d", "cb-agent"], check=True, cwd=E2E_DIR)
        _wait_until(
            lambda: client.get(f"/api/v1/agents/{agent_id}", headers=headers).json()["status"]
            == "active",
            timeout=15,
        )

        revoke = client.post(
            f"/api/v1/agents/{agent_id}/revoke",
            json={"reason": "e2e test"},
            headers=headers,
        )
        assert revoke.status_code == 200, revoke.text

        # Task 12's /link poll interval is 5s — allow a bit of margin.
        time.sleep(8)
        logs = subprocess.run(
            [*COMPOSE, "logs", "cb-agent"],
            capture_output=True,
            text=True,
            cwd=E2E_DIR,
        ).stdout
        assert "disconnect" in logs.lower() or "reconnect" in logs.lower(), (
            f"expected the agent log to show the link closing after revoke; got:\n{logs}"
        )
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], cwd=E2E_DIR)
        (E2E_DIR / "agent.toml").unlink(missing_ok=True)
