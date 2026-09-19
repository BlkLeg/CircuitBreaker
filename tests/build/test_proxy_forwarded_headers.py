"""Every reverse proxy we ship must tell the app which scheme the client used.

nginx terminates TLS and proxies to uvicorn over plain HTTP. Without
`X-Forwarded-Proto` the app cannot tell an https request from an http one, and
`app.core.forwarded.forwarded_base_url` — which decides the `server_url`
written into every agent's `/etc/circuit-breaker/agent.toml` — falls back to
the raw scheme and hands agents `http://`. The agent turns that into a
plaintext `ws://` dial, so the `tls_pin` issued in the same response is never
checked and enrollment fails against the redirect it will not follow.

`deploy/nginx/circuitbreaker*.conf` (the native install) always set the header;
`docker/nginx.mono.conf` did not, which made the mono container the only
deployment where agent enrollment could not work over https.

The rule enforced here is deliberately mechanical: a `location` block that
forwards `X-Forwarded-For` is a block that proxies to the app, so it must
forward `X-Forwarded-Proto` too. That catches a *new* proxy block added
without the header, which is how this defect would come back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PROXY_CONFIGS = [
    REPO_ROOT / "docker" / "nginx.mono.conf",
    REPO_ROOT / "docker" / "nginx.dev.conf",
    REPO_ROOT / "deploy" / "nginx" / "circuitbreaker.conf",
    REPO_ROOT / "deploy" / "nginx" / "circuitbreaker-tls.conf",
]

_LOCATION = re.compile(r"^\s*location\s+(?P<match>[^{]+)\{")


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split an nginx config into (location, body) pairs by brace depth.

    A hand-rolled split rather than a real parser: these files are ours and
    conventionally formatted, and the alternative is a dependency that CI would
    have to install to run a policy test.
    """
    blocks: list[tuple[str, str]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _LOCATION.match(line)
        if not match:
            continue
        depth = 0
        body: list[str] = []
        for following in lines[index:]:
            depth += following.count("{") - following.count("}")
            body.append(following)
            if depth <= 0:
                break
        blocks.append((match.group("match").strip(), "\n".join(body)))
    return blocks


@pytest.mark.parametrize("config", PROXY_CONFIGS, ids=lambda p: p.name)
def test_every_proxying_location_forwards_the_original_scheme(config: Path):
    assert config.is_file(), f"{config} is missing"
    offenders = [
        location
        for location, body in _blocks(config.read_text())
        if "X-Forwarded-For" in body and "X-Forwarded-Proto" not in body
    ]
    assert not offenders, (
        f"{config.name}: these location blocks proxy to the app but never send "
        f"X-Forwarded-Proto, so the app cannot tell https from http: {offenders}"
    )


# `$http_host` is the raw Host header, port included. `$host` is not: nginx
# strips the port from it (and lowercases it), which is the entire defect this
# rule exists to prevent.
_FORWARDED_HOST = re.compile(r"proxy_set_header\s+X-Forwarded-Host\s+\$http_host\s*;")


@pytest.mark.parametrize("config", PROXY_CONFIGS, ids=lambda p: p.name)
def test_every_proxying_location_pins_the_external_host(config: Path):
    """The sibling of the scheme rule above, on the axis of host-and-port.

    Two separate defects share this one cause, and both were live:

    1.  Every proxying location sends `Host $host`, and nginx's `$host` has the
        port stripped. `forwarded_host` therefore falls back to a netloc with no
        port, so `forwarded_base_url` hands agents `https://cb.example.com` for a
        server reachable only at `https://cb.example.com:8443`. `CB_PORT_HTTPS`
        in docker-compose.yml is an operator-settable variable, so every install
        that does not use 443 wrote an unreachable `server_url` into
        `/etc/circuit-breaker/agent.toml` — and the agent dials it directly, with
        no redirect to follow and no browser to correct it.

    2.  `X-Forwarded-Host` is trusted whenever the socket peer is one of our
        proxies (`core.forwarded`), and that trust is what `auth_oauth`'s OAuth
        `redirect_uri` and `smtp_service`'s password-reset links are built on.
        No config we ship ever set the header, and nginx passes client headers
        through untouched — so the value those paths trusted was the client's
        own. Setting it here is what makes the module docstring's threat model
        ("a peer that is not one of our own proxies cannot steer the URL") true.

    Same mechanical shape as the scheme rule, for the same reason: it is a new
    proxy block added without the header that brings the defect back.
    """
    assert config.is_file(), f"{config} is missing"
    offenders = [
        location
        for location, body in _blocks(config.read_text())
        if "X-Forwarded-For" in body and not _FORWARDED_HOST.search(body)
    ]
    assert not offenders, (
        f"{config.name}: these location blocks proxy to the app but never send "
        f"X-Forwarded-Host $http_host, so the app cannot recover the port the "
        f"client used and trusts whatever the client sent instead: {offenders}"
    )


# Every way this app gets started. `start.py` calls `uvicorn.run()`, so it says
# so as a keyword argument; everything else is a command line.
UVICORN_LAUNCHERS = [
    (REPO_ROOT / "docker" / "supervisord.mono.conf", "--no-proxy-headers"),
    (REPO_ROOT / "apps" / "agent" / "e2e" / "supervisord-e2e.conf", "--no-proxy-headers"),
    (REPO_ROOT / "run_backend.sh", "--no-proxy-headers"),
    (REPO_ROOT / "Makefile", "--no-proxy-headers"),
    (REPO_ROOT / ".github" / "workflows" / "baseline.yml", "--no-proxy-headers"),
    (REPO_ROOT / "apps" / "backend" / "src" / "app" / "start.py", "proxy_headers=False"),
]

_UVICORN_INVOCATION = re.compile(r"uvicorn(?:\.run\()?\s+?app\.main:app|uvicorn\.run\(")


@pytest.mark.parametrize("path,marker", UVICORN_LAUNCHERS, ids=lambda v: getattr(v, "name", v))
def test_no_launcher_lets_uvicorn_apply_forwarded_headers(path: Path, marker: str):
    """`app.middleware.proxy_headers` owns X-Forwarded-* — uvicorn must not.

    uvicorn's own ProxyHeadersMiddleware overwrites `scope["client"]` with the
    address from X-Forwarded-For before the application is called. That is the
    single fact `core.forwarded` decides trust on, so with it gone
    `request_from_trusted_proxy` returned False for every request that came
    through nginx, and every forwarded value fell back to its default —
    including the `Host` header, whose port nginx has already stripped. The
    visible result was an agent `server_url` that could not name a non-443 port.

    Our middleware does the same rewrite and additionally records the real peer,
    but only gets the chance if uvicorn has not already done it. A launcher that
    forgets the flag silently restores the defect, with nothing failing.
    """
    assert path.is_file(), f"{path} is missing"
    text = path.read_text()
    assert _UVICORN_INVOCATION.search(text), (
        f"{path.name} no longer looks like a uvicorn launcher — update "
        f"UVICORN_LAUNCHERS rather than deleting the check"
    )
    assert marker in text, (
        f"{path.name} starts uvicorn without {marker!r}, so uvicorn applies the "
        f"forwarded headers itself and app.middleware.proxy_headers never sees "
        f"the real socket peer"
    )
