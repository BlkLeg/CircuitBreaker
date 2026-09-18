"""The check runs on a loop and is cancelled with the other workers."""

import re
from pathlib import Path

_WORKERS = Path(__file__).resolve().parents[2] / "src/app/startup/workers.py"


def test_startup_uses_the_loop_not_the_deleted_one_shot():
    source = _WORKERS.read_text()
    assert "run_update_check_loop" in source
    assert "log_update_notice" not in source, "the one-shot notice was replaced by the loop"


def test_the_task_is_registered_for_cancellation():
    """A bare create_task would leak past shutdown.

    `_worker_tasks` becomes `BackgroundTasks.tasks`, which
    `drain_background_tasks` cancels and gathers.
    """
    source = _WORKERS.read_text()
    pattern = r"_worker_tasks\.append\(\s*asyncio\.create_task\(\s*run_update_check_loop"
    match = re.search(pattern, source)
    assert match, "update loop must be appended to _worker_tasks"


def test_it_is_not_gated_on_in_process_workers():
    """The check is independent of CB_RUN_INPROCESS_WORKERS.

    Sliced between the two section banners that bracket the update check, so
    the assertion is about that block rather than the whole file.
    """
    source = _WORKERS.read_text()
    section = source.split("── Update check")[1].split("── Discovery readiness")[0]
    assert "CB_RUN_INPROCESS_WORKERS" not in section
