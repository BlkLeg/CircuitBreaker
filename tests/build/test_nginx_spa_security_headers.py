r"""The server-level security headers must survive into the SPA document.

nginx inherits `add_header` from the enclosing level "only if the current level
defines no add_header directives of its own". The rule is all-or-nothing per
level, not per header name, so a single unrelated `add_header Cache-Control ...`
inside a `location` silently discards *every* header the `server` block declared.

Both Docker configs walked into exactly that. `location /` (the SPA catch-all)
and the hashed-asset `location ~* \.(js|css|...)$` each declared their own
Cache-Control, so index.html and the JS bundle -- the two responses a CSP and
X-Frame-Options exist to protect -- shipped with none of Content-Security-Policy,
X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy or
(in the mono config) Strict-Transport-Security. Every proxied `/api/` location
declared no add_header at all and therefore kept the full set, which is why the
gap survived review: spot-checking an API response showed the headers present.

`deploy/nginx/circuitbreaker{,-tls}.conf` already solved this deliberately: one
`map $uri $cb_cache_control` at http level and one server-level
`add_header Cache-Control $cb_cache_control;`, leaving every file-serving
location free of add_header so inheritance survives. This test holds all four
shipped configs to that shape.

The second half guards the trap that makes the first half dangerous. Both Docker
CSPs read `script-src 'self' 'unsafe-inline' 'strict-dynamic'`. Under CSP Level 3
`'strict-dynamic'` makes a browser ignore `'self'`, `'unsafe-inline'` and every
host source in `script-src`, so a policy naming no nonce and no hash allows no
script whatsoever. `apps/frontend/index.html` ships a plain
`<script type="module" src="...">` with no nonce, so the instant the CSP actually
reached the document the app would have served a white page -- the fix above
would have looked like the outage. Restoring header inheritance is only safe
alongside a script-src the SPA can genuinely load under.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

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
    ("docker/nginx.conf", False),
    ("docker/nginx.mono.conf", False),
    ("deploy/nginx/circuitbreaker.conf", True),
    ("deploy/nginx/circuitbreaker-tls.conf", True),
]

CONFIG_IDS = [rel for rel, _ in CONFIGS]

# The headers a browser must receive with index.html itself. HSTS is excluded:
# the plain-HTTP native config deliberately omits it, and nginx will not send it
# over a cleartext connection anyway.
REQUIRED_HEADERS = [
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
]


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


def _blocks(conf: str, keyword: str) -> list[tuple[str, str]]:
    """(header line, body) for every `keyword ... { ... }` block in `conf`.

    A hand-rolled split rather than a real parser, for the same reason
    test_proxy_forwarded_headers.py hand-rolls one: these files are ours and
    conventionally formatted, and the alternative is a dependency CI would have
    to install to run a policy test.
    """
    found = []
    for match in re.finditer(rf"^[ \t]*{keyword}\b([^{{]*)\{{", conf, re.M):
        found.append((match.group(1).strip(), _balanced_body(conf, match.end() - 1)))
    return found


def _top_level_lines(body: str) -> list[str]:
    """Lines of `body` that sit at its own level, i.e. outside any nested block."""
    depth = 0
    lines = []
    for line in body.splitlines():
        if depth == 0:
            lines.append(line)
        depth += line.count("{") - line.count("}")
    return lines


def _spa_server_block(conf: str) -> str:
    """The server block that serves index.html off the filesystem."""
    blocks = [body for _, body in _blocks(conf, "server") if "/index.html" in body]
    assert len(blocks) == 1, "expected exactly one SPA-serving server block; discovery is broken"
    return blocks[0]


@pytest.mark.parametrize("rel,templated", CONFIGS, ids=CONFIG_IDS)
def test_file_serving_locations_declare_no_add_header(rel: str, templated: bool):
    """An add_header here -- any add_header -- drops the whole server-level set."""
    conf = _load(rel, templated)
    offenders = [
        (location, line.strip())
        for location, body in _blocks(conf, "location")
        if "try_files" in body
        for line in body.splitlines()
        if re.match(r"^\s*add_header\s", line)
    ]
    assert not offenders, (
        f"{rel}: these locations serve files off disk and declare their own add_header, "
        f"so nginx stops inheriting the server-level security headers and the SPA "
        f"document ships without them -- move the header up to the server block: {offenders}"
    )


@pytest.mark.parametrize("rel,templated", CONFIGS, ids=CONFIG_IDS)
def test_file_serving_locations_do_not_set_expires(rel: str, templated: bool):
    """`expires` emits its own Cache-Control, which would double up with the map."""
    conf = _load(rel, templated)
    offenders = [
        location
        for location, body in _blocks(conf, "location")
        if "try_files" in body and re.search(r"^\s*expires\s", body, re.M)
    ]
    assert not offenders, (
        f"{rel}: these locations set `expires`, which sends a second Cache-Control "
        f"alongside the server-level one and leaves the two free to disagree -- the "
        f"$cb_cache_control map is the single source of truth: {offenders}"
    )


@pytest.mark.parametrize("rel,templated", CONFIGS, ids=CONFIG_IDS)
def test_cache_control_is_set_once_at_server_level(rel: str, templated: bool):
    """The map is what lets one server-level directive serve both cache policies."""
    conf = _load(rel, templated)
    assert re.search(r"^\s*map\s+\$uri\s+\$cb_cache_control\s*\{", conf, re.M), (
        f"{rel}: needs a `map $uri $cb_cache_control` at http level so a single "
        "server-level add_header can give hashed assets a long max-age and index.html "
        "no-store, without any location declaring an add_header of its own"
    )
    server_level = _top_level_lines(_spa_server_block(conf))
    assert [
        line for line in server_level if re.match(r"^\s*add_header\s+Cache-Control\s", line)
    ], (
        f"{rel}: the SPA-serving server block must declare "
        "`add_header Cache-Control $cb_cache_control` itself; without it the SPA "
        "document is cacheable and a deploy leaves stale asset URLs in the browser"
    )


@pytest.mark.parametrize("rel,templated", CONFIGS, ids=CONFIG_IDS)
def test_spa_server_block_declares_the_security_headers(rel: str, templated: bool):
    conf = _load(rel, templated)
    server_level = "\n".join(_top_level_lines(_spa_server_block(conf)))
    missing = [
        header
        for header in REQUIRED_HEADERS
        if not re.search(rf"^\s*add_header\s+{header}\s", server_level, re.M)
    ]
    assert not missing, (
        f"{rel}: the server block that serves index.html declares no {missing} at its "
        "own level, so no response from it can carry the header"
    )


@pytest.mark.parametrize("rel,templated", CONFIGS, ids=CONFIG_IDS)
def test_script_src_allows_the_spa_bundle_to_load(rel: str, templated: bool):
    """'strict-dynamic' with no nonce and no hash allows no script at all."""
    conf = _load(rel, templated)
    policies = re.findall(
        r"^\s*add_header\s+Content-Security-Policy\s+\"([^\"]+)\"", conf, re.M
    )
    assert policies, f"{rel}: no Content-Security-Policy found"
    for policy in policies:
        script_src = next(
            (
                directive.strip()
                for directive in policy.split(";")
                if directive.strip().startswith("script-src")
            ),
            None,
        )
        assert script_src, f"{rel}: the CSP names no script-src"
        if "'strict-dynamic'" in script_src:
            assert "'nonce-" in script_src or "'sha256-" in script_src, (
                f"{rel}: 'strict-dynamic' makes CSP3 browsers ignore 'self', "
                "'unsafe-inline' and every host source in script-src, so this policy "
                "allows no script at all and index.html's <script type=\"module\"> is "
                "blocked -- the SPA renders a white page. Add a nonce or drop "
                f"'strict-dynamic': {script_src}"
            )
