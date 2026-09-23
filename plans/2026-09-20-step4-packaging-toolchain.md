# Step 4 — Packaging Toolchain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire PyInstaller `--onefile`, eliminating the `_MEI` extraction tax paid by seven processes on every start, and — if the measurements allow — the hidden-import failure class that produced v0.4.2.

**Architecture:** Measure first, decide by a rule fixed in advance, then implement exactly one of two adoption paths. Task 1 benchmarks three configurations on both architectures. Task 2 applies the decision rule. Tasks 3a and 3b are the two adoption paths — **exactly one of them is executed**, chosen by Task 2's output.

**Tech Stack:** PyInstaller, python-build-standalone, Python 3.12, nfpm, systemd, Bash.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §19, §20, §21.

**Depends on:** Step 1. `--selftest` is what protects this change — whichever path is adopted, the build refuses to stage a binary that cannot import the application.

## Global Constraints

- Python 3.12. snake_case, full type annotations — mypy runs with `disallow_untyped_defs`. Docstrings on classes and public functions.
- **No placeholders.**
- **Backward compatible.** A half-updated deployment must still work. The bundle layout changes, so `install.sh` must handle both the old single-file layout and the new one during the release in which the change lands.
- **Air-gap is first-class.** The new build path must not add a runtime download. If python-build-standalone is adopted, its interpreter is fetched at **build** time and vendored into the bundle, never fetched on the installing host.
- Never hardcode credentials, tokens, signing material or vault keys.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan touches `scripts/`, `nfpm.yaml`, `deploy/systemd/` and `install.sh`. It does not touch `apps/backend/src/app`, so `make verify` is the gate — **but** it changes how the application is packaged, so the covering suite is a real build plus `--selftest`, and the installer journey once Step 7 exists. Quoting `make verify` for this change would be exactly the error CLAUDE.md rule 1 names.
- **Do not lower the coverage gate.**

## Background an implementer needs

`scripts/build_native_release.py::build_binary` runs PyInstaller with `--onefile`, producing a ~98 MiB single executable. At every process start that executable extracts itself into a temporary directory.

Three consequences, all visible in the tree:

1. `specs/1.0.0/slices/agt-3-pyinstaller-containment.md` (AGT-11, issue #101) exists solely to bound `_MEI*` accumulation — ownership markers, disk budgets, symlink-attack handling, crash-loop cleanup.
2. `deploy/systemd/circuitbreaker-backend.service` and `deploy/systemd/circuitbreaker-worker@.service` both carry `ExecStartPre=/bin/sh -c 'mkdir -p "/var/lib/circuitbreaker/run/%N" && rm -rf "/var/lib/circuitbreaker/run/%N"/_MEI*'`.
3. The backend and every worker instance run the same binary as separate processes, so the extraction cost is paid seven times over, on every start and every restart.

Separately, PyInstaller's static import graph drops modules named only by strings. Three collectors in `build_native_release.py` exist to recover from that, each written after a shipped failure. `--onedir` does **not** fix this; python-build-standalone does, by having no import graph to analyse.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/bench_packaging.py` | Builds each configuration, measures it, writes a comparable report. |
| `docs/evidence/2026-09-20-packaging-benchmark.md` | The measurements, committed as evidence. |
| `scripts/build_native_release.py` | The adopted build path. |
| `nfpm.yaml`, `packaging/*` | File lists for the new layout (both paths). |
| `deploy/systemd/*.service` | `_MEI` cleanup removed (both paths). |
| `install.sh`, `deploy/setup.sh` | Binary staging for the new layout (both paths). |

---

### Task 1: Benchmark the three configurations

**Files:**
- Create: `scripts/bench_packaging.py`
- Create: `docs/evidence/2026-09-20-packaging-benchmark.md`

**Interfaces:**
- Produces: `docs/evidence/2026-09-20-packaging-benchmark.md`, a table Task 2 reads.

- [ ] **Step 1: Write the benchmark script**

Create `scripts/bench_packaging.py`:

```python
#!/usr/bin/env python3
"""Measure the packaging configurations this project is choosing between.

The decision rule in the design spec is fixed in advance precisely so this
script's output decides it, rather than the output being read in whatever way
suits the effort already spent. So this prints numbers and nothing else: no
recommendation, no verdict.

Three configurations:
  onefile  — today. One executable that extracts itself at every process start.
  onedir   — PyInstaller emitting a directory. No extraction; same import graph.
  pbs      — python-build-standalone plus a real site-packages. No extraction
             and no import graph, so the hidden-import failure class disappears.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Measurement:
    """One configuration's measured cost.

    Attributes:
        configuration: One of "onefile", "onedir", "pbs".
        build_seconds: Wall-clock for the packaging step alone.
        compressed_bytes: Size of the .tar.gz a user downloads.
        installed_bytes: Size of the unpacked tree on disk.
        cold_selftest_seconds: First --selftest run, cold page cache.
        warm_selftest_seconds: Median of five subsequent runs.
    """

    configuration: str
    build_seconds: float
    compressed_bytes: int
    installed_bytes: int
    cold_selftest_seconds: float
    warm_selftest_seconds: float


def _tree_size(path: Path) -> int:
    """Total bytes of every regular file under path."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _time_selftest(binary: Path, runs: int) -> list[float]:
    """Wall-clock seconds for each --selftest invocation."""
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        completed = subprocess.run(
            [str(binary), "--selftest"], capture_output=True, text=True, check=False
        )
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            raise SystemExit(
                f"--selftest failed for {binary}: "
                f"{(completed.stdout + completed.stderr).strip()}"
            )
        timings.append(elapsed)
    return timings


def _drop_caches() -> None:
    """Best-effort page-cache drop so 'cold' means something.

    Needs root. Without it the cold number is not comparable across
    configurations and the report says so rather than quietly reporting a warm
    number as cold.
    """
    try:
        subprocess.run(["sync"], check=True)
        Path("/proc/sys/vm/drop_caches").write_text("3\n")
    except (PermissionError, OSError, subprocess.CalledProcessError):
        print(
            "  note: could not drop page cache (needs root); "
            "cold and warm numbers are not distinguishable in this run",
            file=sys.stderr,
        )


def measure(configuration: str, version: str) -> Measurement:
    """Build one configuration and measure it end to end."""
    work = Path(tempfile.mkdtemp(prefix=f"cb-bench-{configuration}-"))
    try:
        started = time.perf_counter()
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "build_native_release.py"),
                "--version",
                version,
                "--packaging",
                configuration,
                "--output-dir",
                str(work),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        build_seconds = time.perf_counter() - started

        archives = sorted(work.glob("*.tar.gz"))
        if not archives:
            raise SystemExit(f"no tarball produced for {configuration} in {work}")
        archive = archives[0]

        unpacked = work / "unpacked"
        unpacked.mkdir()
        with tarfile.open(archive) as handle:
            handle.extractall(unpacked, filter="data")
        # The archive is FLAT: `circuit-breaker`, `deploy/`, `share/` and
        # `manifest.json` all sit at the root, with no bundle subdirectory and
        # no `bin/`. Verified against a real artifact with `tar -tzf`.
        binary = unpacked / "circuit-breaker"
        if not binary.exists():
            raise SystemExit(f"no circuit-breaker at the bundle root of {archive}")

        _drop_caches()
        cold = _time_selftest(binary, runs=1)[0]
        warm_runs = sorted(_time_selftest(binary, runs=5))

        return Measurement(
            configuration=configuration,
            build_seconds=round(build_seconds, 1),
            compressed_bytes=archive.stat().st_size,
            installed_bytes=_tree_size(unpacked),
            cold_selftest_seconds=round(cold, 3),
            warm_selftest_seconds=round(warm_runs[len(warm_runs) // 2], 3),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    """Measure every requested configuration and print a JSON array."""
    parser = argparse.ArgumentParser(description="Benchmark packaging configurations.")
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--configurations",
        nargs="+",
        default=["onefile", "onedir", "pbs"],
        choices=["onefile", "onedir", "pbs"],
    )
    args = parser.parse_args(argv)

    results = [measure(configuration, args.version) for configuration in args.configurations]
    print(json.dumps([asdict(result) for result in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add the `--packaging` and `--output-dir` flags to the build script**

`bench_packaging.py` calls `build_native_release.py --packaging <mode> --output-dir <path>`.
**Neither flag exists yet** — `parse_args()` today declares only `--version` and `--clean`
(verified against the tree). Both must be added, and `--output-dir` is not optional
decoration: without it every configuration writes to `dist/native/` and the benchmark
measures whichever build ran last.

`--output-dir` takes a path, defaults to the current `dist/native/` location so existing
callers are unaffected, and replaces that directory everywhere the script writes an
archive, a package or a manifest. Thread it through `create_archive`, `write_metadata`
and `create_linux_packages`.

`--packaging`: Add it to `parse_args()` with choices `onefile`, `onedir`, `pbs`, defaulting to `onefile` so nothing changes for existing callers, and thread it into `build_binary`. `onedir` and `pbs` are implemented in Tasks 3a/3b respectively — until the corresponding task runs, the unimplemented mode must **fail loudly**:

```python
    if packaging_mode == "pbs":
        raise SystemExit(
            "--packaging pbs is not implemented yet. It lands with Task 3b of "
            "plans/2026-09-20-step4-packaging-toolchain.md, which is executed "
            "only if the benchmark's decision rule selects it."
        )
```

A `SystemExit` with an explanation is not a placeholder: it is the honest behaviour of a flag whose implementation is gated on a measurement that has not happened.

- [ ] **Step 3: Implement `onedir` enough to benchmark it**

Task 3a implements `onedir` for production. To benchmark it now, `build_binary` needs the PyInstaller invocation to swap `--onefile` for `--onedir` and `stage_bundle` to copy the resulting directory. Implement that much here — it is the same code Task 3a would write, and writing it twice would be worse.

In `build_binary`, replace the hardcoded `"--onefile",` with:

```python
            "--onedir" if packaging_mode == "onedir" else "--onefile",
```

and in the path resolution after the run:

```python
    if packaging_mode == "onedir":
        # PyInstaller emits dist/<name>/<name> plus dist/<name>/_internal/.
        binary_path = dist_dir / binary_name(target_os) / binary_name(target_os)
    else:
        binary_path = dist_dir / binary_name(target_os)
```

- [ ] **Step 4: Run the benchmark on amd64**

```bash
sudo .venv/bin/python scripts/bench_packaging.py \
  --version "$(cat VERSION)" \
  --configurations onefile onedir \
  | tee /tmp/bench-amd64.json
```

`sudo` so the page-cache drop works; without it the script says the cold number is not distinguishable and that caveat must reach the report.

Expected: a JSON array of two measurements. This takes several minutes per configuration.

- [ ] **Step 5: Run the benchmark on arm64**

Run the same command on an arm64 host or runner. If none is available, record that in the report as an unmeasured axis rather than extrapolating — extrapolating is how a decision rule gets rationalised.

- [ ] **Step 6: Write the evidence document**

Create `docs/evidence/2026-09-20-packaging-benchmark.md` with the raw JSON from both architectures, a rendered table, the hardware and date, and an explicit note on whether the page cache was dropped. State the `pbs` row as **not measured** if Task 3b has not been built — the decision rule in Task 2 handles that case.

- [ ] **Step 7: Commit**

```bash
git add scripts/bench_packaging.py scripts/build_native_release.py docs/evidence/2026-09-20-packaging-benchmark.md
git commit -m "feat: benchmark the packaging configurations

Measures build wall-clock, compressed and installed size, and cold/warm
selftest latency for onefile and onedir on both architectures. Prints numbers
and no verdict, because the decision rule is fixed in advance precisely so the
measurement decides it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Apply the decision rule

**This task produces a decision, not code.** Do not skip it and do not reinterpret the rule.

The rule, from the spec §21, fixed before any measurement existed:

> Adopt §20.2 (python-build-standalone) unless it regresses compressed artifact size by more than 40% or build wall-clock by more than 50%; otherwise adopt §20.1 (`--onedir`). Either way, `--onefile` does not survive.

- [ ] **Step 1: Decide whether to measure `pbs` at all**

`pbs` must be built before it can be measured, and building it is Task 3b — most of the work. Two honest routes:

- **Route A (recommended).** Build `pbs` as a throwaway prototype sufficient to produce a tarball and pass `--selftest`, measure it, then apply the rule. If the rule selects `pbs`, harden the prototype into Task 3b. If it selects `onedir`, discard the prototype and execute Task 3a.
- **Route B.** Adopt `onedir` now on the strength of the measured onefile-vs-onedir numbers, and record `pbs` as an unevaluated option with the reason. This is legitimate **only if written down** — an unevaluated option silently dropped is how the AST collector in `build_native_release.py` became permanent.

Pick one and record which, with the reason, in `docs/evidence/2026-09-20-packaging-benchmark.md`.

- [ ] **Step 2: Apply the rule and record the outcome**

Append a "Decision" section to the evidence document stating: the measured percentages, the rule as quoted above, which configuration it selects, and the date. One paragraph.

- [ ] **Step 3: Commit the decision**

```bash
git add docs/evidence/2026-09-20-packaging-benchmark.md
git commit -m "docs: record the packaging decision and the numbers behind it

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Execute exactly one of Task 3a or Task 3b**

Task 3a if the rule selected `onedir`. Task 3b if it selected `pbs`. Do not execute both.

---

### Task 3a: Adopt `--onedir`

**Execute only if Task 2 selected `onedir`.**

**Files:**
- Modify: `scripts/build_native_release.py` — default `packaging_mode` to `onedir`
- Modify: `nfpm.yaml` and `packaging/` file lists
- Modify: `deploy/systemd/circuitbreaker-backend.service`, `deploy/systemd/circuitbreaker-worker@.service`
- Modify: `install.sh` (`stage0_install_bundle`) and `deploy/setup.sh` (`stage6_apply_binary`)
- Modify: `specs/1.0.0/slices/agt-3-pyinstaller-containment.md`
- Create: `tests/build/test_no_runtime_extraction.py` (replaces `tests/build/test_agt11_extraction_dirs.py`)

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_no_runtime_extraction.py`:

```python
"""Nothing may extract itself at process start any more.

PyInstaller --onefile unpacked ~98 MiB into a temporary directory on every
process start. The backend and every circuitbreaker-worker@ instance run the
same binary as separate processes, so that cost was paid seven times over, on
every start and every restart — and containing the debris needed a P0 slice of
its own (AGT-11, issue #101): ownership markers, disk budgets, symlink-attack
handling, crash-loop cleanup.

--onedir removes the extraction entirely. These assertions stop it coming back
by accident, because it comes back by deleting one word.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"
SYSTEMD = REPO_ROOT / "deploy" / "systemd"


def test_the_build_does_not_default_to_onefile() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '"onefile"' not in source.split("choices=")[0] or 'default="onedir"' in source, (
        "build_native_release.py still defaults to --onefile"
    )
    assert 'default="onedir"' in source, (
        "the packaging mode does not default to onedir, so a plain build still "
        "produces a self-extracting binary"
    )


def test_no_unit_cleans_up_extraction_debris() -> None:
    offenders = [
        path.name
        for path in SYSTEMD.glob("*.service")
        if "_MEI" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"these units still clean up _MEI* extraction debris: {offenders}. With "
        "--onedir nothing extracts, so the ExecStartPre that removes it is dead "
        "code that documents a hazard the build no longer has."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_no_runtime_extraction.py -v`

Expected: both FAIL.

- [ ] **Step 3: Default the build to `onedir`**

In `scripts/build_native_release.py::parse_args`, change the `--packaging` default to `"onedir"`.

- [ ] **Step 4: Update the bundle staging**

`stage_bundle()` currently copies one file to the bundle root as `circuit-breaker` (the bundle has no `bin/`; that directory only exists after install.sh stages it into /opt). It must now copy the PyInstaller output **directory** so the bundle contains `bin/circuit-breaker` and `bin/_internal/`. Read `stage_bundle` and make the copy recursive, preserving the executable bit on the launcher.

Verify with:

```bash
.venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
tar -tzf dist/native/circuit-breaker_*_linux_amd64.tar.gz | grep -E '^(circuit-breaker|_internal/)' | head
```

Expected: the launcher and `_internal/` entries appear **at the bundle root**.
The bundle is flat — `circuit-breaker`, `deploy/`, `share/`, `manifest.json` all
sit at the top level, and there is no `bin/` inside the tarball. Keep it that way:
`install.sh:996` copies `${CB_BUNDLE_DIR}/circuit-breaker` into
`/opt/circuitbreaker/bin/`, so the *installed* path is unaffected by this and must
not be changed.

- [ ] **Step 5: Remove the `_MEI` cleanup from both units**

Delete this line from `deploy/systemd/circuitbreaker-backend.service` and `deploy/systemd/circuitbreaker-worker@.service`:

```
ExecStartPre=/bin/sh -c 'mkdir -p "/var/lib/circuitbreaker/run/%N" && rm -rf "/var/lib/circuitbreaker/run/%N"/_MEI*'
```

Keep any `mkdir -p` of the runtime directory that other settings still depend on — read the whole unit before deleting, and if the directory is referenced elsewhere, keep the `mkdir` and drop only the `rm -rf`.

- [ ] **Step 6: Update `nfpm.yaml` and the other packaging recipes**

Every recipe that lists `bin/circuit-breaker` as a single file must now ship the directory. Update `nfpm.yaml`, `PKGBUILD`, and the AppImage recipe in the Makefile. Find them all:

```bash
grep -rn 'bin/circuit-breaker' nfpm.yaml packaging/ PKGBUILD Makefile install.sh deploy/
```

Expected: every hit is reviewed and updated. This is the step most likely to be incomplete — a missed recipe produces a package whose binary cannot find `_internal/`.

- [ ] **Step 7: Update `install.sh` and `deploy/setup.sh`**

`stage0_install_bundle` and `stage6_apply_binary` copy the binary into `/opt/circuitbreaker/bin/`. They must copy the directory. **Backward compatibility:** during the release in which this lands, an upgrade may find a single-file binary already installed. Handle both:

```sh
  # --onedir replaced --onefile in 0.5.0. An upgrade from an earlier release
  # finds a single file here and must replace it with the directory, not copy
  # the directory inside it.
  if [[ -f /opt/circuitbreaker/bin/circuit-breaker ]] && [[ ! -d /opt/circuitbreaker/bin/_internal ]]; then
    rm -f /opt/circuitbreaker/bin/circuit-breaker
  fi
```

- [ ] **Step 8: Run the tests**

Run: `pytest tests/build/test_no_runtime_extraction.py tests/build -q`

Expected: pass. The AGT-11 extraction-directory suite will now fail — it asserts behaviour that no longer exists. Read it, and rewrite it to assert the absence rather than deleting it.

- [ ] **Step 9: Update the AGT-3 slice**

`specs/1.0.0/slices/agt-3-pyinstaller-containment.md` describes containing a hazard the build no longer has. Add a status note at the top recording that `--onedir` removed the extraction in this change, naming the commit, rather than deleting the slice — the requirement ledger references it.

- [ ] **Step 10: Prove it end to end**

```bash
.venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
mkdir -p /tmp/cb-onedir && tar -xzf dist/native/circuit-breaker_*_linux_amd64.tar.gz -C /tmp/cb-onedir
BUNDLE="$(find /tmp/cb-onedir -maxdepth 1 -mindepth 1 -type d | head -1)"
"$BUNDLE/bin/circuit-breaker" --selftest
"$BUNDLE/bin/circuit-breaker" --version
ls /tmp | grep -c '^_MEI' || echo "no _MEI directories created — correct"
```

Expected: `selftest OK`, the version, and no `_MEI` directories.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: package with --onedir instead of --onefile

--onefile extracted ~98 MiB at every process start, and the backend plus every
worker instance runs the same binary as a separate process, so the cost was
paid seven times over on every start and restart. Containing the debris needed
a P0 slice of its own (AGT-11).

--onedir removes the extraction entirely: the ExecStartPre that cleaned up
_MEI* is gone from both units, and a test fails if either comes back. install.sh
handles the single-file → directory transition for upgrades.

The hidden-import hazard is unchanged; --selftest is what guards that.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3b: Adopt python-build-standalone

**Execute only if Task 2 selected `pbs`.**

This path removes everything Task 3a removes, **plus** the hidden-import failure class: there is no static import graph to analyse because the packages are present as packages, so all three collectors in `build_native_release.py` — including the AST parser — delete.

**Files:**
- Modify: `scripts/build_native_release.py`
- Create: `packaging/cb-launcher.sh`
- Modify: `apps/backend/src/app/core/config.py:28`, `apps/backend/src/app/startup/paths.py:57`
- Modify: the same packaging recipes, units and installer paths as Task 3a

- [ ] **Step 1: Pin the interpreter**

Add to `scripts/build_native_release.py` a constant naming the exact python-build-standalone release and its **distributor-published** SHA256, following `scripts/ci/fleet/matrix.yaml`'s written rule: pin the digest the distributor published, never one computed from a local download. Include that rationale as a comment.

- [ ] **Step 2: Vendor the interpreter and site-packages at build time**

Download the pinned interpreter, verify the digest, unpack it into the bundle, and `pip install --target` the backend's `requirements.txt` into a `site-packages` directory beside it. **Build time only** — the air-gap contract forbids the installing host fetching anything.

- [ ] **Step 3: Write the launcher**

Create `packaging/cb-launcher.sh`, a small shim that resolves its own directory, sets `PYTHONHOME` and `PYTHONPATH` to the vendored tree, and `exec`s the vendored interpreter on `app.start` with `"$@"`. It must resolve its directory through `readlink -f "$0"` so a symlink in `/usr/local/bin` works.

- [ ] **Step 4: Replace the `_MEIPASS` branches**

`resolve_app_version` (`app/core/config.py:28`) and `app/startup/paths.py:57` both read `sys._MEIPASS`, which no longer exists. Replace with a resolution that works for the vendored layout — the `VERSION` file beside the launcher — while **keeping** the `_MEIPASS` branch for one release so a half-updated deployment still works.

- [ ] **Step 5: Delete the three collectors**

Remove `_collect_migration_hidden_imports`, `_collect_asgi_target_hidden_imports` and `_collect_dynamic_import_hidden_imports`, and the `hidden_imports` list they feed. Remove the now-dead tests in `tests/build/test_build_script.py` that assert their behaviour, and record the deletion in the commit message — this is the failure class closing.

- [ ] **Step 6: Apply Task 3a Steps 5 through 9**

The `_MEI` cleanup removal, the packaging recipe updates, the installer staging with backward compatibility, and the AGT-3 slice status note are identical for this path. Execute them exactly as written there, then create `tests/build/test_no_runtime_extraction.py` from Task 3a Step 1 with `default="pbs"` in place of `default="onedir"`.

- [ ] **Step 7: Prove it end to end**

Run Task 3a Step 10's commands. In addition, assert the collectors are gone:

```bash
grep -c '_collect_.*_hidden_imports' scripts/build_native_release.py || echo "collectors removed — correct"
```

Expected: `selftest OK`, no `_MEI` directories, and no collectors.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: package with a vendored interpreter instead of PyInstaller

Removes the runtime extraction that AGT-11 exists to contain, and the
hidden-import failure class with it: there is no static import graph to analyse
because the packages are present as packages. All three collectors delete,
including the AST parser that read app.main back out of a uvicorn.run string
after v0.4.2 shipped without it.

Interpreter pinned to a distributor-published digest, vendored at build time —
the installing host downloads nothing, per the air-gap contract.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `docs/evidence/2026-09-20-packaging-benchmark.md` contains measurements for both architectures, or names the unmeasured axis.
- [ ] The decision section quotes the rule, the percentages, and the selected configuration.
- [ ] Exactly one of Task 3a / Task 3b was executed.
- [ ] A real build produces a tarball whose binary passes `--selftest`.
- [ ] No `_MEI` directory is created by running the binary.
- [ ] No systemd unit references `_MEI`.
- [ ] `pytest tests/build -q`, `make lint`, `make verify` pass.
- [ ] Every packaging recipe found by `grep -rn 'bin/circuit-breaker'` was reviewed.

## What this plan does NOT cover

`make verify` does not build a package, install one, or boot one. The covering evidence for this change is: a real `build_native_release.py` run, `--selftest` on the produced bundle, the `artifact-smoke` jobs from Steps 2 and 3 against a candidate, and — once it exists — the installer journey from Step 7. **A packaging change reported on the strength of `make verify` is the exact error CLAUDE.md rule 1 names.** The AppImage and `pkg.tar.zst` recipes have no automated install coverage at any tier; if a recipe update breaks one, nothing here will catch it, which is recorded in the design's §27 coverage matrix.
