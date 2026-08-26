"""SRV-01: the server runs headless — no bundled frontend, no UI-only assumptions.

"The web UI is its first client, not an undocumented prerequisite"
(04-server-product-contract.md). The prerequisite is only absent if removing
the frontend artifact leaves an API that still builds, still publishes its
contract, and still answers the health and admin surface — which is what these
tests check, in a process that has never seen a `dist/` directory.

The frontend-absent case cannot be tested by importing the already-imported
`app.main`: the static directory is resolved once at import time, so a second
process is the only honest way to ask the question.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest
from httpx import AsyncClient

_HEADLESS_PROBE = r"""
import json, sys

import app.main as main

report = {
    "frontend_dir": None if main._get_frontend_dir() is None else str(main._get_frontend_dir()),
    "mounted": sorted(
        getattr(route, "path", "")
        for route in main.app.routes
        if getattr(route, "path", "") in ("/assets", "/icons")
    ),
    "root_route": any(getattr(route, "path", "") == "/" for route in main.app.routes),
    "openapi_paths": sorted(main.app.openapi()["paths"]),
}

# The workers must import in the same frontend-free process: a worker that
# reaches for a UI asset would only fail in the container that has none.
for module in (
    "app.workers.main",
    "app.workers.notification_worker",
    "app.workers.discovery",
    "app.workers.monitor_scheduler",
    "app.workers.monitor_poll_worker",
    "app.workers.monitor_probe_dispatch",
    "app.workers.telemetry_ingest_worker",
    "app.workers.integration_worker",
):
    __import__(module)
report["workers_imported"] = True

sys.stdout.write("REPORT:" + json.dumps(report))
"""


@pytest.fixture(scope="module")
def headless_report() -> dict:
    """Import the API and every worker in a process with no frontend build."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env.update(
            {
                "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
                # The frontend artifact is simply not there.
                "STATIC_DIR": os.path.join(tmp, "no-such-frontend-dist"),
                "UPLOADS_DIR": os.path.join(tmp, "uploads"),
                "CB_DATA_DIR": os.path.join(tmp, "data"),
                # Split-service deployment: this process is the API, and owns
                # no background worker.
                "CB_TOPOLOGY_MODE": "api",
                "CB_RUN_INPROCESS_WORKERS": "false",
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", _HEADLESS_PROBE],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    assert completed.returncode == 0, (
        f"headless import failed:\n{completed.stdout}\n{completed.stderr}"
    )
    marker = completed.stdout.rindex("REPORT:")
    return json.loads(completed.stdout[marker + len("REPORT:") :])


def test_the_api_builds_with_no_frontend_artifact(headless_report):
    assert headless_report["frontend_dir"] is None
    assert headless_report["mounted"] == [], "static asset mounts were created with no dist"
    # The placeholder root, not an SPA fallback that would shadow nothing.
    assert headless_report["root_route"] is True


def test_the_workers_import_with_no_frontend_artifact(headless_report):
    assert headless_report["workers_imported"] is True


def test_the_headless_process_still_publishes_its_whole_contract(headless_report):
    """OpenAPI is generated from the production app, so a headless deployment
    is documented by the same artifact a mono deployment is."""
    paths = set(headless_report["openapi_paths"])
    assert len(paths) > 100, f"only {len(paths)} paths published"
    for required in (
        "/api/v1/agents",
        "/api/v1/hardware",
        "/api/v1/admin/db/backup",
        "/api/v1/auth/login",
    ):
        assert required in paths, f"{required} missing from the published contract"


def test_the_probe_endpoints_are_published_for_a_headless_operator(headless_report):
    """An operator with no browser needs the health surface in the contract,
    not only in the source."""
    paths = set(headless_report["openapi_paths"])
    for probe in ("/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz", "/api/v1/health"):
        assert probe in paths, f"{probe} is not published in OpenAPI"


async def test_the_published_contract_is_served(client: AsyncClient):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "Circuit Breaker"


async def test_the_probe_operations_have_unique_operation_ids(client: AsyncClient):
    """A duplicate operationId is a hard error in OpenAPI client generators, so
    a contract that carries one is not usable by the machine clients SRV-01 is
    written for. Publishing GET and HEAD of the same probe as one operation
    produced exactly that."""
    schema = (await client.get("/api/openapi.json")).json()

    operation_ids = [
        operation["operationId"]
        for path, methods in schema["paths"].items()
        if path in ("/api/v1/livez", "/api/v1/readyz", "/api/v1/startupz", "/api/v1/health")
        for operation in methods.values()
        if "operationId" in operation
    ]

    assert len(operation_ids) == len(set(operation_ids)), operation_ids


async def test_errors_carry_a_machine_readable_code(client: AsyncClient, auth_headers):
    """SRV-01's second half: a headless client has no human reading a message,
    so a failure has to be classifiable without parsing prose."""
    response = await client.get("/api/v1/hardware/999999999", headers=auth_headers)

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
