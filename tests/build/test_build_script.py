"""Unit tests for build_native_release.py packaging functions."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add scripts/ to path so we can import the build module
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import build_native_release as br


@pytest.fixture
def tmp_bundle(tmp_path):
    """Minimal bundle dir that satisfies packaging functions."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    binary = bundle / "circuit-breaker"
    binary.write_bytes(b"\x7fELF")  # fake ELF
    binary.chmod(0o755)
    share = bundle / "share" / "frontend"
    share.mkdir(parents=True)
    (share / "index.html").write_text("<html/>")
    return bundle


class TestCreateLinuxPackagesIncludesApk:
    def test_apk_format_is_in_nfpm_loop(self, tmp_path, tmp_bundle):
        """apk must be attempted alongside deb and rpm."""
        called_fmts = []

        def fake_run(cmd, **kwargs):
            if "nfpm" in cmd[0]:
                # Extract --packager value
                idx = cmd.index("--packager")
                called_fmts.append(cmd[idx + 1])
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("build_native_release.shutil.which", return_value="/usr/bin/nfpm"), \
             patch("build_native_release.subprocess.run", side_effect=fake_run), \
             patch("build_native_release.stage_nats_server", return_value="2.14.6"), \
             patch("build_native_release.shutil.copytree"), \
             patch("build_native_release.shutil.rmtree"):
            br.create_linux_packages(tmp_bundle, "0.1.3", "amd64", tmp_path)

        assert "deb" in called_fmts
        assert "rpm" in called_fmts
        assert "apk" in called_fmts

    def test_skips_when_nfpm_missing(self, tmp_path, tmp_bundle):
        with patch("build_native_release.shutil.which", return_value=None):
            result = br.create_linux_packages(tmp_bundle, "0.1.3", "amd64", tmp_path)
        assert result == []


class TestCreateAppimage:
    def test_skips_on_arm64(self, tmp_path, tmp_bundle):
        result = br.create_appimage(tmp_bundle, "0.1.3", "arm64", tmp_path)
        assert result is None

    def test_skips_when_appimagetool_missing(self, tmp_path, tmp_bundle):
        with patch("build_native_release.shutil.which", return_value=None):
            result = br.create_appimage(tmp_bundle, "0.1.3", "amd64", tmp_path)
        assert result is None

    def test_creates_appimage_on_success(self, tmp_path, tmp_bundle):
        expected = tmp_path / "circuit-breaker-0.1.3-x86_64.AppImage"
        expected.write_bytes(b"fake")

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            return r

        with patch("build_native_release.shutil.which", return_value="/usr/bin/appimagetool"), \
             patch("build_native_release.subprocess.run", side_effect=fake_run):
            result = br.create_appimage(tmp_bundle, "0.1.3", "amd64", tmp_path)

        assert result == expected

    def test_returns_none_on_failure(self, tmp_path, tmp_bundle):
        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stderr = "error"
            return r

        with patch("build_native_release.shutil.which", return_value="/usr/bin/appimagetool"), \
             patch("build_native_release.subprocess.run", side_effect=fake_run):
            result = br.create_appimage(tmp_bundle, "0.1.3", "amd64", tmp_path)

        assert result is None


class TestCreateArchPackage:
    def test_skips_when_makepkg_missing(self, tmp_path, tmp_bundle):
        with patch("build_native_release.shutil.which", return_value=None):
            result = br.create_arch_package(tmp_bundle, "0.1.3", "amd64", tmp_path,
                                            tmp_path / "bundle.tar.gz")
        assert result is None

    def test_skips_when_pkgbuild_missing(self, tmp_path, tmp_bundle):
        with patch("build_native_release.shutil.which", return_value="/usr/bin/makepkg"), \
             patch.object(br, "REPO_ROOT", tmp_path):
            result = br.create_arch_package(tmp_bundle, "0.1.3", "amd64", tmp_path,
                                            tmp_path / "bundle.tar.gz")
        assert result is None

    def test_returns_pkg_path_on_success(self, tmp_path, tmp_bundle):
        (tmp_path / "PKGBUILD").write_text(
            "pkgver=PLACEHOLDER\n"
            "source_x86_64=(\"https://example.com/bundle.tar.gz\")\n"
            "sha256sums_x86_64=('SKIP')\n"
        )
        fake_tarball = tmp_path / "circuit-breaker_0.1.3_amd64.tar.gz"
        fake_tarball.write_bytes(b"fake")

        def fake_run(cmd, **kwargs):
            # Simulate makepkg producing a .pkg.tar.zst
            pkgdest = Path(kwargs["env"]["PKGDEST"])
            (pkgdest / "circuit-breaker-0.1.3-1-x86_64.pkg.tar.zst").write_bytes(b"pkg")
            r = MagicMock()
            r.returncode = 0
            return r

        with patch("build_native_release.shutil.which", return_value="/usr/bin/makepkg"), \
             patch.object(br, "REPO_ROOT", tmp_path), \
             patch("build_native_release.subprocess.run", side_effect=fake_run):
            result = br.create_arch_package(
                tmp_bundle, "0.1.3", "amd64", tmp_path, fake_tarball
            )

        assert result is not None
        assert result.suffix == ".zst"


class TestDynamicImportHiddenImports:
    """gh#104: proxmoxer reaches its auth backend through
    ``importlib.import_module(f".backends.{backend}", "proxmoxer")``. PyInstaller
    builds its bundle from a static import graph, so that string was invisible and
    ``proxmoxer/backends/*.py`` was dropped from the frozen binary -- every Proxmox
    VE connection on a native install died with ModuleNotFoundError, while the
    build itself reported success. The build is the only place this can be caught.
    """

    @staticmethod
    def _fake_pyinstaller(monkeypatch, collected):
        """Install a stub PyInstaller.utils.hooks so the wiring is testable
        without PyInstaller present (it is a build-time dep, not a test one)."""
        import types

        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_submodules = lambda pkg: list(collected.get(pkg, []))
        utils = types.ModuleType("PyInstaller.utils")
        utils.hooks = hooks
        root = types.ModuleType("PyInstaller")
        root.utils = utils
        for name, mod in (
            ("PyInstaller", root),
            ("PyInstaller.utils", utils),
            ("PyInstaller.utils.hooks", hooks),
        ):
            monkeypatch.setitem(sys.modules, name, mod)

    def test_collects_the_submodules_static_analysis_cannot_see(self, monkeypatch):
        self._fake_pyinstaller(
            monkeypatch,
            {
                "proxmoxer": ["proxmoxer", "proxmoxer.backends", "proxmoxer.backends.https"],
                "apscheduler": ["apscheduler", "apscheduler.triggers.cron"],
            },
        )
        collected = br._collect_dynamic_import_hidden_imports()
        assert "proxmoxer.backends.https" in collected
        assert "apscheduler.triggers.cron" in collected

    def test_build_passes_them_to_pyinstaller_as_hidden_imports(self, monkeypatch, tmp_path):
        """The list is only worth collecting if it reaches the command line."""
        self._fake_pyinstaller(
            monkeypatch, {"proxmoxer": ["proxmoxer.backends.https"], "apscheduler": ["apscheduler"]}
        )
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            # PyInstaller's output is asserted to exist by build_binary.
            out = tmp_path / "pyinstaller-dist" / br.binary_name("linux")
            out.write_bytes(b"\x7fELF")

        monkeypatch.setattr(br, "run", fake_run)
        br.build_binary("linux", tmp_path)

        assert "--hidden-import=proxmoxer.backends.https" in captured["cmd"]

    def test_refuses_to_build_when_a_dynamic_package_is_absent(self, monkeypatch):
        """An empty result means the package is not installed. Failing here is the
        point: the old behaviour was a green build that broke in production."""
        self._fake_pyinstaller(monkeypatch, {"proxmoxer": [], "apscheduler": ["apscheduler"]})
        with pytest.raises(SystemExit, match="proxmoxer"):
            br._collect_dynamic_import_hidden_imports()

    @pytest.mark.skipif(
        importlib.util.find_spec("PyInstaller") is None, reason="PyInstaller not installed"
    )
    def test_the_real_collector_finds_the_backend_that_broke(self):
        """Guards the actual claim against the real installed proxmoxer, so a
        future proxmoxer layout change cannot silently reintroduce gh#104."""
        collected = br._collect_dynamic_import_hidden_imports()
        assert "proxmoxer.backends.https" in collected
