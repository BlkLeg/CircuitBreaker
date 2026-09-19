"""H5: the server and the agent must compute the same policy fingerprint.

The activation gate credits an agent as converged only when the fingerprint it
reports equals the one the server computes for the advertised policy. So the two
implementations agreeing is a security property, not a nicety — and it fails in
both directions:

  * drift that makes them disagree leaves every agent reading as unconverged, so
    every rotation has to be forced, and forcing is the stranding the gate exists
    to prevent;
  * a digest that ignored the mode would let a stale successor from an abandoned
    rotation satisfy the gate for a policy the agent never received, which is the
    defect this whole field was added to close.

Neither language's suite alone can catch that. Each would be checking its own
arithmetic against itself and agreeing with whatever it had become. Both read the
one shared vectors file instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "apps/agent/internal/link/testdata/fingerprint_vectors.json"
GO_SOURCE = ROOT / "apps/agent/internal/link/trust.go"
GO_TEST = ROOT / "apps/agent/internal/link/trust_fingerprint_test.go"

sys.path.insert(0, str(ROOT / "apps/backend/src"))


def _vectors() -> list[dict[str, str]]:
    cases = json.loads(VECTORS.read_text())["cases"]
    assert cases, "the shared vectors are empty; this contract would pass vacuously"
    return cases


def test_the_server_matches_the_shared_vectors() -> None:
    from app.core.tls_policy import policy_fingerprint

    mismatches = []
    for case in _vectors():
        actual = policy_fingerprint(case["mode"], case["pin"])
        if actual != case["fingerprint"]:
            mismatches.append(
                f"{case['name']}: server computed {actual}, shared vector says "
                f"{case['fingerprint']}"
            )
    assert not mismatches, (
        "the server's policy fingerprint no longer matches the vectors the agent is "
        "tested against:\n  " + "\n  ".join(mismatches)
    )


def test_the_agent_reads_the_same_vectors() -> None:
    """The Go half is asserted by `go test ./internal/link`, which cannot run in
    Tier 0. What this tier can guarantee is that the Go suite is pointed at
    *this* file — a second, private copy of the vectors on the agent side would
    let the two drift while both suites stayed green, which is the failure this
    contract exists to prevent."""
    assert GO_TEST.exists(), "the agent's fingerprint test is missing; the contract is one-sided"
    go_test = GO_TEST.read_text()
    assert "testdata/fingerprint_vectors.json" in go_test, (
        "the agent's test no longer reads the shared vectors file, so the two "
        "implementations are free to drift apart with both suites green"
    )
    assert "PolicyFingerprint" in GO_SOURCE.read_text(), (
        "apps/agent/internal/link/trust.go no longer defines PolicyFingerprint"
    )


def test_the_separator_keeps_mode_and_pin_distinct() -> None:
    """`("self", "_signedX")` and `("self_signed", "X")` concatenate to the same
    bytes. A digest that conflated them would let one policy pass as another —
    and the rotated unit is a policy precisely because a pin alone cannot say
    "stop pinning"."""
    from app.core.tls_policy import policy_fingerprint

    assert policy_fingerprint("self", "_signedX") != policy_fingerprint("self_signed", "X")


def test_an_absent_policy_has_a_fingerprint_of_its_own() -> None:
    """"No successor" must not collide with a real policy, and must be stable:
    the server compares an agent's reported value against this exact string when
    no rotation is running."""
    from app.core.tls_policy import policy_fingerprint

    empty = policy_fingerprint(None, None)
    assert empty == policy_fingerprint("", "")
    assert empty != policy_fingerprint("public", "")
