from unittest.mock import MagicMock, patch

import pytest

from app.services import discovery_reconciler as reconciler
from app.services.discovery_readiness import Capability, CapState


def _cap(key, state):
    return Capability(key=key, title=key, state=state, explanation="", reason_code="")


@pytest.fixture(autouse=True)
def _reset_state():
    reconciler.reset_reconciler_state_for_tests()
    yield
    reconciler.reset_reconciler_state_for_tests()


def test_reconcile_class1_heals_auto_fixable_nmap_present():
    caps = [
        _cap("nmap_present", CapState.AUTO_FIXABLE),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=True
        ),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_called_once()


def test_reconcile_class1_skips_when_already_ready():
    caps = [
        _cap("nmap_present", CapState.READY),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=True
        ),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
        patch("app.services.discovery_reconciler.helper_client.grant_nmap_caps") as grant_caps,
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_not_called()
        grant_caps.assert_not_called()


def test_reconcile_class1_skips_without_helper_installed():
    caps = [_cap("nmap_present", CapState.AUTO_FIXABLE), _cap("nmap_raw", CapState.READY)]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=False
        ),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_not_called()


def test_attempt_heal_backoff_after_threshold_failures():
    with patch("app.services.discovery_reconciler.log_worker_audit"):
        for _ in range(3):
            reconciler._attempt_heal(
                "nmap_present", "ensure_nmap", MagicMock(side_effect=RuntimeError("boom"))
            )
        state = reconciler._STATE["nmap_present"]
        assert state["failures"] == 3
        # Next _due() check should be gated by the longer backoff window,
        # i.e. not due again immediately.
        assert reconciler._due("nmap_present") is False


def test_attempt_heal_resets_backoff_on_success():
    with patch("app.services.discovery_reconciler.log_worker_audit"):
        reconciler._attempt_heal(
            "nmap_present", "ensure_nmap", MagicMock(side_effect=RuntimeError("boom"))
        )
        reconciler._attempt_heal("nmap_present", "ensure_nmap", MagicMock(return_value={}))
        state = reconciler._STATE["nmap_present"]
        assert state["failures"] == 0


def test_reconcile_class2_enables_when_desired_and_not_actual():
    caps = [_cap("arp_l2", CapState.NEEDS_HELPER_ACTION)]
    settings_row = MagicMock(lan_discovery_desired=True)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=True
        ),
        patch(
            "app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row
        ),
        patch("app.services.discovery_reconciler.helper_client.enable_lan_discovery") as enable,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class2(db=MagicMock())
        enable.assert_called_once()


def test_reconcile_class2_disables_when_not_desired_but_actual():
    caps = [_cap("arp_l2", CapState.READY)]
    settings_row = MagicMock(lan_discovery_desired=False)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=True
        ),
        patch(
            "app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row
        ),
        patch("app.services.discovery_reconciler.helper_client.disable_lan_discovery") as disable,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class2(db=MagicMock())
        disable.assert_called_once()


def test_reconcile_class2_noop_when_state_matches_desired():
    caps = [_cap("arp_l2", CapState.READY)]
    settings_row = MagicMock(lan_discovery_desired=True)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch(
            "app.services.discovery_reconciler.helper_client.helper_installed", return_value=True
        ),
        patch(
            "app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row
        ),
        patch("app.services.discovery_reconciler.helper_client.enable_lan_discovery") as enable,
        patch("app.services.discovery_reconciler.helper_client.disable_lan_discovery") as disable,
    ):
        reconciler._reconcile_class2(db=MagicMock())
        enable.assert_not_called()
        disable.assert_not_called()


def test_run_discovery_reconciliation_uses_advisory_lock():
    with patch("app.services.discovery_reconciler.run_with_advisory_lock") as lock:
        reconciler.run_discovery_reconciliation()
        lock.assert_called_once()
        assert lock.call_args.args[0] == "discovery_reconciler"
        assert "job_fn" in lock.call_args.kwargs


def test_attempt_heal_logs_entity_name_matching_capability_key_on_success():
    with patch("app.services.discovery_reconciler.log_worker_audit") as audit:
        reconciler._attempt_heal("nmap_present", "ensure_nmap", MagicMock(return_value={}))
        assert audit.call_args.kwargs["entity_name"] == "nmap_present"


def test_attempt_heal_logs_entity_name_matching_capability_key_on_failure():
    with patch("app.services.discovery_reconciler.log_worker_audit") as audit:
        reconciler._attempt_heal(
            "lan_discovery", "enable_lan_discovery", MagicMock(side_effect=RuntimeError("x"))
        )
        assert audit.call_args.kwargs["entity_name"] == "lan_discovery"
