"""The two ends of a path-based scanner suppression: it must be safe, and complete.

SEC-18 already requires a reviewed manifest row for every `.trivyignore` entry
(``scripts/validate_security_suppressions.py``): an owner, a reviewer, a reason,
a compensating control and an unexpired date. That governs *why* a suppression
exists. It does not govern what the suppression actually covers, and both
directions of that turned out to matter.

**Safe.** Every path entry is a hole in the secret scanner. The reason every
existing one is defensible is the same sentence in every manifest row —
"gitignored and not part of source" — but nothing checked that the sentence was
true. `docker/circuitbreaker-data/tls/privkey.pem` was a tracked file in this
repository once, which is why `scripts/secret_exposure_guard.sh` exists and
blocks that one path by name. A suppression whose directory holds a tracked file
turns the gate from a check into a rubber stamp, silently, and the broader the
entry the more it hides. So: every suppressed path must be ignored by git and
must contain nothing git tracks.

**Complete.** The gate has to stay green on a normal working tree, or it stops
being read. `make dev` sets ``CB_DATA_DIR`` to ``apps/backend/.dev-data`` and
``scripts/dev-tls.sh`` writes a self-signed key under its ``tls/``; that
directory had no entry, so once a developer had started the dev stack, `make
verify` failed its own security gate on every subsequent run over ephemeral TLS
material of exactly the class two other rows already excused. A gate that goes
red on a state the project's own documented workflow produces is a gate people
learn to bypass, and the next real finding goes past with it. So: every
``CB_DATA_DIR`` this repo's tooling points inside the working tree must have its
``tls/`` suppressed, and adding a new one without an entry fails here — at
authoring time, in the diff that introduces it — rather than weeks later on
somebody else's machine.

Both assertions read the same `.trivyignore` the scan does. That file is the
single governed list: ``scripts/security_scan.sh`` derives Trivy's `--skip-dirs`
from its path entries, because Trivy's ignorefile matches finding IDs and never
paths, which is why those entries were inert for as long as they existed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIVY_IGNORE = ROOT / ".trivyignore"

#: A Trivy finding ID — `CVE-2024-1234`, `AVD-DS-0002`, `GHSA-...`. These are
#: what the ignorefile actually matches, and they are not paths, so they are not
#: subject to either assertion below. Mirrors the filter in security_scan.sh.
_FINDING_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")

#: Files whose `CB_DATA_DIR` assignments decide where runtime TLS material lands.
_DATA_DIR_SOURCES = (
    "Makefile",
    "docker-compose.yml",
    "docker-compose.deps.yml",
    "scripts/dev-tls.sh",
    "scripts/dev-agent.sh",
)

#: `CB_DATA_DIR = value`, `CB_DATA_DIR ?= value`, `CB_DATA_DIR="value"`, and the
#: `${CB_DATA_DIR:-value}` default form the shell scripts use.
_DATA_DIR_ASSIGNMENT = re.compile(
    r"CB_DATA_DIR(?:\s*\??=\s*|=)[\"']?([^\"'\s}]+)|"
    r"CB_DATA_DIR:-([^\"'\s}]+)"
)

#: Names every idiom the Makefile and the shell scripts use for "the repo root".
_ROOT_TOKENS = (
    "$(CURDIR)",
    "${CURDIR}",
    "$(PWD)",
    "${PWD}",
    "$REPO_ROOT",
    "${REPO_ROOT}",
)

#: A plain `NAME = value` / `NAME ?= value` Make assignment. Deliberately not
#: `$(shell ...)` or anything conditional: this resolves the handful of simple
#: directory variables the data-dir assignments are written in terms of
#: (`CB_DATA_DIR="$(CURDIR)/$(BACKEND_DIR)/.dev-data"`), and gives up on the rest
#: rather than reimplementing Make.
_MAKE_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)\s*\??=\s*(.+?)\s*$", re.MULTILINE)

#: How many times to walk the expansion. Two levels covers every real case here;
#: the bound is what stops a self-referential variable from spinning.
_MAX_EXPANSIONS = 4


def _make_variables() -> dict[str, str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return {
        name: value
        for name, value in _MAKE_ASSIGNMENT.findall(text)
        if "$(shell" not in value
    }


def _normalise(value: str, variables: dict[str, str]) -> str | None:
    """Reduce a raw assignment to a repo-relative directory, or None.

    None means "this does not name a directory inside the working tree": an
    absolute container or host path (`/data`, `/var/lib/circuit-breaker`), or an
    indirection through a variable that is not statically resolvable. Both are
    outside what a repository scanner ever looks at.
    """
    # Rooted at the repo means in-tree, however it was spelled. Note the order:
    # the leading "/" left behind by "$(CURDIR)/x" has to be dropped *knowing*
    # it came from a root token, or the result reads as an absolute path and
    # gets discarded as out-of-tree — which is precisely how the
    # apps/backend/.dev-data assignment went unnoticed.
    rooted = any(token in value for token in _ROOT_TOKENS)
    for token in _ROOT_TOKENS:
        value = value.replace(token, "")
    if rooted:
        value = value.lstrip("/")

    for _ in range(_MAX_EXPANSIONS):
        if "$" not in value:
            break
        expanded = re.sub(
            r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]|\$([A-Za-z_][A-Za-z0-9_]*)",
            lambda m: variables.get(m.group(1) or m.group(2), m.group(0)),
            value,
        )
        if expanded == value:
            break
        value = expanded

    if "$" in value or value.startswith("/"):
        return None
    value = value.lstrip("./").strip("/")
    return value or None


def _path_entries() -> list[str]:
    """Path suppressions from `.trivyignore`, in file order."""
    entries: list[str] = []
    for raw in TRIVY_IGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or _FINDING_ID.match(line):
            continue
        entries.append(line)
    return entries


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def test_every_suppressed_path_is_ignored_by_git() -> None:
    """A suppression may only cover something that can never be committed.

    `git check-ignore` is the authority rather than a re-read of `.gitignore`,
    so nested ignore files, negations and `.git/info/exclude` all count the way
    git counts them.
    """
    not_ignored = [
        entry
        for entry in _path_entries()
        if _git("check-ignore", "-q", "--no-index", entry).returncode != 0
    ]

    assert not not_ignored, (
        "these .trivyignore paths are not gitignored, so the scanner is being "
        f"silenced over files that can still be committed: {not_ignored}. Every "
        "manifest row for a path suppression justifies it as 'gitignored and not "
        "part of source' (specs/1.0.0/release-control/security-suppressions.json) "
        "— either make that true in .gitignore, or drop the suppression."
    )


def test_no_suppressed_path_contains_a_tracked_file() -> None:
    """The check `secret_exposure_guard.sh` makes for one path, made for all of them.

    Being listed in `.gitignore` does not mean nothing under it is tracked: git
    honours the index over the ignore rules, so a file added before the rule —
    or added with `git add -f` — stays tracked and stays scanned by nobody.
    That is exactly how `docker/circuitbreaker-data/tls/privkey.pem` came to be
    committed.
    """
    offenders: list[str] = []
    for entry in _path_entries():
        tracked = _git("ls-files", "--error-unmatch", "--", entry)
        if tracked.returncode == 0 and tracked.stdout.strip():
            files = tracked.stdout.strip().splitlines()
            offenders.append(f"{entry} -> {files[:5]}")

    assert not offenders, (
        "git-tracked files live under a suppressed path, so the secret scanner "
        f"is blind to content that is in the repository: {offenders}. Remove the "
        "files from the index (and rotate anything sensitive they contain) rather "
        "than narrowing the suppression around them."
    )


def _declared_data_dirs() -> dict[str, str]:
    """In-tree `CB_DATA_DIR` values, mapped to the file that declares each."""
    variables = _make_variables()
    found: dict[str, str] = {}
    for name in _DATA_DIR_SOURCES:
        path = ROOT / name
        if not path.exists():
            continue
        for match in _DATA_DIR_ASSIGNMENT.finditer(path.read_text(encoding="utf-8")):
            raw = match.group(1) or match.group(2)
            if not raw:
                continue
            normalised = _normalise(raw, variables)
            if normalised:
                found.setdefault(normalised, name)
    return found


def test_the_data_dir_scan_finds_the_known_ones() -> None:
    """Guards the completeness check below from quietly matching nothing.

    A refactor that renamed the variable, moved the Makefile, or changed the
    assignment style would leave the next test passing over an empty set while
    the gate went red for the next person to run `make dev`.
    """
    declared = _declared_data_dirs()
    assert "apps/backend/.dev-data" in declared, (
        "the CB_DATA_DIR scan no longer finds apps/backend/.dev-data, the directory "
        f"`make dev` writes TLS material to. Found: {sorted(declared)}. Update "
        "_DATA_DIR_SOURCES or _DATA_DIR_ASSIGNMENT to match how it is set now."
    )


def test_every_in_tree_data_dir_has_its_tls_suppressed() -> None:
    entries = set(_path_entries())
    missing = sorted(
        f"{directory}/tls/ (set in {source})"
        for directory, source in _declared_data_dirs().items()
        if f"{directory}/tls/" not in entries and f"{directory}/" not in entries
    )

    assert not missing, (
        "a CB_DATA_DIR inside the working tree has no .trivyignore entry for its "
        f"tls/: {missing}. On first start the server writes a self-signed EC key "
        "there, and Trivy reports it HIGH, so `make verify` fails its own security "
        "gate for anyone who has run the dev stack. Add the path to .trivyignore "
        "and a matching row to "
        "specs/1.0.0/release-control/security-suppressions.json — the two tests "
        "above will hold the new entry to being gitignored and untracked."
    )
