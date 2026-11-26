"""The agent's `go.mod` directive and the local E2E runner's Go toolchain must name one version.

`apps/agent/go.mod` sets the Go floor, and security.yml runs govulncheck with
`go-version-file: apps/agent/go.mod`, so that directive decides which standard
library the vulnerability scan judges. `apps/agent/e2e/Dockerfile.localrunner`
downloads its own toolchain (`ARG GO_VERSION`) to build the test agent for
`make e2e-local`. Raise the floor for a standard-library fix and leave the
runner behind, and the local E2E keeps building the agent with the vulnerable
toolchain while the scan reports it clean.

`make verify` does not run the agent E2E, so nothing local catches this.
This test does, in the repo-policy suite that Tier 0 always runs.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GO_MOD = ROOT / "apps" / "agent" / "go.mod"
LOCALRUNNER = ROOT / "apps" / "agent" / "e2e" / "Dockerfile.localrunner"

_DIRECTIVE = re.compile(r"^go (?P<version>\d+\.\d+\.\d+)$", re.MULTILINE)
_ARG = re.compile(r"^ARG GO_VERSION=(?P<version>\d+\.\d+\.\d+)$", re.MULTILINE)


def _one(pattern: re.Pattern[str], path: Path) -> str:
    versions = {m.group("version") for m in pattern.finditer(path.read_text())}
    assert len(versions) == 1, (
        f"expected exactly one Go version in {path.relative_to(ROOT)}, found {sorted(versions)} — "
        "either the pin moved or this test's pattern is stale"
    )
    return versions.pop()


def test_localrunner_toolchain_matches_the_agent_go_directive() -> None:
    directive = _one(_DIRECTIVE, GO_MOD)
    runner = _one(_ARG, LOCALRUNNER)
    assert runner == directive, (
        f"apps/agent/go.mod says go {directive} but Dockerfile.localrunner installs Go {runner}. "
        "The E2E runner would build the agent with a different standard library than the one "
        "govulncheck scanned. Move both together."
    )
