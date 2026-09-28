"""Every artifact a release workflow downloads by pattern is one it produces.

The staged image merge in release-dry-run.yml failed on its first execution
with "expected 2 per-architecture OCI archives, found 1". Its download used
`pattern: dry-run-image-a?d64`, narrowed from `dry-run-image-*` so it would
stop matching the provenance uploads (`dry-run-image-build-info-*`). `?` is one
character, so the pattern matched `amd64` and never `arm64`. Nothing evaluated
the pattern against the names the workflow actually uploads, so the mistake was
invisible until a runner downloaded one archive of two.

The fix was to stop the prefixes overlapping rather than to find a cleverer
glob. This is the guard for the class: it expands every `actions/upload-artifact`
name the run produces — including those of the reusable workflows it calls —
over each job's matrix, and evaluates every `pattern:` download against that
set with the matcher download-artifact uses.

Matching semantics. download-artifact filters with minimatch; artifact names
cannot contain `/`, so for `*`, `?` and `[...]` that is exactly
`fnmatch.fnmatchcase` (case-sensitive, like minimatch's default). minimatch
also brace-expands `{a,b}`. That is modelled rather than refused: a pattern is
brace-expanded (nested and multiple groups included) and matches if any
expansion does, which is minimatch's behaviour. Extglobs and `**` are not
modelled, and a pattern using them fails the test rather than being evaluated
wrongly.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip(
    "yaml", reason="PyYAML parses the workflow files; it arrives with the backend dev extra"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DRY_RUN = "release-dry-run.yml"

# Workflows whose pattern downloads are checked. Both release graphs: the dry
# run is the rehearsal, release.yml is the thing it rehearses.
CHECKED_WORKFLOWS = ("release-dry-run.yml", "release.yml")

_EXPR = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")
_UNMODELLED = re.compile(r"\*\*|[?*+@!]\(")


def _load(name: str) -> dict[str, Any]:
    document = yaml.safe_load((WORKFLOW_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{name} is not a mapping"
    return document


def _uses(step: dict[str, Any], action: str) -> bool:
    uses = step.get("uses")
    return isinstance(uses, str) and uses.split("@", 1)[0] == action


def _matrix_axis(key: str, values: Any, inputs: dict[str, Any]) -> list[Any]:
    """A matrix axis as a list: a literal, or `${{ fromJSON(inputs.x) }}` of a known input."""
    if isinstance(values, list):
        return values
    match = re.fullmatch(r"\$\{\{\s*fromJSON\((inputs\.[\w-]+)\)\s*\}\}", str(values).strip())
    assert match is not None and match.group(1) in inputs, (
        f"matrix axis {key!r} is {values!r}; this test cannot expand it"
    )
    decoded = json.loads(str(inputs[match.group(1)]))
    assert isinstance(decoded, list), f"matrix axis {key!r} decodes to {decoded!r}, not a list"
    return decoded


def _matrix_combinations(job: dict[str, Any], inputs: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The concrete matrix entries a job runs, following GitHub's include rules.

    Axes form a cartesian product and `exclude` removes matching combinations.
    Each `include` entry is merged into every original combination whose axis
    values it does not contradict; one that fits none becomes a combination of
    its own (with no axes, that is every entry).
    """
    strategy = job.get("strategy")
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if matrix is None:
        return [{}]
    assert isinstance(matrix, dict), f"matrix is an expression ({matrix!r}); this test cannot expand it"

    axes = {
        k: _matrix_axis(k, v, inputs or {})
        for k, v in matrix.items()
        if k not in ("include", "exclude")
    }
    base: list[dict[str, Any]] = (
        [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
    )
    for excluded in matrix.get("exclude") or []:
        base = [c for c in base if any(c.get(k) != v for k, v in excluded.items())]
    added: list[dict[str, Any]] = []
    for extra in matrix.get("include") or []:
        compatible = [c for c in base if all(c[k] == v for k, v in extra.items() if k in axes)]
        for combo in compatible:
            combo.update(extra)
        if not compatible:
            added.append(dict(extra))
    return (base + added) or [{}]


# Contexts whose values exist only at run time (a job output, a step output,
# the run id). A name built from one is kept with an opaque placeholder in that
# position, which only `*` can reach — the same as a real pattern would need.
_RUNTIME_ONLY = ("needs.", "steps.", "github.")


def _render(template: str, context: dict[str, Any]) -> str:
    """Substitute `${{ matrix.x }}` / `${{ inputs.x }}`; fail on anything unknown."""

    def substitute(match: re.Match[str]) -> str:
        expression = match.group(1)
        if expression.startswith(_RUNTIME_ONLY):
            return f"<runtime:{expression}>"
        if expression not in context:
            raise AssertionError(
                f"cannot resolve ${{{{ {expression} }}}} in artifact name {template!r}; "
                "extend this test's context rather than skipping the name"
            )
        return str(context[expression])

    return _EXPR.sub(substitute, template)


def _call_inputs(called: dict[str, Any], caller_with: dict[str, Any] | None) -> dict[str, Any]:
    """`inputs.*` for a reusable workflow: declared defaults, overridden by `with:`."""
    triggers = called.get("on") or called.get(True) or {}
    call = triggers.get("workflow_call") if isinstance(triggers, dict) else None
    declared = (call or {}).get("inputs") or {}
    values = {name: spec.get("default") for name, spec in declared.items() if isinstance(spec, dict)}
    values.update(caller_with or {})
    return {f"inputs.{k}": v for k, v in values.items() if v is not None}


def produced_artifacts(
    workflow: str, inputs: dict[str, Any] | None = None, _seen: frozenset[str] = frozenset()
) -> dict[str, set[str]]:
    """Every artifact name the workflow's run uploads, keyed by the job that uploads it.

    Jobs that call a local reusable workflow contribute that workflow's uploads,
    keyed `<caller job>/<called job>`, since they land in the same run.
    """
    assert workflow not in _seen, f"reusable workflow cycle through {workflow}"
    document = _load(workflow)
    produced: dict[str, set[str]] = {}
    for job_name, job in (document.get("jobs") or {}).items():
        uses = job.get("uses")
        if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
            called_name = uses.rsplit("/", 1)[1]
            called = _load(called_name)
            nested = produced_artifacts(
                called_name, _call_inputs(called, job.get("with")), _seen | {workflow}
            )
            for inner, names in nested.items():
                produced[f"{job_name}/{inner}"] = names
            continue
        for combo in _matrix_combinations(job, inputs):
            context = dict(inputs or {})
            context.update({f"matrix.{k}": v for k, v in combo.items()})
            for step in job.get("steps") or []:
                if _uses(step, "actions/upload-artifact"):
                    name = (step.get("with") or {}).get("name")
                    assert isinstance(name, str), f"{workflow}:{job_name} uploads with no name"
                    produced.setdefault(job_name, set()).add(_render(name, context))
    return produced


def _all_names(produced: dict[str, set[str]]) -> set[str]:
    return set().union(*produced.values()) if produced else set()


def _expand_braces(pattern: str) -> list[str]:
    """minimatch's brace expansion: `a{b,c}d` -> [abd, acd], innermost first."""
    match = re.search(r"\{([^{}]*,[^{}]*)\}", pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [
        expanded
        for option in match.group(1).split(",")
        for expanded in _expand_braces(head + option + tail)
    ]


def pattern_matches(pattern: str, name: str) -> bool:
    """Whether download-artifact's `pattern:` selects the artifact *name*."""
    assert not _UNMODELLED.search(pattern), (
        f"pattern {pattern!r} uses minimatch syntax (globstar or extglob) this test "
        "does not model; extend pattern_matches rather than loosening the check"
    )
    return any(fnmatch.fnmatchcase(name, p) for p in _expand_braces(pattern))


def pattern_downloads(workflow: str) -> list[tuple[str, str, str]]:
    """(job, step name, pattern) for every download-artifact step using `pattern:`."""
    found = []
    for job_name, job in (_load(workflow).get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if _uses(step, "actions/download-artifact"):
                pattern = (step.get("with") or {}).get("pattern")
                if isinstance(pattern, str):
                    found.append((job_name, str(step.get("name", "")), pattern))
    return found


# ── Self-checks on the matcher: it must reproduce the incident ─────────────────


def test_the_matcher_reproduces_the_a_question_mark_d64_mistake() -> None:
    assert pattern_matches("dry-run-image-a?d64", "dry-run-image-amd64")
    assert not pattern_matches("dry-run-image-a?d64", "dry-run-image-arm64")


def test_the_matcher_brace_expands_like_minimatch() -> None:
    assert pattern_matches("img-{amd64,arm64}", "img-arm64")
    assert pattern_matches("x-{a,b{c,d}}", "x-bd")
    assert not pattern_matches("img-{amd64,arm64}", "img-{amd64,arm64}")


def test_the_matcher_refuses_what_it_does_not_model() -> None:
    with pytest.raises(AssertionError):
        pattern_matches("img-@(a|b)", "img-a")


def test_the_matrix_expansion_covers_the_image_legs() -> None:
    combos = _matrix_combinations(_load(DRY_RUN)["jobs"]["image"])
    assert sorted(c["arch"] for c in combos) == ["amd64", "arm64"]


# ── The rules ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("workflow", CHECKED_WORKFLOWS)
def test_every_pattern_download_matches_something_produced(workflow: str) -> None:
    names = _all_names(produced_artifacts(workflow))
    dead = [
        f"{job} / {step!r}: pattern {pattern!r}"
        for job, step, pattern in pattern_downloads(workflow)
        if not any(pattern_matches(pattern, name) for name in names)
    ]
    assert not dead, (
        f"{workflow} downloads by patterns that match no artifact the run uploads:\n  "
        + "\n  ".join(dead)
        + f"\nproduced: {sorted(names)}"
    )


def _oci_archive_names() -> set[str]:
    """The per-arch OCI archive names the dry run's image job uploads."""
    job = _load(DRY_RUN)["jobs"]["image"]
    names: set[str] = set()
    for combo in _matrix_combinations(job):
        context = {f"matrix.{k}": v for k, v in combo.items()}
        for step in job["steps"]:
            if not _uses(step, "actions/upload-artifact"):
                continue
            upload = step.get("with") or {}
            if str(upload.get("path", "")).endswith(".tar"):
                names.add(_render(upload["name"], context))
    return names


def test_the_image_merge_downloads_exactly_the_oci_archives() -> None:
    """One archive per image-matrix arch, and nothing else: not provenance, not diagnostics.

    `merge-multiple: true` drops everything matched into /tmp/images, and the
    job then counts `image-*.tar` files against the number of architectures.
    """
    arches = {c["arch"] for c in _matrix_combinations(_load(DRY_RUN)["jobs"]["image"])}
    expected = _oci_archive_names()
    assert len(expected) == len(arches), (
        f"expected one OCI archive upload per image arch {sorted(arches)}; found {sorted(expected)}"
    )

    downloads = [
        pattern for job, _step, pattern in pattern_downloads(DRY_RUN) if job == "image-merge"
    ]
    assert len(downloads) == 1, f"image-merge should download the OCI archives once; found {downloads}"
    pattern = downloads[0]

    everything = _all_names(produced_artifacts(DRY_RUN))
    matched = {name for name in everything if pattern_matches(pattern, name)}
    assert matched == expected, (
        f"image-merge's pattern {pattern!r} selects {sorted(matched)}; it must select exactly "
        f"the per-arch OCI archives {sorted(expected)}.\n"
        f"  missing: {sorted(expected - matched)}\n  extra:   {sorted(matched - expected)}"
    )


def test_no_other_artifact_shares_the_oci_archive_prefix() -> None:
    """The OCI archive family and every other dry-run artifact do not share a prefix.

    `<oci-prefix>*` is the natural pattern for the OCI archives, so no other
    artifact may start with that prefix. This is what makes the pattern above
    correct by construction rather than by a carefully shaped glob.
    """
    oci = _oci_archive_names()
    arches = {c["arch"] for c in _matrix_combinations(_load(DRY_RUN)["jobs"]["image"])}
    prefixes = {name[: -len(arch)] for name in oci for arch in arches if name.endswith(arch)}
    others = _all_names(produced_artifacts(DRY_RUN)) - oci
    overlapping = sorted(name for name in others for prefix in prefixes if name.startswith(prefix))
    assert not overlapping, (
        f"these artifacts share the OCI archive prefix {sorted(prefixes)} and would be "
        f"selected by `{next(iter(prefixes), '')}*`: {overlapping}. Rename them."
    )
