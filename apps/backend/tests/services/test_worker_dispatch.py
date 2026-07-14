# apps/backend/tests/services/test_worker_dispatch.py
from app.workers.main import _TYPE_MAP


def test_monitor_worker_types_registered():
    assert _TYPE_MAP["4"] == "monitor_scheduler"
    assert _TYPE_MAP["5"] == "monitor_poll"
    assert _TYPE_MAP["6"] == "monitor_poll"
