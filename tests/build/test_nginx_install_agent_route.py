"""The shipped nginx templates must proxy /install-agent.sh to the backend.

Without an exact-match location for it, the SPA catch-all (`try_files $uri
$uri/ /index.html`) answers the request with index.html and a 200. `curl -f`
sees a success, writes the HTML to disk, and the operator's `sha256sum -c`
fails against the digest the API computed -- which is exactly how this
surfaced in the field.

The header assertions matter as much as the route: agents.py's
/install-command endpoint and main.py's /install-agent.sh route both build
`server_url` from `request.url.scheme` + `netloc`, and uvicorn derives the
scheme from X-Forwarded-Proto. If the two locations forward a different Host
or X-Forwarded-Proto, the served script differs from the one that was hashed
and the digest check fails again -- for a subtler reason.
"""
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_DIR = REPO_ROOT / "deploy" / "nginx"

sys.path.insert(0, str(REPO_ROOT / "deploy" / "helper"))
import cb_helperd  # noqa: E402

TEMPLATE_VARS = {
    "CB_PORT": "8088",
    "server_name": "_",
    "CB_DATA_DIR": "/var/lib/circuitbreaker",
}

TEMPLATES = ["circuitbreaker.conf", "circuitbreaker-tls.conf"]

BACKEND_UPSTREAM = "proxy_pass http://127.0.0.1:8000;"


def render(name: str) -> str:
    return cb_helperd.render_nginx_template(
        (NGINX_DIR / name).read_text(), TEMPLATE_VARS
    )


def location_body(conf: str, header: str) -> str:
    """The brace-balanced body of `location <header> { ... }`."""
    match = re.search(r"location\s+" + re.escape(header) + r"\s*\{", conf)
    if match is None:
        raise AssertionError(f"no `location {header}` block in config")
    depth = 0
    for index in range(match.end() - 1, len(conf)):
        if conf[index] == "{":
            depth += 1
        elif conf[index] == "}":
            depth -= 1
            if depth == 0:
                return conf[match.end() : index]
    raise AssertionError(f"unbalanced braces in `location {header}` block")


@pytest.mark.parametrize("template", TEMPLATES)
def test_install_agent_script_is_proxied_to_the_backend(template):
    body = location_body(render(template), "= /install-agent.sh")
    assert BACKEND_UPSTREAM in body, (
        f"{template}: /install-agent.sh must reach the backend; otherwise the "
        "SPA catch-all serves index.html with a 200 and the operator's "
        "sha256sum check fails on HTML"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_install_agent_script_forwards_the_same_identity_headers_as_the_api(template):
    conf = render(template)
    api = location_body(conf, "/api/")
    script = location_body(conf, "= /install-agent.sh")

    for header in ("Host", "X-Forwarded-Proto"):
        pattern = re.compile(r"^\s*proxy_set_header\s+" + header + r"\s+(\S+);", re.M)
        api_value = pattern.search(api)
        script_value = pattern.search(script)
        assert api_value is not None, f"{template}: /api/ does not set {header}"
        assert script_value is not None, (
            f"{template}: /install-agent.sh does not set {header} -- the script it "
            "renders would then carry a different server_url than the digest the "
            "install-command API computed"
        )
        assert script_value.group(1) == api_value.group(1), (
            f"{template}: /install-agent.sh forwards {header} as "
            f"{script_value.group(1)} but /api/ forwards {api_value.group(1)}"
        )
