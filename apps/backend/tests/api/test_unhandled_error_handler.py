"""The catch-all 500 handler must leave evidence behind.

`main.unhandled_error_handler` deliberately tells the client nothing but
"Internal server error" outside dev_mode. For a long time it told the *server*
nothing either: the exception was formatted into a response and then dropped.

That is not a theoretical gap. Nine consecutive nightly Composed-Agent-E2E runs
failed on a 500 from `POST /agents/{id}/update`, and the cause had to be
reconstructed from file ownership inside the container because no traceback was
written anywhere. The scenario exercised below is that exact one: an
`agent-binaries/manifest.json` the server process cannot read.
"""

import logging

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_unhandled_exception_is_logged_with_a_traceback(
    client, factories, auth_headers, monkeypatch, caplog
):
    from app.main import app
    from app.services import agent_update

    def unreadable_manifest(*args, **kwargs):
        raise PermissionError(
            13, "Permission denied", "/opt/circuitbreaker/agent-binaries/manifest.json"
        )

    monkeypatch.setattr(agent_update, "load_manifest", unreadable_manifest)
    agent = factories.agent(status="active", os="linux", arch="amd64")

    # A separate transport because the shared `client` fixture leaves
    # `raise_app_exceptions` at its default, which re-raises through the test
    # instead of letting the handler's response come back. The fixture is still
    # requested above: it is what installs the get_db override this uses.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as raw:
        with caplog.at_level(logging.ERROR, logger="app.main"):
            resp = await raw.post(
                f"/api/v1/agents/{agent.id}/update",
                json={"version": "9.9.9-pinned"},
                headers=auth_headers,
            )

    assert resp.status_code == 500
    assert resp.json()["error_code"] == "INTERNAL_SERVER_ERROR"

    matching = [r for r in caplog.records if "unhandled exception" in r.getMessage()]
    assert matching, f"the 500 was not logged at all: {[r.getMessage() for r in caplog.records]}"
    assert any(r.exc_info for r in matching), (
        "logged without exc_info — the traceback is what makes the record useful"
    )
    assert any("/update" in r.getMessage() for r in matching), (
        "the record must name the route that failed"
    )
