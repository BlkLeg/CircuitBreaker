"""REL-19: every skip/xfail marker is registered, owned and dated, and an
unexpected warning fails the run.

RC-08 forbids "an unexplained skip, xfail, warning, scan suppression, or unmet
gate" at sign-off, and REL-19's acceptance is that the register and the test
reports "reconcile exactly". Reconciling exactly is the part a document cannot
do on its own: the security suppressions manifest learned this the hard way —
its test asserted against the date the manifest was written, so every
suppression expired and the file stayed green for three days while the security
gate went red (see test_security_suppressions.py). This file uses today's date
for the same reason.

Two halves, matching the two clauses of REL-19.

Half one, the register. ``specs/1.0.0/release-control/skip-register.csv`` holds
one row per distinct marker, and the four failures below are the ones that
matter:

  * a marker exists with no row — a test was quietly disabled;
  * a row exists with no marker, or with a different number of them — the
    register describes a tree that no longer exists;
  * a row is past its expiry — the thing it excused was never resolved;
  * a row is missing an owner, a reason, a tracking item or a date — the row is
    a placeholder, which is the state RC-08 exists to reject.

Rows are keyed by ``(path, kind, signature)`` and carry an occurrence count,
deliberately *not* by line number. Line numbers move whenever anything above
them is edited, so a line-keyed register would be wrong within a week and would
train everyone to re-run a generator instead of reading what changed. The
signature is the marker's own call text with whitespace collapsed, which is
both stable under reformatting-free edits and greppable: paste it into ``git
grep -F`` and the marker is the only hit. The ``lines`` are recoverable at any
time from ``_scan_markers``; they are not the contract.

Half two, the warnings. ``/pytest.ini`` sets ``filterwarnings = error`` for the
root suites. The static half of that is checked here so an ignore cannot be
added anonymously; the behavioural half runs pytest against a module that
raises a warning and requires the run to fail.

Scope. Every file git does not ignore is scanned — backend and repo-root
pytest, the Go agent suites, and the frontend Vitest/Playwright specs — because
a register that covers one language is a register that documents where the
author happened to look.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_CONTROL = REPO_ROOT / "specs/1.0.0/release-control"
REGISTER = RELEASE_CONTROL / "skip-register.csv"
OWNER_MAP = RELEASE_CONTROL / "owner-map.md"
RISK_REGISTER = RELEASE_CONTROL / "risk-register.csv"
EXCEPTION_REGISTER = RELEASE_CONTROL / "exception-register.csv"
PYTEST_INI = REPO_ROOT / "pytest.ini"

CATEGORIES = {
    # The host cannot construct the state under test: a missing binary, an
    # absent capability, root, a filesystem layout. Expected, and reviewed on
    # the register's cadence rather than fixed.
    "environment",
    # A corpus or parametrised entry that this case has nothing to assert
    # about. The siblings still assert.
    "data",
    # Known-broken, disabled, or guarding a feature that does not exist. These
    # are defects wearing a marker, and they carry the short expiry.
    "defect",
}

_REQUIRED_FIELDS = (
    "skip_id",
    "path",
    "kind",
    "signature",
    "occurrences",
    "category",
    "reason",
    "owner",
    "tracking",
    "expiry",
)

# Written escaped so that scanning this file — which the scan does, it is
# tracked Python — cannot match the patterns' own source.
_PYTHON_MARKER = re.compile(
    r"(?<![\w.])("
    r"pytest\.mark\.(?:skipif|skip|xfail)"
    r"|pytest\.(?:importorskip|skip|xfail)"
    r"|unittest\.(?:skipIf|skipUnless|skip|expectedFailure)"
    r")\b"
)
_GO_MARKER = re.compile(r"(?<![\w.])t\.(?:Skipf|SkipNow|Skip)\s*\(")
_JS_MARKER = re.compile(r"(?<![\w.])(?:describe|suite|it|test)\.(?:skip|todo|failing|fixme)\b")
_JS_SPEC = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")

_TRACKING = re.compile(r"^(RISK-\d{3}|EXC-\d{3}|https://github\.com/\S+/issues/\d+)$")


# ── scanning ────────────────────────────────────────────────────────────────


def _candidate_files() -> list[str]:
    """Every file in the working tree that git does not ignore.

    `--others --exclude-standard` alongside `--cached` is the reason this reads
    the index at all rather than walking the filesystem: it picks up a test file
    that exists but is not yet committed — where a skip is most likely to be
    sitting while someone is still working — and it still gets .gitignore for
    free, which keeps .venv, node_modules, site/ and the agent worktrees out
    without maintaining a second exclusion list that would drift from the first.

    Tracked-only would also pass in CI, which always runs on a committed tree.
    It would just say nothing locally until after the commit, which is the wrong
    end of the loop to find out that a test was disabled.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(set(out.stdout.splitlines()))


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _call_arguments(text: str, open_paren: int) -> str | None:
    """Source between the parentheses of the call starting at `open_paren`.

    A marker's arguments routinely span lines and contain nested calls,
    parentheses inside reason strings, and trailing commas, so the extent is
    found by matching parentheses with string literals honoured rather than by
    a regex that would stop at the first `)`.
    """
    depth = 0
    quote: str | None = None
    index = open_paren
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : index]
        index += 1
    return None


def _in_comment(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    return text[line_start:position].lstrip().startswith("#")


def _scan_markers() -> list[tuple[str, str, str, int]]:
    """Every skip/xfail marker git tracks, as (path, kind, signature, line)."""
    found: list[tuple[str, str, str, int]] = []
    for relative in _candidate_files():
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        if relative.endswith(".py"):
            pattern, language = _PYTHON_MARKER, "py"
        elif relative.endswith("_test.go"):
            pattern, language = _GO_MARKER, "go"
        elif _JS_SPEC.search(path.name):
            pattern, language = _JS_MARKER, "js"
        else:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - no such file is tracked today
            continue
        for match in pattern.finditer(text):
            # A marker named in prose is prose. Commented-out markers are not
            # markers either, and the register must not demand rows for them.
            if language == "py" and _in_comment(text, match.start()):
                continue
            line = text.count("\n", 0, match.start()) + 1
            if language == "py":
                kind = match.group(1)
                trailing = text[match.end() :]
                if trailing.lstrip().startswith("("):
                    offset = match.end() + len(trailing) - len(trailing.lstrip())
                    arguments = _call_arguments(text, offset)
                    signature = (
                        f"{kind}({_collapse(arguments)})" if arguments is not None else kind
                    )
                else:
                    # A bare decorator with no call, e.g. an unparameterised
                    # expected-failure marker.
                    signature = kind
            else:
                # Go and JavaScript markers are single-line in this tree, and
                # a JS one is followed by its whole callback body — taking the
                # line keeps the signature to the part a reader recognises.
                line_end = text.find("\n", match.start())
                line_start = text.rfind("\n", 0, match.start()) + 1
                signature = _collapse(text[line_start : line_end if line_end != -1 else len(text)])
                kind = _collapse(match.group(0)).rstrip("( ")
            found.append((relative, kind, signature, line))
    return found


def _marker_counts() -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for relative, kind, signature, _line in _scan_markers():
        counts[(relative, kind, signature)] += 1
    return counts


def _marker_lines() -> dict[tuple[str, str, str], list[int]]:
    lines: dict[tuple[str, str, str], list[int]] = {}
    for relative, kind, signature, line in _scan_markers():
        lines.setdefault((relative, kind, signature), []).append(line)
    return lines


def _register_rows() -> list[dict[str, str]]:
    with REGISTER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["path"], row["kind"], row["signature"])


# ── half one: the register reconciles with the tree ─────────────────────────


def test_the_register_exists_and_is_not_empty():
    """A register nobody wrote reads exactly like a repository with no skips."""
    assert REGISTER.exists(), f"REL-19 register missing: {REGISTER.relative_to(REPO_ROOT)}"
    rows = _register_rows()
    assert rows, "skip-register.csv has a header and no rows"
    assert set(_REQUIRED_FIELDS).issubset(rows[0].keys()), (
        f"skip-register.csv is missing columns: "
        f"{sorted(set(_REQUIRED_FIELDS) - set(rows[0].keys()))}"
    )


def test_every_marker_in_the_tree_has_a_register_row():
    """The failure this catches: a test is disabled and nothing records it."""
    registered = {_key(row) for row in _register_rows()}
    lines = _marker_lines()
    unregistered = sorted(key for key in _marker_counts() if key not in registered)
    detail = "\n".join(
        f"  {path}:{','.join(str(n) for n in lines[(path, kind, signature)])}  "
        f"{kind}  {signature[:120]}"
        for path, kind, signature in unregistered
    )
    assert not unregistered, (
        f"{len(unregistered)} skip/xfail marker(s) have no row in "
        f"{REGISTER.relative_to(REPO_ROOT)}:\n{detail}\n"
        "REL-19 requires every one to carry a reason, an owner, a tracking item "
        "and an expiry. Add the row — or delete the marker, which is the better "
        "fix when the thing it excused is fixed."
    )


def test_every_register_row_still_matches_a_real_marker():
    """A row whose marker is gone, or whose count moved, describes a tree that
    does not exist. Deleting a marker without deleting its row is how a
    register turns back into a document."""
    counts = _marker_counts()
    stale = []
    for row in _register_rows():
        key = _key(row)
        actual = counts.get(key, 0)
        expected = int(row["occurrences"])
        if actual != expected:
            stale.append(f"  {row['skip_id']}  {row['path']}  expected {expected}, found {actual}")
    assert not stale, (
        "register rows no longer match the tree:\n"
        + "\n".join(stale)
        + "\nA count of 0 means the marker was removed: delete the row. A "
        "changed count means markers were added or removed alongside it: update "
        "`occurrences`, and split the row if the new markers deserve their own "
        "reason and expiry."
    )


def test_no_register_row_has_passed_its_expiry():
    """Today, not a pinned date.

    test_security_suppressions.py records what a pinned date costs: the
    assertion could never observe an expiry passing, which is the one thing it
    existed to catch.
    """
    today = datetime.now(UTC).date()
    expired = []
    for row in _register_rows():
        expiry = datetime.strptime(row["expiry"], "%Y-%m-%d").date()
        if expiry < today:
            expired.append(
                f"  {row['skip_id']}  {row['path']}  expired {expiry} "
                f"({(today - expiry).days} days ago, owner {row['owner']}, "
                f"tracking {row['tracking']})"
            )
    assert not expired, (
        f"{len(expired)} register row(s) are past expiry:\n"
        + "\n".join(expired)
        + "\nResolve the marker, or re-approve the row with a new expiry and a "
        "note saying what changed. Moving the date without doing either is how "
        "an expiry stops meaning anything."
    )


def test_every_row_carries_an_owner_a_reason_and_a_tracking_item():
    incomplete = []
    for row in _register_rows():
        blank = [field for field in _REQUIRED_FIELDS if not (row.get(field) or "").strip()]
        if blank:
            incomplete.append(f"  {row.get('skip_id', '?')}  blank: {blank}")
    assert not incomplete, "register rows are placeholders:\n" + "\n".join(incomplete)

    rows = _register_rows()
    identifiers = [row["skip_id"] for row in rows]
    duplicates = sorted({i for i in identifiers if identifiers.count(i) > 1})
    assert not duplicates, f"duplicate skip_id: {duplicates}"
    malformed = sorted(i for i in identifiers if not re.fullmatch(r"SKIP-\d{3}", i))
    assert not malformed, f"skip_id must look like SKIP-001: {malformed}"

    bad_category = sorted(
        f"{row['skip_id']}={row['category']}"
        for row in rows
        if row["category"] not in CATEGORIES
    )
    assert not bad_category, f"category must be one of {sorted(CATEGORIES)}: {bad_category}"


def test_every_owner_is_a_role_from_the_owner_map():
    """RC-07: an owner who is not in the owner map is not accountable to
    anything. The role names are the ones owner-map.md assigns per requirement
    prefix, so a row's owner is checkable rather than decorative."""
    owner_map = OWNER_MAP.read_text(encoding="utf-8")
    unknown = sorted(
        {row["owner"] for row in _register_rows() if row["owner"] not in owner_map}
    )
    assert not unknown, (
        f"owners not named in {OWNER_MAP.relative_to(REPO_ROOT)}: {unknown}. "
        "Use one of the role-level owners it assigns."
    )


def test_every_tracking_item_resolves():
    """"Tracked" has to mean tracked somewhere a reader can go.

    A risk id, an exception id, or a GitHub issue URL — and the register ids
    are checked against the registers that define them, so a typo or a deleted
    risk row fails here rather than at sign-off.
    """
    with RISK_REGISTER.open(encoding="utf-8", newline="") as handle:
        risks = {row["risk_id"] for row in csv.DictReader(handle)}
    with EXCEPTION_REGISTER.open(encoding="utf-8", newline="") as handle:
        exceptions = {row["exception_id"] for row in csv.DictReader(handle)}
    unresolved = []
    for row in _register_rows():
        tracking = row["tracking"].strip()
        if not _TRACKING.fullmatch(tracking):
            unresolved.append(f"  {row['skip_id']}  {tracking!r} is not a RISK/EXC id or issue URL")
        elif tracking.startswith("RISK-") and tracking not in risks:
            unresolved.append(f"  {row['skip_id']}  {tracking} is not in risk-register.csv")
        elif tracking.startswith("EXC-") and tracking not in exceptions:
            unresolved.append(f"  {row['skip_id']}  {tracking} is not in exception-register.csv")
    assert not unresolved, "register rows point at nothing:\n" + "\n".join(unresolved)


def test_registered_paths_exist():
    missing = sorted(
        f"{row['skip_id']} -> {row['path']}"
        for row in _register_rows()
        if not (REPO_ROOT / row["path"]).is_file()
    )
    assert not missing, f"register rows name files that are not in the tree: {missing}"


def test_defect_rows_expire_sooner_than_environment_rows():
    """A defect and a missing binary are not the same kind of exception.

    An environment row is reviewed on the release-control cadence, because the
    host will still lack `pg_dump` next month. A defect row is a disabled test
    or an unimplemented feature, and giving it the same date says the project
    is content to ship it. The rule kept here is only the ordering — the
    concrete dates stay in the register where they can be re-approved.
    """
    rows = _register_rows()
    defects = [datetime.strptime(r["expiry"], "%Y-%m-%d").date() for r in rows if r["category"] == "defect"]
    others = [datetime.strptime(r["expiry"], "%Y-%m-%d").date() for r in rows if r["category"] != "defect"]
    if defects and others:
        assert max(defects) <= min(others), (
            "a defect row expires no earlier than the environment rows: "
            f"latest defect {max(defects)}, earliest environment {min(others)}. "
            "Defects get the shorter review, or the category is wrong."
        )


# ── half two: an unexpected warning fails the run ───────────────────────────


def _filterwarnings_block() -> list[tuple[list[str], str]]:
    """Each entry of pytest.ini's `filterwarnings`, with the comment lines
    immediately above it."""
    lines = PYTEST_INI.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("filterwarnings"))
    except StopIteration:  # pragma: no cover - the assertion below reports it
        return []
    entries: list[tuple[list[str], str]] = []
    comments: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith((" ", "\t", "#")):
            break
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(stripped)
        elif stripped:
            entries.append((comments, stripped))
            comments = []
    return entries


def test_the_root_suite_declares_warnings_as_errors():
    entries = _filterwarnings_block()
    assert entries, (
        f"{PYTEST_INI.name} declares no filterwarnings. REL-19 requires "
        "unexpected warnings to fail the run."
    )
    assert entries[0][1] == "error", (
        "the first filterwarnings entry must be `error` — everything after it "
        f"is a documented exception to that rule, not the rule. Found: {entries[0][1]!r}"
    )


def test_no_ignore_is_anonymous_or_unbounded():
    """The list is empty today. This is what keeps it honest when it is not.

    A bare `ignore`, or an `ignore` for a whole category, hides our warnings
    along with the third-party one being tolerated — which is precisely the
    outcome REL-08 and REL-19 exist to prevent. An ignore with no owner and no
    stated way out is a permanent one.
    """
    owner_map = OWNER_MAP.read_text(encoding="utf-8")
    owners = set(re.findall(r"shawnji \(\w+\)", owner_map))
    problems = []
    for comments, entry in _filterwarnings_block():
        if not entry.startswith("ignore"):
            continue
        if entry in {"ignore", "ignore::DeprecationWarning", "ignore::UserWarning"} or ":" not in entry:
            problems.append(f"  {entry!r} is not narrowed to a message and module")
        comment = " ".join(comments)
        if not any(owner in comment for owner in owners):
            problems.append(f"  {entry!r} names no owner from owner-map.md in the comment above it")
        if "Remove when" not in comment:
            problems.append(f"  {entry!r} states no removal condition (\"Remove when ...\")")
    assert not problems, (
        "filterwarnings ignores must be narrow, owned and time-bound:\n" + "\n".join(problems)
    )


def test_a_warning_actually_fails_a_root_run(tmp_path: Path):
    """The static checks above pin the text; this one pins the behaviour.

    Without `filterwarnings = error` in pytest.ini this module passes with a
    warning printed in the summary, which is the state REL-19 rejects.
    """
    module = tmp_path / "test_rel19_warning_policy.py"
    module.write_text(
        "import warnings\n"
        "\n"
        "def test_emits_a_deprecation_warning():\n"
        "    warnings.warn('REL-19 policy probe', DeprecationWarning)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(PYTEST_INI),
            str(module),
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "a DeprecationWarning did not fail a run configured by pytest.ini:\n"
        f"{result.stdout[-2000:]}"
    )
    assert "REL-19 policy probe" in result.stdout
