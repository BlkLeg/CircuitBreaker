"""The local agent E2E runner's Go toolchain must match the agent's `go.mod` floor.

`apps/agent/e2e/Dockerfile.localrunner` downloads Go itself (`ARG GO_VERSION`)
because the suite shells out to `go build`. The agent's `go.mod` names the
minimum toolchain with its `go` directive, and the security workflow installs
Go from that file (`go-version-file: apps/agent/go.mod`). A runner left on an
older release than the floor either refuses the module outright or, with
toolchain switching enabled, quietly downloads a different Go than the one the
image claims to pin.

The Dockerfile's own comment said "bump both together", and the 2026-10
govulncheck fix (1.26.8 -> 1.26.10) is where that was nearly missed: only a
repository-wide grep for the old version found the second pin. `make verify`
does not build that image, so nothing local caught it. This test does.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GO_MOD = ROOT / "apps" / "agent" / "go.mod"
LOCALRUNNER = ROOT / "apps" / "agent" / "e2e" / "Dockerfile.localrunner"

_GO_DIRECTIVE = re.compile(r"^go (?P<version>\d+\.\d+(?:\.\d+)?)\s*$", re.MULTILINE)
_GO_ARG = re.compile(r"^ARG GO_VERSION=(?P<version>\S+)\s*$", re.MULTILINE)


def _single(pattern: re.Pattern[str], path: Path) -> str:
    matches = [m.group("version") for m in pattern.finditer(path.read_text())]
    assert len(matches) == 1, (
        f"expected exactly one {pattern.pattern!r} in {path.relative_to(ROOT)}, "
        f"found {matches} — the pin moved or this test's regex is stale"
    )
    return matches[0]


def test_go_mod_names_a_patch_release():
    """Guards the guard: a bare `go 1.26` would make the comparison below meaningless."""
    floor = _single(_GO_DIRECTIVE, GO_MOD)
    assert floor.count(".") == 2, (
        f"apps/agent/go.mod says `go {floor}`; pin a patch release so the runner and the "
        "security workflow install the same, advisory-clean toolchain"
    )


def test_localrunner_go_version_matches_go_mod():
    floor = _single(_GO_DIRECTIVE, GO_MOD)
    pinned = _single(_GO_ARG, LOCALRUNNER)
    assert pinned == floor, (
        f"apps/agent/go.mod requires go {floor} but Dockerfile.localrunner downloads "
        f"go {pinned}. Move both together: `make e2e-local` builds the agent with the "
        "runner's toolchain, which is the one govulncheck must have cleared."
    )
