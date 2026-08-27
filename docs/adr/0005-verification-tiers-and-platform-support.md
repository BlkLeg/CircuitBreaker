# ADR 0005: Verification Tiers and Platform Support

**Status:** Proposed
**Date:** 2026-08-27
**Requirements:** REL-19, RC-08, AGT-01, SEC-18
**Decision owners:** Architecture, release, security
**Design:** `docs/design/2026-08-27-verification-strategy-design.md`

## Context

The pipeline is ten workflows and roughly 45 minutes of compute, and it is not where
defects are found. Every open bug issue — #81, #87, #101, #103, #104 — is one shape: a
native packaged artifact that installs correctly and then fails at runtime, at install or
upgrade time, three of the five on aarch64.

`artifact-smoke.yml` builds amd64 and arm64 and installs the `.deb` on both. It then
asserts that the binary prints a version, that the unit and support files exist, and that
uninstall removes them. It contains no `systemctl`, no health probe and no migration run,
and it covers one of the six formats `make build` produces. CI proves the package
installs; nothing proves the installed thing runs.

A second class of breakage is invisible for a different reason. `pytest.ini` gained
`filterwarnings = error` on `dev`; `e2e.yml` runs on tags and a nightly schedule against
`main`, which carries neither that setting nor the root `conftest.py`. Four defects in the
composed agent journey sat behind that split, one of which collects zero tests. Alongside
it: a security gate that runs ESLint, finds no binary, and reports the absence identically
to a clean scan (#106); a diagnostics artifact holding a `docker ps` header and no logs;
and a workflow that pins `CB_E2E_SEED` for reproducibility while installing its four test
dependencies unpinned. These share one shape — an error path that turns failure into
silence.

Local runs are not currently evidence either: laptop and runner differ in OS, Docker,
Compose, Python, uid and pytest configuration, and the uid difference alone silently
defeats the agent harness's cleanup.

## Decision

Verification is organised into four tiers, each with exactly one definition in
`scripts/ci/`, invoked identically by the laptop, the fleet and GitHub Actions.

- **T0 static** — lint, typecheck, repo-policy suites. Laptop, ~90 s, every commit.
- **T1 unit and integration** — backend integration, frontend unit, security gate.
  Laptop, ~4 min, **the pre-push gate**, fully offline.
- **T2 composed** — agent E2E, browser E2E, mono image. Laptop or fleet, ~30 min,
  pre-merge to `main`.
- **T3 artifact** — install, **boot**, exercise, upgrade, roll back, per format and
  architecture, on ephemeral Proxmox clones. Pre-release and nightly.

The four-minute T1 budget is a hard constraint. A gate slower than the developer's
patience is bypassed, and a bypassed gate is worse than no gate because branch protection
still reports it as satisfied.

Platform support becomes declared tiers with stated guarantees:

- **Tier 1** — guaranteed to install, boot, upgrade and roll back: deb/rpm on amd64.
- **Tier 2** — guaranteed to install and boot: deb/rpm on arm64, verified on
  GitHub's native `ubuntu-22.04-arm` runners.
- **Tier 3** — guaranteed to build only: apk, AppImage, tarball, `pkg.tar.zst`.

Three further rules apply repo-wide: a gate may not pass by not running; test
configuration that changes semantics must be branch-invariant; and evidence collection is
part of the gate, not an optional trailing step.

## Rejected alternatives

**Pinning a runner image to clone CI's environment locally.** It would hide the uid-1001
cleanup defect rather than fix it, and would mask the next portability bug the same way.
Environment sensitivity in a harness is a bug; the harness is fixed instead.

**Self-hosted GitHub runners as the fleet mechanism.** Still requires a push to trigger,
which is the objection being answered, and persistent runners drift — an install test on a
dirty host is not an install test.

**Running the workflow YAML locally with `act`.** Avoids the extraction work, but its gaps
around services, artifacts and nested `docker compose` fall exactly on the agent E2E
suite, the tier most in need of local execution.

**Leaving arm64 at Tier 3.** Honest about today, but the project would knowingly ship a
platform it does not verify while users file bugs against it — and unnecessary, since
native aarch64 runners are already in use here and cost nothing.

**Acquiring arm64 hardware for the fleet.** Considered and withdrawn. The repository is
public and `build.yml` and `artifact-smoke.yml` already run on `ubuntu-22.04-arm`, so
arm64 packages are already built and installed on real aarch64 silicon. The gap is that
the job does not start what it installs, which is the same gap as amd64 and needs no
purchase to close.

## Consequences

GitHub Actions stops being where things are learned and becomes a second opinion running
the same scripts, plus the system of record for release provenance. Its cost stops
governing what gets verified.

Gate logic becomes reviewable code in the diff rather than YAML that only executes where
no reviewer can run it.

The fleet is x86_64, but aarch64 coverage does not depend on it. Two of the five open
issues (#87, #104) and part of a third (#101) have no architecture component and are
caught by the boot-and-exercise tier on any host. The remainder are covered by extending
the existing native `ubuntu-22.04-arm` job from "installs and prints a version" to the
full boot-and-exercise contract, with local qemu emulation available for the development
loop but never as a gate.

What is knowingly not covered is Raspberry Pi 5 specifically — its kernel, page-size
configuration and storage — since `ubuntu-22.04-arm` is aarch64 Linux but is not a Pi.
That residue is accepted rather than closed, with observability as the compensating
control: #81's defect is that the backend crashes *silently*, and a first-boot self-check
that reports a specific diagnosis converts an untestable failure into a one-line bug
report. Throughout this record the enemy is not failure; it is silence.

Third-party actions are tag-pinned rather than SHA-pinned, which is the propagation
mechanism this class of supply-chain compromise uses. Moving to commit SHAs is folded into
the same programme.

## Migration impact

None to shipped behaviour; this changes how the project verifies itself, not what it does.
The work is sequenced so each phase is independently shippable, beginning with the four
`filterwarnings` defects that would otherwise take the agent E2E job to zero collected
tests the moment `dev` reaches `main`.
