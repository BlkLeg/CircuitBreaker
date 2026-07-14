from unittest.mock import patch


def test_nmap_binary_present_true_when_on_path():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value="/usr/bin/nmap"):
        assert nmap_binary_present() is True


def test_nmap_binary_present_false_when_missing():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value=None):
        assert nmap_binary_present() is False


def _mock_open_text(text):
    from unittest.mock import mock_open

    return mock_open(read_data=text)


def test_nmap_os_capable_true_with_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    # CapAmb with bit 13 set → 0x0000000000002000
    proc_status = "Name:\tpython\nCapAmb:\t0000000000002000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is True


def test_nmap_os_capable_false_without_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    proc_status = "Name:\tpython\nCapAmb:\t0000000000000000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is False


def test_readiness_all_ready_when_capable():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=True),
        patch.object(r, "_nmap_os_capable", return_value=True),
        patch.object(r, "_arp_available", return_value=True),
        patch.object(r, "detect_lan_adjacency", return_value=True),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert list(caps) == ["nmap_present", "nmap_raw", "arp_l2", "lan_adjacency"]
    assert caps["nmap_present"].state == r.CapState.READY
    assert caps["nmap_raw"].state == r.CapState.READY
    assert caps["arp_l2"].state == r.CapState.READY
    assert caps["lan_adjacency"].state == r.CapState.READY


def test_readiness_nmap_missing_is_auto_fixable():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=False),
        patch.object(r, "_nmap_os_capable", return_value=False),
        patch.object(r, "_arp_available", return_value=False),
        patch.object(r, "detect_lan_adjacency", return_value=True),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["nmap_present"].state == r.CapState.AUTO_FIXABLE
    assert caps["nmap_present"].explanation  # non-empty human text


def test_readiness_arp_needs_helper_when_no_adjacency():
    import app.services.discovery_readiness as r

    with (
        patch.object(r, "nmap_binary_present", return_value=True),
        patch.object(r, "_nmap_os_capable", return_value=True),
        patch.object(r, "_arp_available", return_value=False),
        patch.object(r, "detect_lan_adjacency", return_value=False),
    ):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["arp_l2"].state == r.CapState.NEEDS_HELPER_ACTION
    assert caps["lan_adjacency"].state == r.CapState.NEEDS_HELPER_ACTION
