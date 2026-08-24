"""SRV-03: every probe whose failure restarts something must poll /livez.

A HEALTHCHECK failure is a restart decision. /health and /readyz both fold
Postgres and Redis into their verdict, so wiring either one to a restart turns
a dependency blip into a restart storm against a process that is working fine.
/livez answers the only question a restart should turn on: can this process
serve at all?

These are file-shape tests on purpose. The application side is covered by
apps/backend/tests/test_health_endpoints.py, but nothing there can catch a
Dockerfile, a compose override or an nginx server block pointing the probe
somewhere else — which is exactly how these three drifted apart before.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVEZ = "/api/v1/livez"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _healthcheck_directive(dockerfile: str) -> str:
    """The HEALTHCHECK instruction, with backslash line-continuations joined."""
    text = _read(dockerfile)
    joined = re.sub(r"\\\n\s*", " ", text)
    matches = [line for line in joined.splitlines() if line.startswith("HEALTHCHECK")]
    assert len(matches) == 1, (
        f"{dockerfile}: expected exactly one HEALTHCHECK, got {len(matches)}"
    )
    return matches[0]


def _dockerfiles_with_api_healthchecks() -> list[str]:
    """Every Dockerfile in the tree whose HEALTHCHECK probes the API.

    Discovered rather than listed: docker/backend.Dockerfile was missed by a
    sweep that only looked at paths beginning with "Dockerfile", and so stayed
    on /api/v1/health long after the others had moved off it.
    """
    found = []
    for path in sorted(ROOT.rglob("*Dockerfile*")):
        if path.is_dir() or any(
            part in {"node_modules", ".git", "site"} for part in path.parts
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "HEALTHCHECK" in text and "/api/" in text:
            found.append(str(path.relative_to(ROOT)))
    assert found, "no Dockerfile with an API HEALTHCHECK found - discovery is broken"
    return found


@pytest.mark.parametrize("dockerfile", _dockerfiles_with_api_healthchecks())
def test_image_healthchecks_probe_livez(dockerfile: str):
    directive = _healthcheck_directive(dockerfile)
    assert LIVEZ in directive, f"{dockerfile} HEALTHCHECK must poll {LIVEZ}"
    assert "/api/v1/health" not in directive, (
        f"{dockerfile} HEALTHCHECK must not poll /api/v1/health: a Postgres or Redis "
        "outage would restart a healthy container"
    )
    assert "/api/v1/readyz" not in directive, (
        f"{dockerfile} HEALTHCHECK must not poll /api/v1/readyz for the same reason"
    )


def test_systemd_healthcheck_script_probes_livez():
    """deploy/scripts/healthcheck.sh restarts the backend unit on failure."""
    script = _read("deploy/scripts/healthcheck.sh")
    assert LIVEZ in script, f"healthcheck.sh must poll {LIVEZ}"
    assert "/api/v1/health" not in script


def _probe_url(directive_or_test: str) -> str:
    match = re.search(r"https?://[^\s'\"|]+", directive_or_test)
    assert match, f"no probe URL found in: {directive_or_test}"
    return match.group(0)


def test_compose_healthcheck_matches_the_mono_image():
    """A compose healthcheck overrides the image's, silently undoing it if it drifts."""
    compose = yaml.safe_load(_read("docker-compose.yml"))
    test = compose["services"]["circuitbreaker"]["healthcheck"]["test"]
    joined = " ".join(test)
    assert LIVEZ in joined, f"docker-compose.yml healthcheck must poll {LIVEZ}"
    assert "/api/v1/health" not in joined

    image_url = _probe_url(_healthcheck_directive("Dockerfile.mono"))
    compose_url = _probe_url(joined)
    assert compose_url.endswith(LIVEZ) and image_url.endswith(LIVEZ)
    # Same port, or the compose override is probing something the image is not.
    assert (
        compose_url.split("://", 1)[1].split("/", 1)[0].rsplit(":", 1)[-1]
        == image_url.split("://", 1)[1].split("/", 1)[0].rsplit(":", 1)[-1]
    ), f"compose probes {compose_url} but the image probes {image_url}"


def _plain_http_server_block(conf: str) -> str:
    """The `listen 8080` server block of docker/nginx.mono.conf."""
    blocks = []
    for match in re.finditer(r"\n    server \{", conf):
        start = match.end() - 1
        depth, index = 0, start
        while index < len(conf):
            if conf[index] == "{":
                depth += 1
            elif conf[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        blocks.append(conf[start : index + 1])
    plain = [b for b in blocks if re.search(r"^\s*listen 8080;", b, re.MULTILINE)]
    assert len(plain) == 1, (
        f"expected one `listen 8080` server block, found {len(plain)}"
    )
    return plain[0]


def _matches_location(directive: str, path: str) -> bool:
    """Does one nginx `location` directive match `path`?"""
    exact = re.match(r"location\s+=\s+(\S+)\s*\{", directive)
    if exact:
        return exact.group(1) == path
    regex = re.match(r"location\s+~\*?\s+(.+?)\s*\{", directive)
    if regex:
        return re.search(regex.group(1), path) is not None
    prefix = re.match(r"location\s+(?:\^~\s+)?(\S+)\s*\{", directive)
    return bool(prefix and path.startswith(prefix.group(1)))


def test_mono_nginx_routes_the_probe_it_is_asked_for():
    """The :8080 block 301-redirects anything it does not explicitly proxy.

    Without a matching location the HEALTHCHECK never reaches the backend at
    all — it either always passes (a bare `curl -f` treats 301 as success) or
    always fails (a body match against nginx's redirect page). Both are worse
    than no healthcheck.
    """
    block = _plain_http_server_block(_read("docker/nginx.mono.conf"))
    locations = re.findall(r"location\s+[^\n{]*\{", block)
    proxied = [d for d in locations if not re.match(r"location\s+/\s*\{", d)]
    assert any(_matches_location(d, LIVEZ) for d in proxied), (
        f"no location in the `listen 8080` block matches {LIVEZ}; the HEALTHCHECK in "
        f"Dockerfile.mono would fall through to `return 301`. Locations: {proxied}"
    )
