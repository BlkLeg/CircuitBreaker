"""GOV-13: the historical-record indexes must stay complete.

`SECURITY_REPORTS/README.md` and `plans/README.md` exist so that no security
report, patch record or plan sits in the tree without a status telling a reader
whether it is current, historical or superseded. Writing the indexes once was
GOV-13's first half; this file is the second, which the ledger recorded as
outstanding: *"no test enforces either index, so a new report added without a
row would not be caught."*

The failure this prevents is quiet: a contributor adds a report, the index is
not updated, and six months later the directory is a pile of undated documents
again — which is the exact state GOV-13 was raised to fix. A test is the only
thing that makes the index a rule rather than a habit.

Each index is matched by the document's filename appearing in a Markdown link
within its README, because that is how every existing row is written and it is
what makes the row navigable rather than merely present.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# A README is never a row in its own index, and neither is a directory.
_EXCLUDED_NAMES = {"README.md"}


def _indexed_targets(readme: Path) -> set[str]:
    """Basenames of every Markdown link target in `readme`.

    Rows link with a repo-relative path (`./SECURITY_PATCH-3.md`,
    `../SECURITY_PATCHES/security_patch.md`), so comparing basenames keeps the
    test indifferent to which README indexes a given directory — the security
    README deliberately indexes two directories.
    """
    text = readme.read_text(encoding="utf-8")
    return {
        Path(match.group(1).split("#", 1)[0]).name
        for match in re.finditer(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)", text)
    }


def _documents(directory: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix in suffixes
        and path.name not in _EXCLUDED_NAMES
    )


def _assert_all_indexed(directory: Path, readme: Path, suffixes: tuple[str, ...]) -> None:
    assert readme.exists(), f"missing index: {readme.relative_to(ROOT)}"
    indexed = _indexed_targets(readme)
    missing = [
        doc.name for doc in _documents(directory, suffixes) if doc.name not in indexed
    ]
    assert not missing, (
        f"{len(missing)} document(s) in {directory.relative_to(ROOT)}/ have no row in "
        f"{readme.relative_to(ROOT)}: {missing}. GOV-13 requires every historical record "
        f"to carry a date, the version it describes and a status, so a reader can tell "
        f"whether it still applies. Add a row rather than deleting the document."
    )


def test_every_security_report_is_indexed():
    """Audits, triage and raw scanner output under SECURITY_REPORTS/."""
    _assert_all_indexed(
        ROOT / "SECURITY_REPORTS",
        ROOT / "SECURITY_REPORTS" / "README.md",
        (".md", ".txt"),
    )


def test_every_security_patch_record_is_indexed():
    """SECURITY_PATCHES/ is indexed by the SECURITY_REPORTS README, not its own."""
    _assert_all_indexed(
        ROOT / "SECURITY_PATCHES",
        ROOT / "SECURITY_REPORTS" / "README.md",
        (".md", ".txt"),
    )


def test_every_plan_is_indexed():
    """Design and remediation plans under plans/."""
    _assert_all_indexed(ROOT / "plans", ROOT / "plans" / "README.md", (".md",))


def test_indexes_name_the_current_source_of_truth():
    """An index that does not defer to the ledger invites being read as current.

    Both READMEs open by saying these are historical records and that the
    requirement ledger decides what is actually closed. That sentence is the
    reason the index is safe to keep; without it the directory reads as a
    live security posture, which is how it was being misread before GOV-13.
    """
    ledger = "specs/1.0.0/release-control/requirement-ledger.csv"
    for readme in (
        ROOT / "SECURITY_REPORTS" / "README.md",
        ROOT / "plans" / "README.md",
    ):
        text = readme.read_text(encoding="utf-8")
        assert ledger in text, (
            f"{readme.relative_to(ROOT)} does not point at {ledger}. Every historical "
            f"index must name the ledger as the current source of truth."
        )
