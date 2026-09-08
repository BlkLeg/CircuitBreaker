"""The install command's server_url: it must reflect the scheme and host the
reverse proxy was actually asked for, not the plain-HTTP request uvicorn sees
behind nginx -- an agent handed ws:// would try its handshake in the clear.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

# ── Install command: the URL an agent is told to come back to ────────────────
#
# nginx terminates TLS and proxies to uvicorn over plain HTTP, so
# `request.url.scheme` is "http" for every request that reached the operator's
# browser as https. The agent turns that scheme into its websocket scheme
# (`u.Scheme = strings.Replace(u.Scheme, "http", "ws", 1)` in the agent's
# internal/enroll and internal/link), so an "http://" here is not cosmetic: it
# sends the agent at ws:// in the clear, where the tls_pin it was just issued
# is never checked and nginx's :8080 redirect-to-https is not something a
# websocket dialer follows. Enrollment simply fails.


@pytest.mark.asyncio
async def test_install_command_uses_the_scheme_the_proxy_terminated(
    client, auth_headers, monkeypatch
):
    """An https operator must not hand out an http:// server_url."""
    from app.services import agent_install

    seen: dict[str, str] = {}

    def _capture(db, server_url, endpoint_id=None, enroll_token=None):
        seen["server_url"] = server_url
        raise ValueError("stop here — the URL is the whole assertion")

    monkeypatch.setattr(agent_install, "build_install_command", _capture)

    await client.get(
        "/api/v1/agents/install-command",
        headers={**auth_headers, "X-Forwarded-Proto": "https"},
    )

    assert seen["server_url"].startswith("https://"), seen


@pytest.mark.asyncio
async def test_install_command_uses_the_host_the_proxy_was_asked_for(
    client, auth_headers, monkeypatch
):
    """`X-Forwarded-Host` decides the hostname an agent will dial back."""
    from app.services import agent_install

    seen: dict[str, str] = {}

    def _capture(db, server_url, endpoint_id=None, enroll_token=None):
        seen["server_url"] = server_url
        raise ValueError("stop here — the URL is the whole assertion")

    monkeypatch.setattr(agent_install, "build_install_command", _capture)

    await client.get(
        "/api/v1/agents/install-command",
        headers={
            **auth_headers,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "cb.example.com",
        },
    )

    assert seen["server_url"] == "https://cb.example.com", seen
