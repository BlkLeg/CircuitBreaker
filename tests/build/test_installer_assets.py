"""scripts/ci/installer_assets.py: the one definition of what install.sh downloads."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "installer_assets.py"
INSTALL_SH = REPO_ROOT / "install.sh"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cb_installer_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer_assets = _load()

PARAMETER = 'cb_check_bundle() {\n  local tarball_name="$2"\n}\n'
TEMPLATE = 'local tarball_name="circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz"\n'


def test_the_template_wins_over_an_earlier_parameter_assignment() -> None:
    """The `$2` parameter comes first in install.sh; it is not an asset name."""
    assert (
        installer_assets.tarball_template(PARAMETER + TEMPLATE)
        == "circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz"
    )


def test_the_real_install_sh_yields_exactly_one_template() -> None:
    """The real installer still resolves to a single template.

    This used to assert the `tarball_name="$2"` parameter trap preceded the
    template. cb_verify_bundle_checksum, which held it, was replaced by
    cb_check_bundle, which derives the name with basename, so the trap is gone
    and the remaining guarantee is that the real file still parses.
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert installer_assets.tarball_template(text) == "circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz"


def test_no_candidate_raises() -> None:
    with pytest.raises(installer_assets.InstallerTemplateError):
        installer_assets.tarball_template(PARAMETER)


def test_a_template_missing_the_arch_is_not_a_candidate() -> None:
    with pytest.raises(installer_assets.InstallerTemplateError):
        installer_assets.tarball_template('tarball_name="cb_${CB_VERSION}.tar.gz"\n')


def test_two_candidates_raise() -> None:
    second = 'tarball_name="cb-${CB_VERSION}-${ARCH}.tgz"\n'
    with pytest.raises(installer_assets.InstallerTemplateError):
        installer_assets.tarball_template(TEMPLATE + second)


def test_the_real_install_sh_yields_both_release_tarballs() -> None:
    names = installer_assets.expected_assets(
        INSTALL_SH.read_text(encoding="utf-8"), "1.2.3", ["amd64", "arm64"]
    )
    assert names == [
        "circuit-breaker_1.2.3_linux_amd64.tar.gz",
        "circuit-breaker_1.2.3_linux_arm64.tar.gz",
    ]


def test_main_passes_when_every_asset_is_staged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for arch in ("amd64", "arm64"):
        (tmp_path / f"circuit-breaker_1.2.3_linux_{arch}.tar.gz").write_bytes(b"x")
    code = installer_assets.main(
        ["--installer", str(INSTALL_SH), "--version", "1.2.3", "--release-dir", str(tmp_path)]
    )
    assert code == 0, capsys.readouterr().out


def test_main_names_the_missing_asset(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "circuit-breaker_1.2.3_linux_amd64.tar.gz").write_bytes(b"x")
    code = installer_assets.main(
        ["--installer", str(INSTALL_SH), "--version", "1.2.3", "--release-dir", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "::error::" in out and "circuit-breaker_1.2.3_linux_arm64.tar.gz" in out


def test_main_fails_closed_when_install_sh_names_no_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text(PARAMETER, encoding="utf-8")
    code = installer_assets.main(
        ["--installer", str(installer), "--version", "1.2.3", "--release-dir", str(tmp_path)]
    )
    assert code == 1
    assert "::error::" in capsys.readouterr().out
