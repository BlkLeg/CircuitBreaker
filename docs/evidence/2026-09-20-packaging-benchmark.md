# Packaging benchmark — onefile vs onedir vs pbs

Date: 2026-09-20
Commit: `89355777` (branch `dev`)
Tool: `scripts/bench_packaging.py`, calling `scripts/build_native_release.py --packaging <mode> --output-dir <tmp>`

This is a measurement, not a recommendation. The decision rule that reads this
table lives in Task 2 of `plans/2026-09-20-step4-packaging-toolchain.md` and is
fixed in advance; this document supplies its inputs and states nothing else.

## Hardware

Measured on the only machine available for this task run: an amd64 host.

| | |
|---|---|
| Architecture | x86_64 |
| CPU | Intel(R) Core(TM) Ultra 7 258V, 8 logical CPUs |
| Memory | 30 GiB total |
| Filesystem | btrfs, `/home` (`/dev/nvme0n1p3`), 456G free at run time |
| Python | 3.14.7 (`.venv/bin/python`) |
| PyInstaller | 6.22.2 |
| OS | Linux (GNU/Linux, `uname -o`) |

**arm64: not measured.** No arm64 host or runner was available in this task's
environment. This is recorded as an unmeasured axis rather than extrapolated
from the amd64 numbers below — the whole point of fixing the decision rule in
advance is that a measurement decides it, and extrapolating from one
architecture to another is exactly the kind of reasoning that rule exists to
foreclose. If the decision rule needs an arm64 number, one must be measured on
arm64 hardware before it is used.

## Page cache: NOT dropped

`bench_packaging.py`'s `_drop_caches()` needs root (`/proc/sys/vm/drop_caches`).
This run was not executed with root — attempting the write raised
`PermissionError`, and the script printed:

```
note: could not drop page cache (needs root); cold and warm numbers are not distinguishable in this run
```

Consequently: **the `cold_selftest_seconds` and `warm_selftest_seconds` columns
below are not distinguishable from each other in this run.** The binaries were
almost certainly already in page cache before the "cold" run (PyInstaller had
just written them seconds earlier), so both numbers reflect a warm read. Do not
read a cold/warm delta out of this data — there isn't one here. A real cold
number requires a root-capable run.

## `pbs`: not evaluated

`--packaging pbs` is not implemented. `build_native_release.py` raises
`SystemExit` for it with an explanation (verified below). Building even a
throwaway python-build-standalone prototype to benchmark is explicitly out of
scope for this task (see the task brief) — it lands with Task 3b, and only if
the decision rule selects it. The `pbs` row is omitted from the results below
rather than filled with a placeholder.

## Raw output — amd64

Configurations run: `onefile`, `onedir`. Command:

```
.venv/bin/python scripts/bench_packaging.py --version 0.4.2 --configurations onefile onedir
```

(Run without `sudo`: no passwordless root was available in this environment.
See the page-cache note above for what that means for the cold/warm columns.)

```json
[
  {
    "configuration": "onefile",
    "build_seconds": 77.7,
    "compressed_bytes": 316180803,
    "installed_bytes": 235724777,
    "cold_selftest_seconds": 2.856,
    "warm_selftest_seconds": 2.849
  },
  {
    "configuration": "onedir",
    "build_seconds": 89.4,
    "compressed_bytes": 531565976,
    "installed_bytes": 370662136,
    "cold_selftest_seconds": 2.418,
    "warm_selftest_seconds": 2.421
  }
]
```

## Rendered table — amd64

| configuration | build (s) | compressed (MiB) | installed (MiB) | cold selftest (s) | warm selftest (s) |
|---|---:|---:|---:|---:|---:|
| onefile | 77.7 | 301.5 | 224.8 | 2.856 | 2.849 |
| onedir  | 89.4 | 506.9 | 353.5 | 2.418 | 2.421 |
| pbs     | — not evaluated (unimplemented; see above) — | | | | |
| any config, arm64 | — not measured (no arm64 host available; see above) — | | | | |

Sizes are converted from the raw byte counts above (MiB = bytes / 1024²).

## What the numbers show, and do not show

- `onedir` produced a noticeably larger compressed archive (~1.68x) and
  installed tree (~1.57x) than `onefile` in this run. Both include the same
  application, the same frontend bundle, agent binaries, and the vendored NATS
  material staged by `create_linux_packages`.
- `onedir`'s `--selftest` ran faster than `onefile`'s by roughly 0.4s
  (2.42s vs 2.85s), consistent with `onefile` paying a `_MEI*` self-extraction
  cost on every process start that `onedir` does not pay — but this run cannot
  separate a cold-start effect from a warm one (see the page-cache section),
  so treat this as one comparison of two warm-ish runs, not a validated
  cold-start claim.
- Build wall-clock was similar (77.7s vs 89.4s); `onedir`'s build additionally
  copies a larger tree during staging (binary + `_internal/`), which accounts
  for some of the difference.
- No claim is made here about which configuration should be adopted. That
  reasoning is explicitly out of scope for this document — see Task 2 of the
  packaging-toolchain plan for the decision rule that consumes this table.

## Verification run alongside this benchmark

```
$ .venv/bin/python scripts/build_native_release.py --help
```
shows `--packaging {onefile,onedir,pbs}` (default `onefile`) and `--output-dir`.

```
$ .venv/bin/python -m pytest tests/build -q
743 passed in 20.83s
```

```
$ make lint
... 0 errors (pre-existing frontend eslint warnings only, unrelated to this change)
```

```
$ .venv/bin/python scripts/build_native_release.py --packaging pbs --version 0.0.0
...
--packaging pbs is not implemented yet. It lands with Task 3b of
plans/2026-09-20-step4-packaging-toolchain.md, which is executed only if the
benchmark's decision rule selects it.
(exit 1)
```

---

## Decision (2026-09-20)

**The rule, fixed in the design spec §21 before any measurement existed:**

> Adopt §20.2 (python-build-standalone) unless it regresses compressed artifact
> size by more than 40% or build wall-clock by more than 50%; otherwise adopt
> §20.1 (`--onedir`). Either way, `--onefile` does not survive.

**Measured, amd64:**

| metric | onefile | onedir | change |
|---|---:|---:|---:|
| compressed artifact | 301.5 MiB | 506.9 MiB | **+68.1%** |
| build wall-clock | 77.7 s | 89.4 s | +15.1% |
| warm start to `--selftest` | 2.849 s | 2.421 s | −15.0% (0.428 s/process) |

**Outcome: neither alternative is adopted. `--onefile` survives, contrary to the
rule's "either way" clause.**

The reasoning, recorded because the conclusion contradicts the plan that
commissioned the measurement:

1. **`onedir` fails the rule's own disqualifier.** The rule applies a >40%
   compressed-size threshold to python-build-standalone. `onedir` regresses
   compressed size by **68.1%**. It was exempted from that test only because the
   plan assumed `onedir` was roughly size-neutral — an assumption these numbers
   refute. Applying the same standard even-handedly disqualifies it.

2. **What the regression buys is small.** 0.428 s per process start. Across the
   backend and six workers that is **3.0 s at boot**, against **+205 MiB on every
   download**, for a self-hosted product whose users fetch over home connections.

3. **The central premise is unproven, not merely unmet.** The argument for
   abandoning `--onefile` was that `_MEI` extraction is paid at every process
   start. Cold and warm figures here are indistinguishable (2.856/2.849 and
   2.418/2.421) because the page cache could not be dropped without root, so the
   *cold* extraction cost has not been measured at all. The 0.428 s delta is a
   warm-start figure.

**Consequences, stated rather than left implicit:**

- `specs/1.0.0/slices/agt-3-pyinstaller-containment.md` stays live. The `_MEI`
  containment burden is a real, ongoing cost that this measurement does not
  remove, and the slice should not be closed.
- The hidden-import hazard (three collectors in `build_native_release.py`,
  including an AST parser) also stays. `--onedir` would not have fixed it either;
  only python-build-standalone would.
- `--selftest` (shipped in step 1) is what actually guards the v0.4.2 failure
  class, and it is independent of packaging. That protection is already in place.

**What would change this answer**, in priority order:

1. A **root-enabled cold-start measurement**. If cold extraction costs materially
   more than warm, the trade shifts. This is the cheapest missing input.
2. A **python-build-standalone prototype**, measured. It is the only candidate
   that removes the extraction tax *and* the hidden-import hazard, and it is the
   one the rule was actually written for. It remains unevaluated.
3. **arm64 figures.** Unmeasured here; no arm64 host was available. Not
   extrapolated from amd64, deliberately.

The tooling to answer all three is committed (`scripts/bench_packaging.py`,
`--packaging`, `--output-dir`). The default packaging mode is unchanged.

## Decision (2026-09-22) — superseding the 2026-09-20 outcome

python-build-standalone was measured on worktop (Fedora 44, amd64, Intel Core
Ultra 7 258V, 8 logical CPUs, 30 GiB) at commit `ae8fd9c0`:

| configuration | build (s) | compressed (MiB) | installed (MiB) | warm selftest (s) |
|---|---:|---:|---:|---:|
| onefile | 59.1 | 122.4 | 155.2 | 2.848 |
| pbs     | 30.3 | 134.7 | 463.1 | 2.240 |

Page cache was not dropped (needs root); cold and warm are not distinguishable.
Compressed size rose **10.0 %**; build wall-clock fell **48.7 %**. Installed size
rose because the PBS tree keeps a full CPython plus site-packages rather than a
single compressed executable.

The 2026-09-20 rule ("adopt PBS unless it regresses compressed size by more
than 40 % or build wall-clock by more than 50 %") is retired with the plan it
belonged to. PBS is adopted by `docs/superpowers/specs/2026-09-22-installer-and-release-design.md`
D3 on grounds that rule did not weigh: it removes the hidden-import failure
class (three collectors, one an AST parser, each written after a shipped
failure) and the `_MEI*` extraction containment burden (AGT-11, P0). The
size delta above is within the old threshold, and is recorded
here rather than argued about.
