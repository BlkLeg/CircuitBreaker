"""REL-08 — un-awaited coroutine warnings and deprecations stay tracked defects.

The backend suite runs with `error::RuntimeWarning` and `error::DeprecationWarning`,
so an async or deprecation warning fails the build rather than scrolling past.
That gate is only worth anything if the escape hatch beside it stays honest:
every `ignore:` entry must name an owner and the condition that removes it, and
none of them may silence a warning raised by our own code.

The acceptance criterion is "no unexplained async/deprecation warnings; future
removal dates have owners", which is a property of the register, not of any one
test run — so this reads the register and checks it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _BACKEND_ROOT / "pyproject.toml"

# An owner is "name (team)" — the shape every other governance register in this
# repo uses, e.g. the requirement ledger's "shawnji (backend)".
_OWNER_RE = re.compile(r"\b[\w.\-]+\s*\([\w \-]+\)")
# A removal condition. "Remove when X" is the phrasing already in the file; the
# point is that the entry says what makes it go away, not that it says a date.
_REMOVAL_RE = re.compile(r"\bremove\b", re.IGNORECASE)

_FATAL_CATEGORIES = ("error::RuntimeWarning", "error::DeprecationWarning")


def _filterwarnings_block() -> list[str]:
    """The raw `filterwarnings` lines, comments included, in file order."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    start = text.index("filterwarnings = [")
    end = text.index("\n]", start)
    return text[start:end].splitlines()


def entries_with_justifications(lines: list[str]) -> list[tuple[str, str]]:
    """Pair each filter entry with the comment block immediately above it.

    Pure so the rule itself is testable: `test_the_rule_rejects_an_unowned_entry`
    below feeds it a synthetic register.
    """
    pairs: list[tuple[str, str]] = []
    comment: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            comment.append(line.lstrip("# "))
            continue
        if not line or line.startswith("filterwarnings"):
            continue
        pairs.append((line.strip().strip(",").strip('"'), " ".join(comment)))
        comment = []
    return pairs


def unjustified_ignores(pairs: list[tuple[str, str]]) -> list[str]:
    """Ignore entries missing an owner or a removal condition."""
    offenders = []
    for entry, justification in pairs:
        if not entry.startswith("ignore"):
            continue
        if not _OWNER_RE.search(justification) or not _REMOVAL_RE.search(justification):
            offenders.append(entry)
    return offenders


def test_async_and_deprecation_warnings_are_fatal_by_default():
    config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    filters = config["tool"]["pytest"]["ini_options"]["filterwarnings"]
    for category in _FATAL_CATEGORIES:
        assert category in filters, f"{category} is no longer fatal — REL-08's gate is off"
    # Order matters: pytest applies the last matching filter, so the blanket
    # errors have to come before the targeted ignores or they would override them.
    for category in _FATAL_CATEGORIES:
        assert filters.index(category) < min(
            (i for i, f in enumerate(filters) if f.startswith("ignore")),
            default=len(filters),
        )


def test_every_silenced_warning_names_an_owner_and_a_removal_condition():
    offenders = unjustified_ignores(entries_with_justifications(_filterwarnings_block()))
    assert not offenders, (
        "these filterwarnings ignores carry no owner and/or no removal condition: "
        f"{offenders}. REL-08 requires each one to name both."
    )


def test_no_ignore_silences_a_warning_raised_by_our_own_code():
    """A third-party deprecation may be waited out. One of ours is a defect and
    has to be fixed, not filtered."""
    config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    filters = config["tool"]["pytest"]["ini_options"]["filterwarnings"]
    for entry in filters:
        if not entry.startswith("ignore"):
            continue
        parts = entry.split(":")
        module = parts[3] if len(parts) > 3 else ""
        assert not module.startswith("app."), (
            f"{entry!r} silences a warning from our own code; fix the call site instead"
        )


@pytest.mark.parametrize(
    ("justification", "expected_offenders"),
    [
        ("shawnji (backend): remove when httpx2 ships.", 0),
        ("remove when httpx2 ships.", 1),  # no owner
        ("shawnji (backend): third-party noise.", 1),  # no removal condition
        ("", 1),  # no justification at all
    ],
)
def test_the_rule_rejects_an_unowned_or_open_ended_entry(justification, expected_offenders):
    """The register above passes today; this proves the check would catch it if
    it stopped passing."""
    lines = [f"    # {justification}", '    "ignore:something:DeprecationWarning",']
    assert len(unjustified_ignores(entries_with_justifications(lines))) == expected_offenders
