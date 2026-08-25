"""Every plain-HTTP server block must serve the ACME HTTP-01 webroot itself.

HTTP-01 validation is fetched over port 80 by a CA that holds no credentials and
follows no redirect it is willing to trust. Each of this repo's three nginx configs
answered that request the wrong way before this test existed:

  * docker/nginx.mono.conf and deploy/nginx/circuitbreaker-tls.conf 301'd it to HTTPS
    -- on a first issuance there is no certificate to redirect to, so the CA sees a
    redirect to a broken endpoint and the order fails.
  * deploy/nginx/circuitbreaker.conf answered it from the SPA catch-all, so the CA got
    index.html with a 200 and rejected the key authorization as wrong content.

The `location` vs server-level `return` distinction is the subtle half. nginx runs a
server-level `return` in the server rewrite phase, which is *before* location selection
-- so a bare `return 301` in the server block preempts even a `^~` location. The
redirect has to live inside `location /` for the challenge location to be reachable at
all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "deploy" / "helper"))
import cb_helperd  # noqa: E402

TEMPLATE_VARS = {
    "CB_PORT": "8088",
    "server_name": "_",
    "CB_DATA_DIR": "/var/lib/circuitbreaker",
}

# (repo path, whether cb_render_template must run over it first)
CONFIGS = [
    ("docker/nginx.mono.conf", False),
    ("deploy/nginx/circuitbreaker.conf", True),
    ("deploy/nginx/circuitbreaker-tls.conf", True),
]

ACME_LOCATION = "location ^~ /.well-known/acme-challenge/"


def _load(rel: str, templated: bool) -> str:
    text = (ROOT / rel).read_text(encoding="utf-8")
    return cb_helperd.render_nginx_template(text, TEMPLATE_VARS) if templated else text


def _balanced_body(conf: str, open_brace: int) -> str:
    """The text between `open_brace` and its matching close brace."""
    depth = 0
    for index in range(open_brace, len(conf)):
        if conf[index] == "{":
            depth += 1
        elif conf[index] == "}":
            depth -= 1
            if depth == 0:
                return conf[open_brace + 1 : index]
    raise AssertionError("unbalanced braces")


def _server_blocks(conf: str) -> list[str]:
    return [
        _balanced_body(conf, match.end() - 1)
        for match in re.finditer(r"^\s*server\s*\{", conf, re.M)
    ]


def _is_plain_http(block: str) -> bool:
    listens = re.findall(r"^\s*listen\s+([^;]+);", block, re.M)
    assert listens, "server block with no listen directive"
    return not any("ssl" in listen for listen in listens)


def _plain_http_blocks() -> list[Any]:
    found = []
    for rel, templated in CONFIGS:
        for block in _server_blocks(_load(rel, templated)):
            if _is_plain_http(block):
                found.append(pytest.param(rel, block, id=rel))
    assert len(found) == len(CONFIGS), (
        "expected one plain-HTTP server block per config; discovery is broken"
    )
    return found


PLAIN_HTTP_BLOCKS = _plain_http_blocks()


@pytest.mark.parametrize("rel,block", PLAIN_HTTP_BLOCKS)
def test_plain_http_server_serves_the_challenge_webroot(rel, block):
    assert ACME_LOCATION in block, (
        f"{rel}: the plain-HTTP server must serve /.well-known/acme-challenge/ itself, "
        "or the CA gets a redirect (or the SPA) instead of the key authorization"
    )
    body = _balanced_body(block, block.index("{", block.index(ACME_LOCATION)))

    root = re.search(r"^\s*root\s+(\S+);", body, re.M)
    assert root, f"{rel}: the challenge location needs a `root`"
    assert root.group(1).endswith("/acme-challenge"), (
        f"{rel}: root must be the webroot acme_service.webroot() writes into, so nginx "
        f"appending the request URI lands on the token; got {root.group(1)}"
    )
    assert "alias" not in body, (
        f"{rel}: `alias` drops the matched prefix, but certbot writes the token under "
        "<webroot>/.well-known/acme-challenge/ -- `root` is what appends it back"
    )


@pytest.mark.parametrize("rel,block", PLAIN_HTTP_BLOCKS)
def test_the_https_redirect_cannot_preempt_the_challenge(rel, block):
    """A server-level `return` runs before location selection and would win regardless."""
    depth = 0
    server_level = []
    for line in block.splitlines():
        if depth == 0:
            server_level.append(line)
        depth += line.count("{") - line.count("}")

    assert not [line for line in server_level if re.match(r"^\s*return\s", line)], (
        f"{rel}: the redirect must sit inside `location /`; a server-level `return` is "
        "evaluated in the server rewrite phase, before nginx ever picks a location"
    )
