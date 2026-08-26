"""The check runs on a loop and is cancelled with the other workers."""

import re
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "src/app/main.py"


def test_startup_uses_the_loop_not_the_deleted_one_shot():
    source = _MAIN.read_text()
    assert "run_update_check_loop" in source
    assert "log_update_notice" not in source, "the one-shot notice was removed in Task 4"


def test_the_task_is_registered_for_cancellation():
    """A bare create_task would leak past shutdown; _worker_tasks is cancelled
    at main.py:1426-1429."""
    source = _MAIN.read_text()
    pattern = r"_worker_tasks\.append\(\s*asyncio\.create_task\(\s*run_update_check_loop"
    match = re.search(pattern, source)
    assert match, "update loop must be appended to _worker_tasks"


def test_it_is_not_gated_on_in_process_workers():
    """The check is independent of CB_RUN_INPROCESS_WORKERS."""
    source = _MAIN.read_text()
    phase9 = source.split("Phase 9")[1].split("Phase 10")[0]
    assert "CB_RUN_INPROCESS_WORKERS" not in phase9
