"""The shipped CSPs must not permit a third-party font CDN.

The UI used to load its typeface from fonts.googleapis.com, so every deployment
template carried `style-src ... https://fonts.googleapis.com` and
`font-src 'self' https://fonts.gstatic.com` to allow it. The faces are vendored
under `apps/frontend/public/fonts` now, which makes those allowances dead
permission — and dead permission in a CSP is exactly the kind of thing that
quietly becomes live again when someone adds a `<link>` back.

Air-gap is first-class here (`CB_AIRGAP`). A console people self-host so their
infrastructure is not visible to third parties should not disclose every viewer
to one in order to render its own text.

`apps/frontend/e2e/no-third-party-fonts.spec.ts` is the runtime half of this:
it asserts no such request is made. This half asserts none would be permitted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every file in the tree that ships a Content-Security-Policy.
POLICY_FILES = [
    "apps/backend/src/app/middleware/security_headers.py",
    "docker/nginx.conf",
    "docker/nginx.mono.conf",
    "docker/nginx.dev.conf",
    "docker/Caddyfile",
    "deploy/nginx/circuitbreaker.conf",
    "deploy/nginx/circuitbreaker-tls.conf",
]

FONT_CDNS = ("fonts.googleapis.com", "fonts.gstatic.com")


@pytest.mark.parametrize("rel", POLICY_FILES)
def test_no_font_cdn_is_permitted(rel: str) -> None:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    offenders = [cdn for cdn in FONT_CDNS if cdn in text]
    assert not offenders, (
        f"{rel} still permits {offenders}. The UI serves its own fonts from "
        "/fonts; re-adding the allowance means a page load can leave the box "
        "again. If a font genuinely has to come from a CDN, that is a product "
        "decision to take deliberately, not a leftover permission."
    )


@pytest.mark.parametrize("rel", POLICY_FILES)
def test_the_file_actually_declares_a_policy(rel: str) -> None:
    """Guards the test above from passing because the policy vanished."""
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "Content-Security-Policy" in text, f"{rel} declares no CSP at all"
    assert re.search(r"font-src\s+'self'", text), f"{rel} has no font-src 'self'"
    assert "frame-ancestors 'none'" in text, f"{rel} lost frame-ancestors 'none'"


def test_the_vendored_faces_exist() -> None:
    """A CSP of `font-src 'self'` is only correct if we actually ship faces."""
    fonts = REPO_ROOT / "apps/frontend/public/fonts"
    woff2 = sorted(fonts.glob("*.woff2"))
    assert woff2, "no vendored woff2 files — font-src 'self' would render nothing"
    licences = sorted((fonts / "licenses").glob("*OFL.txt"))
    assert licences, "vendored fonts ship without their SIL Open Font Licence text"
    for path in woff2:
        assert path.read_bytes()[:4] == b"wOF2", f"{path.name} is not a woff2 file"
