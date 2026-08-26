"""How the app was installed, and what an operator should actually run."""

import pytest

from app.core import install_method


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("CB_INSTALL_METHOD", "APPIMAGE"):
        monkeypatch.delenv(var, raising=False)


def test_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("CB_INSTALL_METHOD", "deb")
    assert install_method.detect_install_method() == "deb"


def test_unrecognised_env_value_is_ignored(monkeypatch):
    """A typo must not invent a method the command table cannot serve."""
    monkeypatch.setenv("CB_INSTALL_METHOD", "banana")
    assert install_method.detect_install_method() != "banana"


def test_install_conf_supplies_the_mode(monkeypatch, tmp_path):
    conf = tmp_path / "install.conf"
    conf.write_text('CB_MODE="compose"\nCB_PORT=8088\n')
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", (conf,))
    assert install_method.detect_install_method() == "compose"


def test_appimage_env_is_recognised(monkeypatch, tmp_path):
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", ())
    monkeypatch.setenv("APPIMAGE", "/opt/circuit-breaker.AppImage")
    assert install_method.detect_install_method() == "appimage"


def test_unknown_when_nothing_identifies_the_install(monkeypatch):
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", ())
    monkeypatch.setattr(install_method, "_in_container", lambda: False)
    monkeypatch.setattr(install_method, "_package_owner", lambda: None)
    assert install_method.detect_install_method() == "unknown"


def test_every_method_has_a_command():
    for method in install_method.KNOWN_METHODS:
        assert install_method.upgrade_command(method, "1.0.0-rc.4").strip()


def test_command_names_the_target_version():
    assert "1.0.0-rc.4" in install_method.upgrade_command("compose", "1.0.0-rc.4")
    assert "1.0.0-rc.4" in install_method.upgrade_command("docker", "1.0.0-rc.4")


def test_unknown_method_gets_documentation_not_a_guess():
    command = install_method.upgrade_command("unknown", "1.0.0-rc.4")
    assert "http" in command
    assert "apt" not in command and "docker" not in command


def test_missing_target_still_returns_usable_text():
    assert install_method.upgrade_command("binary", None).strip()
