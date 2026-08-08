# apps/backend/tests/services/test_worker_dispatch.py
from app.workers.main import _TYPE_MAP


def test_monitor_worker_types_registered():
    assert _TYPE_MAP["4"] == "monitor_scheduler"
    assert _TYPE_MAP["5"] == "monitor_poll"
    assert _TYPE_MAP["6"] == "monitor_poll"
    assert _TYPE_MAP["7"] == "monitor_probe_dispatch"


def test_every_alias_names_a_worker_dispatch_can_actually_start():
    """The numeric aliases are what supervisord passes; an alias with no
    `_dispatch` branch crash-loops at startup with "Unknown worker type", which
    is exactly how the retired index 1 failed."""
    import inspect

    from app.workers import main

    source = inspect.getsource(main._dispatch)
    for kind in set(_TYPE_MAP.values()):
        assert f'== "{kind}"' in source, kind
