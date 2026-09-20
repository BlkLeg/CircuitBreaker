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
        # "pbs" is excluded from the default: build_binary raises SystemExit for
        # it today, so including it here means every default invocation runs
        # two full PyInstaller builds and then dies before printing anything.
        # Pass --configurations onefile onedir pbs explicitly once pbs builds.
        default=["onefile", "onedir"],
        choices=["onefile", "onedir", "pbs"],
        help="Configurations to measure (default: onefile onedir; pbs is excluded "
        "because build_binary currently raises SystemExit for it)",
    )
    args = parser.parse_args(argv)

    results: list[Measurement] = []
    for configuration in args.configurations:
        result = measure(configuration, args.version)
        results.append(result)
        # Emitted as each measurement completes, not only at the end, so a
        # later configuration's failure cannot discard earlier results.
        print(json.dumps(asdict(result), indent=2))

    print(json.dumps([asdict(result) for result in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
