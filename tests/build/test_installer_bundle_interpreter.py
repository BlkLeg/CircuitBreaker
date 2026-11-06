"""install.sh hands the lifecycle journal the bundle's interpreter, and keeps it alive.

The lifecycle journal (deploy/lib/lifecycle.sh) runs its state utility under a
trusted Python. `cb_lifecycle_python` tries /usr/bin/python3 and otherwise
falls back to the verified bundle's python/bin/python3 — but only if the
caller passes it, and no caller did. Every native host without a system
python3 (minimal Debian 12, Fedora 41+ whose dnf5 is not Python, Arch) then
stopped with exit 7 straight after the bundle phase, on install and on update
alike, and the installer journey went red on exactly those three distros. The
library's own tests stayed green because they call the function directly;
nothing checked that install.sh wires it.

The fallback has a lifetime as well as a call site. The bundle is extracted
into CB_PRIVATE_TMP, which stage0_install_bundle used to delete as soon as the
files were copied — while the journal still needed that interpreter for the
final `committed` checkpoint written from the EXIT trap. Deleting it there
turns every successful install on such a host into `recovery_required`.

A full run of main needs root and a real host; the installer journey does
that. These tests pin the two halves it found broken.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "install.sh"
TEXT = INSTALL_SH.read_text(encoding="utf-8")


def _function(name: str) -> str:
    """The body of shell function `name` in install.sh, from its header to its closing brace."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", TEXT, re.DOTALL | re.MULTILINE)
    assert match, f"install.sh defines no {name}()"
    return match.group(1)


def _code_lines(body: str) -> list[str]:
    """Non-comment lines, stripped, so an explanatory comment can never satisfy an assertion."""
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]


def _first(lines: list[str], needle: str) -> int:
    for index, line in enumerate(lines):
        if needle in line:
            return index
    raise AssertionError(f"no line containing {needle!r}")


def test_main_resolves_the_interpreter_with_the_bundle_fallback_before_the_first_change() -> None:
    lines = _code_lines(_function("main"))
    resolve = _first(lines, 'cb_lifecycle_python "$bundle_python"')
    assert resolve < _first(lines, "cb_lifecycle_install_control_plane"), (
        "the interpreter must be resolved before the control plane is installed: "
        "a refusal (exit 7) has to leave the host unchanged"
    )
    assert resolve < _first(lines, "cb_lifecycle_begin ")
    assignment = _first(lines, 'bundle_python="${CB_BUNDLE_DIR}/python/bin/python3"')
    assert assignment < resolve


def test_the_bundle_fallback_applies_to_updates_as_well_as_fresh_installs() -> None:
    """R13 as amended: a 0.4.6 host without python3 must be able to update."""
    lines = _code_lines(_function("main"))
    start = _first(lines, 'local bundle_python=""')
    resolve = _first(lines, 'cb_lifecycle_python "$bundle_python"')
    window = "\n".join(lines[start : resolve + 1])
    assert "UPGRADE_MODE" not in window, "the bundle interpreter must not be offered to fresh installs only"


def test_stage0_install_bundle_never_deletes_the_private_tmp_unconditionally() -> None:
    body = "\n".join(_code_lines(_function("stage0_install_bundle")))
    assert 'rm -rf -- "$CB_PRIVATE_TMP"' not in body, (
        "stage0_install_bundle may only remove CB_PRIVATE_TMP through the guard that keeps it "
        "while the lifecycle interpreter lives inside it"
    )


def _cleanup_guard() -> str:
    body = _function("stage0_install_bundle")
    match = re.search(r'^\s*case "\$\{_CB_LIFECYCLE_PYTHON:-\}" in\n.*?^\s*esac\n', body, re.DOTALL | re.MULTILINE)
    assert match, "stage0_install_bundle has no cleanup guard on _CB_LIFECYCLE_PYTHON"
    return match.group(0)


def _run_guard(tmp_path: Path, interpreter: str) -> bool:
    """Run the real guard and _cb_remove_private_tmp; return whether CB_PRIVATE_TMP survived."""
    private = tmp_path / "private"
    (private / "bundle" / "python" / "bin").mkdir(parents=True)
    interpreter = interpreter.replace("{private}", str(private))
    script = (
        "set -Eeuo pipefail\n"
        f"_cb_remove_private_tmp() {{\n{_function('_cb_remove_private_tmp')}}}\n"
        f'CB_PRIVATE_TMP="{private}"\n'
        f'_CB_LIFECYCLE_PYTHON="{interpreter}"\n'
        + _cleanup_guard()
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return private.exists()


def test_the_private_tmp_survives_while_the_bundle_interpreter_is_in_use(tmp_path: Path) -> None:
    assert _run_guard(tmp_path, "{private}/bundle/python/bin/python3")


def test_the_private_tmp_is_removed_when_the_system_interpreter_is_in_use(tmp_path: Path) -> None:
    assert not _run_guard(tmp_path, "/usr/bin/python3")


def test_a_sibling_directory_with_a_shared_prefix_does_not_keep_the_private_tmp(tmp_path: Path) -> None:
    """/tmp/tmp.abc must not be kept alive by an interpreter under /tmp/tmp.abcdef."""
    assert not _run_guard(tmp_path, "{private}-other/python/bin/python3")


def test_the_exit_trap_removes_the_private_tmp_only_after_the_final_checkpoint() -> None:
    lines = _code_lines(_function("_cb_on_exit"))
    removals = [i for i, line in enumerate(lines) if line == "_cb_remove_private_tmp"]
    results = [i for i, line in enumerate(lines) if line.startswith("cb_install_result ")]
    assert len(removals) == 2, "both exits of _cb_on_exit (revert and normal) must remove CB_PRIVATE_TMP"
    assert len(results) == 2
    for result, removal in zip(results, removals, strict=True):
        assert result < removal, "cb_install_result writes the last checkpoint, which may need the bundle interpreter"
