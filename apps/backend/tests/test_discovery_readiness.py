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
