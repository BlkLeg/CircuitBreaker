from unittest.mock import patch


def test_nmap_binary_present_true_when_on_path():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value="/usr/bin/nmap"):
        assert nmap_binary_present() is True


def test_nmap_binary_present_false_when_missing():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value=None):
        assert nmap_binary_present() is False
