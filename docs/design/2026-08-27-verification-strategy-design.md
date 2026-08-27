# Verification Strategy — Local-First, Fleet-Backed — Design

**Date:** 2026-08-27
**Status:** Draft for review
**Scope:** `.github/workflows/*`, `scripts/ci/` (new), `Makefile` verify targets,
`apps/agent/e2e/` harness, and the Proxmox-backed artifact tier (new)
**Decision record:** `docs/adr/0005-verification-tiers-and-platform-support.md`

---

## 1. Problem statement

The pipeline is large — ten workflows, roughly twenty jobs, ~45 minutes of
compute — and it is not where defects are found. Two independent bodies of
evidence say so.

### 1.1 Every escaped bug is in one band

Every open bug issue at time of writing:

| Issue | Failure | Deployment mode | Arch |
|---|---|---|---|
| #104 | PyInstaller omits `proxmoxer.backends`; Proxmox integration dead | native package | any |
| #103 | Update fails after upgrading to v1.0.0-rc.2 | native package | aarch64 |
| #101 | PIL/`_avif` crash loop, `_MEI` accumulation, type mismatch | native package | aarch64 |
| #87 | Backend crashes after migration 0080, "all platforms" | native package | any |
| #81 | Backend crashes silently after successful migrations | native package | aarch64 |

Five for five: **native packaged artifacts, at install or upgrade time,
failing at runtime, disproportionately on arm64.**

The pipeline tests the Docker mono image on x86_64 hosted runners. The
release path does build amd64 + arm64 and does smoke-install the `.deb` on
both — but `artifact-smoke.yml` contains no `systemctl`, no `curl`, no health
probe and no migration run. It asserts that the binary prints a version, that
unit files exist, and that uninstall removes them.

> **CI proves the package installs. Nothing proves the installed thing runs.**

Every escape lives in that band. No file-existence assertion could have caught
one of them. This is the single highest-value gap in the system.

### 1.2 Some breakage is structurally invisible to CI

Found during the 2026-08-27 investigation, in one session:

- `pytest.ini` gained `filterwarnings = error` (REL-19) on `dev`. `e2e.yml`
  runs on tags and a nightly schedule against `main`. `main` has neither that
  setting nor the root `conftest.py`. Four latent defects in the agent E2E
  suite were therefore invisible: an unregistered `e2e` marker (**zero tests
  collected**), two `websockets` deprecations, and a leaked subprocess pipe.
  Merging `dev` to `main` moves the E2E job from "6 of 12 failing" to "0
  collected", and nothing in CI today would say so first.
- `security_scan.sh` runs ESLint, the binary is absent on the runner, and the
  section is `|| true`. A scanner that never ran is reported identically to a
  scanner that found nothing (issue #106).
- The composed E2E journey uploads a diagnostics artifact containing a
  `docker ps` header and no container logs, because the compose stack is torn
  down before collection. The 500 error in that suite is not diagnosable from
  CI output at all.
- `e2e.yml` pins `CB_E2E_SEED` with a comment arguing that a floating value
  means "a green run cannot be used to characterise a red one", then installs
  `pytest pytest-timeout httpx websockets` unpinned. Both websockets
  deprecations entered the suite through that gap, with no commit to point at.

These are not unrelated bugs. They share one shape: **an error path that
converts failure into silence.**

### 1.3 Local and CI are not the same machine

The test that fails in CI passes on the development laptop. Six axes differ:

| | Laptop | CI runner |
|---|---|---|
| OS | Fedora 44 | ubuntu-22.04 |
| Docker | 29.7.2 | older |
| Compose | v5.5.0 | v2.x |
| uid | 1000 (equal to the container's `breaker` user) | 1001 |
| Python | 3.14 | 3.12 |
| pytest config | `dev` | `main` |

The uid difference is load-bearing: `_down()` in the agent E2E harness calls
`shutil.rmtree(_E2E_DATA_DIR, ignore_errors=True)` on a directory written by
the container's uid-1000 user. On the runner, uid 1001 cannot unlink those
files, `ignore_errors=True` hides it, and each test inherits the previous
test's Postgres state — which is precisely what the `assert 4 == 1` discovery
failures show.

**"It passed locally" is currently not evidence.** Any local-first strategy
that does not address this merely relocates the surprise.

---

## 2. Goals and non-goals

### Goals

1. A developer can gate a push on a **complete, trustworthy** verification run
   executed entirely on the LAN, with no GitHub involvement and no network.
2. The band where 100% of defects currently escape — installed artifact,
   started, upgraded, on real distributions — is covered by an automated tier.
3. Every gate has **exactly one definition**, invoked identically by the
   laptop, the fleet, and GitHub Actions.
4. No gate can pass by not running.

### Non-goals

- Replacing GitHub Actions. It remains a second opinion and the system of
  record for release provenance. It stops being where things are *learned*.
- Self-hosted GitHub runners as an end in themselves. They are a possible
  later mechanism, not a goal (explicitly deselected during design).
- 100% coverage targets, or any metric that rewards test volume over escape
  reduction.
- Rewriting the existing test suites. They are largely good; the tiering and
  the harness around them are what is missing.

---

## 3. Principles

Each is stated with the industry practice it is drawn from, so that the
rationale outlives this document.

**P1 — Gates are defined once and called from everywhere.**
Kubernetes keeps gate logic in `hack/*.sh` and `make verify`; its workflows
are thin callers. Envoy's CI entry point is `ci/run_envoy_docker.sh`, run
identically by contributors and by CI. A gate defined in workflow YAML can
only ever run in CI, which makes local verification a reimplementation and
therefore a lie.

**P2 — Fail closed. A missing tool is a failed gate.**
Already correctly implemented for Gitleaks in `security_scan.sh` ("a gate
that 'passes' because the scanner is absent is not a gate"). The rule is
sound; it is applied inconsistently. Extend it to every scanner and every
cleanup step.

**P3 — Test the artifact you ship, in the state you ship it.**
Debian's `autopkgtest` / DEP-8 exists for exactly this: tests run against the
*installed binary package* on a real system, not against the source tree.
openSUSE and Fedora use openQA to drive real installs in VMs. systemd's
`TEST-*` suite boots real images. This is the discipline the artifact-smoke
job approximates and stops short of.

**P4 — Environment sensitivity is a bug, not a variable to clone.**
The uid-1001 cleanup failure is a portability defect. Pinning the runner
image to hide it would preserve the defect and mask the next one. Fix the
harness; do not clone the environment. (This was an explicit design decision;
the pinned-runner-image alternative was considered and rejected.)

**P5 — Declare platform support in tiers, with stated guarantees.**
Rust defines Tier 1 ("guaranteed to work", tested in CI), Tier 2 ("guaranteed
to build"), and Tier 3 (best effort, no guarantee). CircuitBreaker ships six
package formats across two architectures and currently guarantees nothing
explicitly about any of them, while users file arm64 runtime bugs. An
undeclared guarantee is one that gets broken silently.

**P6 — Test the merge result, not the branch.**
The `filterwarnings` divergence is the "not rocket science rule" failure that
bors and GitHub's merge queue were built to prevent: two independently green
branches producing a red merge.

**P7 — The pipeline is a production system and must be observable.**
An empty diagnostics artifact is a monitoring outage. Evidence collection is
part of the gate, not an afterthought appended with `if: always()` and
allowed to collect nothing.

**P8 — Distributed hardware is how portability is actually verified.**
The PostgreSQL buildfarm — community machines continuously building and
testing across OS and architecture combinations — is the canonical model. A
five-machine private fleet is a small buildfarm.

---

## 4. The verification ladder

Four tiers, adapting the small/medium/large test taxonomy from *Software
Engineering at Google* and Kubernetes' unit/integration/e2e split, with a
fourth tier for real-hardware artifact verification.

| Tier | Contents | Runs where | Budget | Gate |
|---|---|---|---|---|
| **T0** static | lint, format, typecheck, repo-policy suites (`tests/build`), suppression manifest | laptop | 90 s | every commit |
| **T1** unit + integration | frontend unit, security gate, and (measured 2026-08-27, see below) backend integration via Testcontainers — present in the T1 script but off by default in the pre-push gate; runs in full via `make verify-full` | laptop | 4 min | **pre-push hook** |
| **T2** composed | agent E2E, browser E2E, mono image smoke | laptop on demand, or fleet | 30 min | pre-merge to `main` |
| **T3** artifact | install · **boot** · exercise · upgrade · rollback, per format/arch/distro | fleet, ephemeral VMs | 20 min | pre-release + nightly |

Entry points (Phase 1 status — only T0 and T1 are extracted; T2/T3 callers
below are the target shape, not yet wired):

```
make verify-fast     # T0                                — the inner loop (measured ~17s)
make verify          # T0 + T1 minus the backend suite    — the pre-push gate (measured 1m46s)
make verify-full     # T0 + T1 in full (+ backend suite)  — on demand / pre-merge (measured 6m43s)
make verify-fleet    # T3                                — pre-release
```

`verify-full` names T1's full form here because that is what Phase 1 needed
it for; when T2's script lands, its pre-merge caller will need a name that
does not collide with this one — an open question for that phase, not this
one.

**T1 is the pre-push gate.** The 4-minute budget is a hard design constraint,
not an aspiration: a gate slower than the developer's patience gets bypassed,
and a bypassed gate is worse than no gate because it produces false
confidence in the branch protection rules that depend on it.

**The backend suite moved out of the default pre-push run for budget
reasons, measured, not guessed.** On 2026-08-27, full T1 with the backend
suite (`CB_VERIFY_BACKEND=shards`) took 6m43s — 68% over the 4-minute budget.
T1 with the backend suite off (`CB_VERIFY_BACKEND=off`) took 1m46s, 2m14s
under budget. `make verify` therefore runs with the backend suite off by
default. This is never a silent gap: `cb::skipped` prints the omission on
every run, so a green `make verify` never looks like it covered more than it
did. The backend suite still runs on every push in CI, and locally on demand
via `make verify-full`. Re-measure before changing this default; the numbers
above are the evidence, not the last word.

### Tier contract

Every tier script:

1. Declares required tooling and **fails closed** if absent (P2).
2. Takes no argument that differs between laptop, fleet and CI.
3. Writes evidence to `artifacts/<tier>/` in a fixed layout.
4. Exits non-zero on any gate failure. `|| true` is forbidden on a gate; a
   genuinely informational step must print an explicit `SKIPPED (reason)`
   marker so that "did not run" is never spelled the same as "found nothing".

---

## 5. Parity: one definition per gate

```
scripts/ci/
  lib/
    common.sh          # logging, require_tool, evidence paths, SKIPPED marker
  tier0-static.sh
  tier1-unit.sh
  tier2-composed.sh
  tier3-artifact.sh    # executes INSIDE a fleet VM
  fleet/
    matrix.yaml        # distro × format × arch × PVE template
    provision.sh       # clone template → boot → return address
    dispatch.sh        # push artifact + tier3 script, run, collect, destroy
```

Workflows reduce to thin callers:

```yaml
- name: Tier 1
  run: scripts/ci/tier1-unit.sh
```

This is the Kubernetes/Envoy pattern (P1). It has a second, larger benefit:
the gate becomes reviewable as code, in the diff, with the repo's normal
review rules — rather than as YAML that only executes in an environment no
reviewer can run.

**Migration is mechanical and incremental.** Each job moves one at a time;
the workflow keeps working throughout because a thin caller and an inline
block are indistinguishable from the outside.

---

## 6. The environment-agnostic harness

Five rules, each traceable to a defect found on 2026-08-27.

**R1 — No cleanup may silently fail.**
`shutil.rmtree(..., ignore_errors=True)` is replaced by a deletion that
cannot be defeated by file ownership — remove the tree from inside a
throwaway privileged container, which runs as root regardless of host uid —
and that raises on failure. *Fixes the uid-1001 state leak; addresses the
`assert 4 == 1` and `assert 2 == 1` discovery failures.*

**R2 — No unpinned test dependency.**
`e2e.yml` installs four packages unpinned. Replace with a checked-in
constraints file used by laptop, fleet and CI. *A test dependency that
floats makes the pinned `CB_E2E_SEED` pointless — reproducibility is a
property of the whole environment or of none of it.*

**R3 — No uid, path or version assumption in a harness.**
Where a harness must know the runtime uid, it reads it; it does not assume
it. *This is P4 applied: the fix belongs in the harness, not in a cloned
image.*

**R4 — No scanner may pass by being absent.**
Every scanner section either gates (fails closed) or prints an explicit
`SKIPPED (reason)`. *Issue #106.*

**R5 — Configuration that changes test semantics is branch-invariant.**
`pytest.ini`, marker registrations and warning filters must be identical on
`dev` and `main`, enforced by a repo-policy test in `tests/build/`. Combined
with P6's merge queue, this closes the class rather than the instance.

---

## 7. Tier 3 — the fleet

### 7.1 Model

The lifecycle is Molecule's (create → converge → verify → destroy), and the
assertion contract is autopkgtest's (test the installed package as installed).

```
for each row in matrix.yaml:
    provision   clone PVE template → ephemeral VM → wait for SSH
    install     copy candidate artifact → install via native package manager
    boot        start the service; wait for /livez, then /readyz
    exercise    run migrations; hit health + a real API path; run `cb` CLI parity checks
    upgrade     install N-1 first, upgrade to N, assert data + schema survived
    rollback    execute the documented rollback; assert the service returns
    collect     journalctl, migration logs, /data listing  → artifacts/tier3/<row>/
    destroy     always, even on failure — AFTER collection
```

Ephemeral clones rather than snapshot-reset persistent VMs: an install test on
a host with residue is not an install test, and template cloning makes that
guarantee structural rather than procedural.

### 7.2 Matrix

`matrix.yaml` is the single source of truth for what is claimed to work, and
feeds both the tier and the support-tier table in §8.

Each row names where it executes, because arm64 rows run on GitHub's native
aarch64 runners rather than on the x86_64 fleet (§8.2):

```yaml
- {distro: debian-12,   format: deb,         arch: amd64, runner: pve/9001,        tier: 1}
- {distro: fedora-40,   format: rpm,         arch: amd64, runner: pve/9002,        tier: 1}
- {distro: ubuntu-22.04, format: deb,        arch: arm64, runner: gha/ubuntu-22.04-arm, tier: 2}
- {distro: ubuntu-22.04, format: deb,        arch: arm64, runner: local/qemu-arm64, tier: 2}
- {distro: alpine-3.20, format: apk,         arch: amd64, runner: pve/9005,        tier: 3}
- {distro: arch,        format: pkg.tar.zst, arch: amd64, runner: pve/9006,        tier: 3}
- {distro: debian-12,   format: AppImage,    arch: amd64, runner: pve/9001,        tier: 3}
- {distro: debian-12,   format: tarball,     arch: amd64, runner: pve/9001,        tier: 3}
```

The `runner` field is the only thing that varies by execution site;
`tier3-artifact.sh` is identical across all of them (P1).

### 7.3 Evidence

Collection happens **before** destroy, and the tier fails if the evidence
directory is empty (P7). This is a direct response to the composed-E2E
diagnostics artifact that contained a `docker ps` header and nothing else.

### 7.4 Multi-host agent and Proxmox

The fourth selected scope item. Two PVE hosts carry agent VMs on separate
VLANs; the tier asserts LAN discovery, per-agent isolation, and partition
behaviour against real networking rather than a Docker bridge. The Proxmox
integration is exercised against a real PVE API — which also gives #104 a
regression test, since `proxmoxer.backends` is only missing in the *native
packaged* build and only fails when something actually calls it.

This is the most complex slice and is sequenced last (§11).

---

## 8. Platform support tiers, and the arm64 problem

### 8.1 Declared tiers

Adopting Rust's model (P5), published in the docs and enforced by §7's matrix:

| Tier | Guarantee | Formats | Verified on | Gate |
|---|---|---|---|---|
| **1** | Guaranteed to install, boot, upgrade and roll back | deb/rpm amd64 | PVE clones | blocks release |
| **2** | Guaranteed to install and boot | deb/rpm arm64 | `ubuntu-22.04-arm` (native aarch64) | blocks release |
| **3** | Guaranteed to build; installation best-effort | apk, AppImage, tarball, pkg.tar.zst | PVE clones | reported, does not block |

Three of five escaped bugs are arm64 and the Raspberry Pi 5 is evidently a
real deployment target, so arm64 cannot be Tier 3. It is not promoted to
Tier 1 because upgrade and rollback are exercised on the fleet, which is
x86_64 — see §8.2 for how the Tier 2 guarantee is met without arm hardware,
and for what is knowingly left uncovered.

### 8.2 Covering arm64 without buying hardware

There is no arm64 hardware in the fleet and none is being acquired. That
constraint turns out to bind far less than it first appears, because the
project already has native aarch64 CI and is not using it for this.

**`build.yml` and `artifact-smoke.yml` already run on `ubuntu-22.04-arm`** —
GitHub's native aarch64 runners, free for public repositories, which this one
is. arm64 packages are already built and installed on real aarch64 silicon
today. What that job does not do is *start* what it installed. The arm64 gap
is therefore not an absence of hardware; it is the same boot-and-exercise gap
as amd64, on a runner that already exists.

The strategy is four layers, cheapest and highest-yield first.

**L1 — Catch the arch-independent bugs on x86, where they are cheapest.**
Not every bug filed against arm64 is an arm64 bug. #104 (`proxmoxer.backends`
missing from the PyInstaller bundle) is a hidden-import defect with no
architecture component at all, and is caught deterministically by a bundle
completeness assertion — enumerate the dynamic imports the app performs,
assert each resolves inside the frozen bundle — which runs anywhere in
seconds. #87 is explicitly "all platforms". Parts of #101 (`environment_id`
type mismatch, `DB_POOL_SIZE` naming) are plain logic and configuration
defects. **Two of the five open issues, and part of a third, need no arm64 at
all** — they need the boot-and-exercise tier that does not yet exist.

**L2 — Native aarch64 boot-and-exercise on GitHub's arm runners.**
Extend the existing `ubuntu-22.04-arm` job from "installs and reports a
version" to the full §7.1 contract: start the service, run migrations, probe
`/livez` and `/readyz`, exercise the CLI, assert no restart loop. This is real
aarch64 execution on real silicon and costs nothing. It is what makes the
Tier 2 guarantee ("guaranteed to install and boot") honest rather than
aspirational, and it would plausibly have caught #81 and the `PIL/_avif`
crash loop in #101, both of which are missing-or-broken shared library
failures rather than timing ones.

**L3 — Emulated aarch64 locally, for the development loop.**
`binfmt_misc` + `qemu-user-static` with `docker buildx` runs the arm64
artifact on the laptop. Lower fidelity than L2 and explicitly not a gate — its
purpose is that a developer debugging an arm64 failure can iterate locally
instead of pushing to see. Because `tier3-artifact.sh` is one script (P1), the
emulated container and the native runner execute the identical contract; only
`matrix.yaml`'s `runner` field differs.

**L4 — Name the residue, and make it loud instead of silent.**
What none of the above reaches: Raspberry Pi 5 specifically — its kernel, its
page-size configuration, its storage — and timing-dependent failures on slow
hardware. `ubuntu-22.04-arm` is aarch64 Linux; it is not a Pi. #103's upgrade
failure and #101's `_MEI` accumulation may be in this residue.

The compensating control is observability, not more testing. Read #81 again:
the backend "crashes **silently**". That word is the actual defect. Surface
that cannot be tested must instead fail loudly — a first-boot self-check that
validates the frozen bundle, the migration state and the runtime environment,
and reports a specific diagnosis to the journal and to `cb doctor`, converts
an untestable failure into a one-line bug report from the user who hits it.
This is the same principle as P2 and R4 applied to runtime rather than to
gates: the enemy throughout this document is not failure, it is silence.

Residual risk is recorded in the risk register rather than closed. If Pi-class
escapes continue after L1–L4 land, the hardware question reopens with evidence
instead of speculation.

**Correction to an earlier draft of this section:** it asserted that the
architecture with the highest escape rate could not be verified without
purchasing hardware, having reasoned from the fleet's architecture without
checking the runner labels the repository already uses. Native aarch64 CI was
already wired into two workflows. The recommendation to acquire a device is
withdrawn.

---

## 9. Supply chain and security posture

The release path is already strong and should be credited: cosign keyless
signing via OIDC, buildx `--provenance` and `--sbom` attestations, syft SBOMs
fetched by pinned checksum, GPG-signed artifacts, and — unusually good — a
governed scanner-suppression manifest (`security-suppressions.json`) whose
validator requires an owner, a reviewer, an expiry and a compensating control
for every suppression, enforced in CI.

Three gaps:

**S1 — Third-party actions are tag-pinned, not SHA-pinned.**
`gitleaks/gitleaks-action@v2`, `aquasecurity/trivy-action@v0.36.0`,
`lycheeverse/lychee-action@v2`, `docker/setup-buildx-action@v3`. A tag is
mutable; the account that owns it can move it. This is the propagation
mechanism of the March 2025 `tj-actions/changed-files` compromise, and it is
OpenSSF Scorecard's `Pinned-Dependencies` check. Pin to full commit SHAs with
the version in a trailing comment, and let Dependabot raise the bumps.

**S2 — Scanners that can pass without running.** P2/R4 above.

**S3 — No periodic posture measurement.** Add OpenSSF Scorecard on the
existing weekly security schedule. It is a measurement, not a gate; the value
is the trend.

The tiering itself is a security control: the band with a 100% escape rate is
the band where a privilege-escalating install bug would also land.

---

## 10. Branch model and config drift

Three changes, smallest first:

1. **Run the same workflows on `dev` and `main`.** `e2e.yml` runs only against
   `main` today, which is why four dev-only defects went unseen.
2. **Enforce branch-invariant test configuration** (R5) with a
   `tests/build/` policy test — the same mechanism the repo already uses for
   the skip register and suppression manifest.
3. **Adopt GitHub's merge queue** so `main` is only ever updated by a commit
   whose *merge result* was tested (P6).

---

## 11. Sequencing

Ordered by escape risk per unit of effort, not by architectural tidiness.

**Phase 0 — Stop the bleeding (already in progress, uncommitted).**
The four `filterwarnings` defects in the agent E2E suite, plus the marker
registration. Without this, `dev` reaching `main` takes E2E to zero collected
tests.

**Phase 1 — Extract T0/T1 and wire the pre-push gate.**
`scripts/ci/tier0-static.sh`, `tier1-unit.sh`, `make verify`, and a
`pre-push` hook. Delivers the developer-facing goal in the smallest
increment, and every later phase reuses the harness.

**Phase 2 — T3 first slice: boot-and-exercise on one Fedora VM.**
Install the rpm, start the service, run migrations, probe `/livez` and
`/readyz`, exercise the CLI. This is the first thing in the project's history
that would have caught #87 or #81. Deliberately sequenced ahead of T2.

**Phase 3 — T3 breadth.** The remaining matrix rows: formats, distros,
upgrade and rollback. Closes #103's class.

**Phase 4 — T2 extraction and harness hardening.** R1–R3, the composed
journey's `--no-deps` fix and its diagnostics collection.

**Phase 5 — Branch model and supply chain.** §9 and §10.

**Phase 6 — Multi-host agent and Proxmox.** §7.4.

Each phase is independently valuable and independently shippable. There is no
point at which the repo is mid-migration and worse off than it started.

**This document is a programme, not a single implementation plan.** Each phase
is scoped to be planned and executed on its own, against this design as the
shared reference. Phase 0 is already in progress; Phase 1 is the first that
needs a written plan.

---

## 12. Success criteria

Measured, not asserted:

| Metric | Today | Target |
|---|---|---|
| Escape rate in the install/boot band | 5 of 5 open bugs | 0 new escapes |
| CI surprises (CI red where `make verify` was green) | unmeasured, known >0 | → 0 |
| `make verify` p95 duration | measured 2026-08-27: 1m46s as shipped (backend suite off); 6m43s if the backend suite is included (`make verify-full`) | < 5 min |
| Gates that can pass without running | ≥ 2 (ESLint, rmtree) | 0 |
| Package formats with a boot assertion | 0 of 6 | 6 of 6 |
| Architectures with a boot assertion | 0 of 2 | 2 of 2 |

The first row is the only one that matters. The rest are leading indicators.

---

## 13. Open questions

1. ~~**arm64 fidelity.**~~ **Resolved 2026-08-27:** no arm hardware will be
   acquired. §8.2 meets the Tier 2 guarantee on GitHub's existing native
   `ubuntu-22.04-arm` runners, which the repository already uses for building
   and smoke-installing, and records the Pi-specific residue as accepted risk
   with a loud-failure compensating control. Reopens only if Pi-class escapes
   continue after L1–L4 land.
2. **PVE API credentials for the harness.** A dedicated PVE role and token
   with clone/destroy rights, scoped to a template pool, stored via the
   existing vault mechanism rather than in a developer's shell profile.
3. **Fleet availability during offline work.** The pre-push gate (T0/T1) is
   fully offline by design. T3 needs the LAN. Acceptable, but should be
   stated in the developer docs so nobody believes T3 ran when it did not —
   which is the same failure mode as R4.
4. **T2 placement.** Runnable on the laptop but 30 minutes. Should it default
   to the fleet once the fleet exists?

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| The pre-push gate becomes slow and gets bypassed | 4-minute budget is a hard constraint; T1 contents are negotiable to defend it |
| Fleet becomes a second system to maintain | Ephemeral clones from templates; no persistent state to drift; the tier scripts are the same ones CI runs |
| Script extraction stalls half-done | Phase 1 migrates T0/T1 only; a thin caller and an inline block are interchangeable, so partial migration is a valid resting state |
| The design is written and not built | Phases are ordered so Phase 1 alone delivers the stated developer goal |
| Pi-specific arm64 failures survive L1–L4 (§8.2) | Accepted. Compensating control is the first-boot self-check and `cb doctor` diagnosis, converting a silent crash into a reportable one; reopens the hardware question with evidence |

---

## 15. References

- Debian DEP-8 / `autopkgtest` — testing binary packages as installed
- Rust platform support tiers — declared guarantees per target
- PostgreSQL buildfarm — distributed multi-OS/arch verification
- Kubernetes `hack/` + `make verify`; Envoy `ci/run_envoy_docker.sh` — one
  definition per gate
- Ansible Molecule — create/converge/verify/destroy across a distro matrix
- systemd `TEST-*` / mkosi; openSUSE and Fedora openQA — booting real images
- *Software Engineering at Google* — small/medium/large test taxonomy
- OpenSSF Scorecard — `Pinned-Dependencies`; SLSA provenance levels
- bors / GitHub merge queue — always test the merge result
