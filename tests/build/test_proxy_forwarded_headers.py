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
