"""Settings.airgap must resolve from the documented CB_AIRGAP variable.

`Settings` sets no `env_prefix`, so a bare `airgap: bool = False` bound only the
un-prefixed `AIRGAP`. Everything an operator reads names the prefixed form:
`docs/installation/configuration.md` documents `CB_AIRGAP` as the air-gap
switch, `core/network_acl.py` names it in its own docstring, and
`docker-compose.yml` wires `CB_AIRGAP=${CB_AIRGAP:-false}` into the container.
An operator who set it believed active network scans were refused. They were
not -- `settings.airgap` stayed False and every scan ran.

These tests construct a fresh `Settings()` rather than monkeypatching the
module-level singleton. Monkeypatching `settings.airgap` is exactly what hid
the bug: every existing air-gap test set the attribute directly and so never
exercised the env-var binding at all.
"""

from app.core.config import Settings


def test_cb_airgap_sets_airgap(monkeypatch):
    monkeypatch.setenv("CB_AIRGAP", "true")
    assert Settings().airgap is True


def test_bare_airgap_still_sets_airgap(monkeypatch):
    """The un-prefixed form kept working; the alias adds CB_, it does not swap."""
    monkeypatch.delenv("CB_AIRGAP", raising=False)
    monkeypatch.setenv("AIRGAP", "true")
    assert Settings().airgap is True


def test_cb_airgap_wins_over_the_bare_form(monkeypatch):
    monkeypatch.setenv("CB_AIRGAP", "true")
    monkeypatch.setenv("AIRGAP", "false")
    assert Settings().airgap is True


def test_airgap_defaults_off(monkeypatch):
    monkeypatch.delenv("CB_AIRGAP", raising=False)
    monkeypatch.delenv("AIRGAP", raising=False)
    assert Settings().airgap is False
