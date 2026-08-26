"""One answer to 'which version is newer'.

Ordering delegates to `packaging`, which is already a declared dependency and
handles the case a hand-rolled comparator gets wrong: `1.0.0-rc.10` outranks
`1.0.0-rc.4`. The previous update check compared
`v.lstrip("v").split("-")[0]`, which collapsed every 1.0.0 candidate to
`(1, 0, 0)` and so could never report an rc.2 -> rc.4 upgrade.

`is_prerelease` deliberately does NOT use `Version.is_prerelease`. It mirrors
the allowlist rule in `scripts/release_channel.py` so the build-time and
run-time definitions cannot drift: `1.0` and `1.0.0.post1` are stable to
packaging but are not release versions this project publishes, and treating an
unrecognised string as stable is the failure that must never happen.
"""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

# A stable version is exactly MAJOR.MINOR.PATCH with no suffix.
_STABLE_RE = re.compile(r"^\d+\.\d+\.\d+$")


def clean(raw: str) -> str:
    """Strip surrounding whitespace and a leading `v`/`V` tag prefix.

    Public because callers outside this module compare version strings that may
    or may not carry the git tag's `v` — `update_check.select_update` compares
    an operator-supplied APP_VERSION against v-stripped release tags, and any
    asymmetry there yields a silent "no update offered".
    """
    return str(raw).strip().lstrip("vV")


def parse(raw: str) -> Version | None:
    """None for anything unparseable — an unknown version is never 'newer'."""
    try:
        return Version(clean(raw))
    except (InvalidVersion, TypeError):
        return None


def is_prerelease(raw: str) -> bool:
    """True for anything that is not a bare MAJOR.MINOR.PATCH."""
    return not _STABLE_RE.match(clean(raw))


def is_newer(candidate: str, current: str) -> bool:
    """True only when both parse and candidate sorts strictly above current."""
    left, right = parse(candidate), parse(current)
    if left is None or right is None:
        return False
    return left > right
