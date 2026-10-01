"""Every inlined library copy must stay byte-identical to its deploy/lib/ source.

install.sh inlines deploy/lib/ui.sh and deploy/lib/bundle-signature.sh;
cb-proxmox-deploy.sh, also run straight from a raw `main` URL, inlines
deploy/lib/bundle-signature.sh so it can verify a release bundle on the
Proxmox host. The reasoning below is the same for every target.

install.sh is served raw from `main` — pages.yml does a bare `cp` and the
documented install command is `curl -fsSL .../main/install.sh | sudo bash` —
so it cannot `source deploy/lib/ui.sh` at runtime; a host running that command
never cloned the repo and has no `deploy/` directory to source from. It
carries an inlined copy between two marker comments instead, and
`deploy/setup.sh`/`uninstall.sh` use the real library from the installed
bundle. That is a dependency pinned in two places — CLAUDE.md's rule for that
shape is explicit, and `test_playwright_image_matches_package.py` is the
precedent: the guard goes in, not only the fix.

`scripts/ci/sync_installer_ui.py` is the write side of this pair. This is the
read side: it extracts the block between each marker pair in each target and
asserts it equals the library exactly, byte for byte.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/ is not a package, so load the sync script by path; it is the single
# source of truth for which libraries are inlined and between which markers.
_spec = importlib.util.spec_from_file_location(
    "sync_installer_ui", REPO_ROOT / "scripts" / "ci" / "sync_installer_ui.py"
)
assert _spec is not None and _spec.loader is not None
_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sync)
BLOCKS: list[tuple[Path, Path, str, str]] = [tuple(b) for b in _sync.BLOCKS]

_SYNC_COMMAND = ".venv/bin/python scripts/ci/sync_installer_ui.py"


def _block_re(begin: str, end: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(begin) + r"\n(.*)^" + re.escape(end), re.DOTALL | re.MULTILINE
    )


_PARAMS = pytest.mark.parametrize(
    ("target", "library", "begin", "end"),
    BLOCKS,
    ids=[f"{target.name}:{lib.name}" for target, lib, _, _ in BLOCKS],
)


@_PARAMS
def test_the_inlining_markers_exist(
    target: Path, library: Path, begin: str, end: str
) -> None:
    """Guards the guard: if someone deletes the markers, the identity test
    below must not pass vacuously by finding nothing to compare."""
    text = target.read_text(encoding="utf-8")
    assert begin in text, (
        f"{target.name} is missing the marker {begin!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert end in text, (
        f"{target.name} is missing the marker {end!r} — the inlined "
        f"renderer block can no longer be located, so run '{_SYNC_COMMAND}' "
        "and restore the marker comments around it."
    )
    assert _block_re(begin, end).search(text), (
        f"{target.name} has both marker strings but not in the expected "
        f"'{begin} ... {end}' order/shape — the block between "
        f"them cannot be extracted. Run '{_SYNC_COMMAND}' to regenerate it."
    )


@_PARAMS
def test_the_inlined_block_matches_the_library_byte_for_byte(
    target: Path, library: Path, begin: str, end: str
) -> None:
    target_text = target.read_text(encoding="utf-8")
    match = _block_re(begin, end).search(target_text)
    assert match, (
        f"could not find the inlined {library.name} block in {target} "
        f"— run '{_SYNC_COMMAND}' to regenerate it."
    )
    inlined = match.group(1)
    library_text = library.read_text(encoding="utf-8")
    assert inlined == library_text, (
        f"{target.name}'s inlined copy of {library.name} has drifted from the "
        f"library. Run '{_SYNC_COMMAND}' to resync it, then commit the "
        "result."
    )


def test_blocks_lists_exactly_the_inlined_libraries() -> None:
    """An emptied or shortened BLOCKS would make the parity tests above vacuous."""
    assert [
        (
            target.relative_to(REPO_ROOT).as_posix(),
            lib.relative_to(REPO_ROOT).as_posix(),
        )
        for target, lib, _, _ in BLOCKS
    ] == [
        ("install.sh", "deploy/lib/ui.sh"),
        ("install.sh", "deploy/lib/bundle-signature.sh"),
        ("cb-proxmox-deploy.sh", "deploy/lib/bundle-signature.sh"),
    ]


def _fake_blocks(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Two targets, each inlining one library, in tmp_path."""
    lib_a = tmp_path / "a.sh"
    lib_a.write_text("echo a\n")
    lib_b = tmp_path / "b.sh"
    lib_b.write_text("echo b\n")
    first = tmp_path / "first.sh"
    first.write_text("#!/bin/bash\n# BEGIN A\necho a\n# END A\n")
    second = tmp_path / "second.sh"
    second.write_text("#!/bin/bash\n# BEGIN B\necho b\n# END B\nmain\n")
    return lib_a, lib_b, first, second


def test_check_reports_drift_in_a_target_other_than_install_sh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lib_a, lib_b, first, second = _fake_blocks(tmp_path)
    monkeypatch.setattr(_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        _sync,
        "BLOCKS",
        [
            _sync.Block(first, lib_a, "# BEGIN A", "# END A"),
            _sync.Block(second, lib_b, "# BEGIN B", "# END B"),
        ],
    )
    assert _sync.main(["--check"]) == 0
    lib_b.write_text("echo b2\n")
    before = second.read_text()
    assert _sync.main(["--check"]) == 1
    assert "second.sh has drifted from b.sh" in capsys.readouterr().err
    assert second.read_text() == before, "--check must not write"


def test_sync_rewrites_every_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib_a, lib_b, first, second = _fake_blocks(tmp_path)
    monkeypatch.setattr(_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        _sync,
        "BLOCKS",
        [
            _sync.Block(first, lib_a, "# BEGIN A", "# END A"),
            _sync.Block(second, lib_b, "# BEGIN B", "# END B"),
        ],
    )
    lib_a.write_text("echo a2 \\n\n")
    lib_b.write_text("echo b2\n")
    assert _sync.main([]) == 0
    assert first.read_text() == "#!/bin/bash\n# BEGIN A\necho a2 \\n\n# END A\n"
    assert second.read_text() == "#!/bin/bash\n# BEGIN B\necho b2\n# END B\nmain\n"


def test_a_target_missing_its_markers_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib_a, _, _first, second = _fake_blocks(tmp_path)
    monkeypatch.setattr(_sync, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        _sync, "BLOCKS", [_sync.Block(second, lib_a, "# BEGIN A", "# END A")]
    )
    assert _sync.main(["--check"]) == 1
    assert _sync.main([]) == 1
