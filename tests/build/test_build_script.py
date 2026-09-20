"""Unit tests for build_native_release.py packaging functions."""
import importlib.util
import sys
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add scripts/ to path so we can import the build module
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import build_native_release as br

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"


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


class TestAsgiTargetHiddenImport:
    """The API server is the one module the frozen binary names in a string.

    ``start.py`` hands uvicorn ``"app.main:app"``; nothing imports that module,
    so PyInstaller's static graph never sees it. Until b0347b36 it rode along
    on ``from app.main import run_alembic_upgrade`` a few lines above -- an
    accident, not a contract. That refactor moved the helper to
    ``app.startup.schema``, the last static reference disappeared, and the
    0.4.2 binary shipped without the application it exists to serve: migrations
    ran, then every native install died on

        ERROR: Error loading ASGI app. Could not import module "app.main".

    Deriving the name from the call means a future rename of main.py moves the
    hidden import with it instead of silently emptying the binary again.
    """

    def test_collector_finds_the_module_the_entrypoint_serves(self):
        assert br._collect_asgi_target_hidden_imports() == ["app.main"]

    def test_build_passes_the_asgi_module_to_pyinstaller(self, monkeypatch, tmp_path):
        """Collecting it is only worth anything if it reaches the command line."""
        TestDynamicImportHiddenImports._fake_pyinstaller(
            monkeypatch, {"proxmoxer": ["proxmoxer.backends.https"], "apscheduler": ["apscheduler"]}
        )
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            out = tmp_path / "pyinstaller-dist" / br.binary_name("linux")
            out.write_bytes(b"\x7fELF")

        monkeypatch.setattr(br, "run", fake_run)
        br.build_binary("linux", tmp_path)

        assert "--hidden-import=app.main" in captured["cmd"]

    def test_refuses_to_build_when_the_entrypoint_serves_nothing(self, monkeypatch, tmp_path):
        """No ASGI target means either a rename this scan cannot see or an
        entrypoint that no longer starts a server. Both are build-stopping: a
        binary that boots into ImportFromStringError is worse than no binary."""
        stub = tmp_path / "start.py"
        stub.write_text("import uvicorn\n\n\ndef main():\n    return 0\n", encoding="utf-8")
        monkeypatch.setattr(br, "BACKEND_ENTRYPOINT", stub)
        with pytest.raises(SystemExit, match="ASGI"):
            br._collect_asgi_target_hidden_imports()

def test_build_runs_the_selftest_before_staging_the_bundle() -> None:
    """Cheapest disproof first.

    v0.4.0 failed artifact-smoke after every package and every image had already
    been built, on both architectures. v0.4.2 was not caught at all. A binary
    that cannot import its own application is disprovable in seconds, inside the
    job that produced it, before anything is staged or packaged.
    """
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "assert_binary_contains_application" in source, (
        "build_native_release.py does not assert the built binary contains the "
        "application. PyInstaller drops modules named only by strings, and the "
        "build is the cheapest place to find out."
    )
    build_binary_body = re.search(
        r"def build_binary\(.*?\n(?=\ndef )", source, re.DOTALL
    )
    assert build_binary_body, "build_binary() not found in build_native_release.py"
    assert "assert_binary_contains_application(binary_path)" in build_binary_body.group(0), (
        "assert_binary_contains_application exists but build_binary does not "
        "call it, so a build can still emit a binary with no application in it."
    )
