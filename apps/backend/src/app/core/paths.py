"""Lazy resolution of the data and uploads directories.

Import-time consumers of these paths used to each compute their own
module-level ``Path`` constant and, in three places, ``mkdir`` it immediately.
That made importing the application fail whenever the caller could not write
to its own current working directory — concretely, ``--selftest`` run by an
unprivileged user (``cb doctor``, ``cb diag bundle``) from an arbitrary cwd,
which is exactly the case the installer journey's `runuser` check exercises.

Nothing here writes to disk. Callers create what they need at the point they
need it, the way `startup.bootstrap.validate_data_dir_writable` already does
for ``/data`` itself, or in whichever function does the actual write.

`data_dir()` mirrors the majority default already scattered across
`start.py`, `cli.py` and `vault_service.py`: ``CB_DATA_DIR`` if set, else
``Path.cwd() / "data"``. `uploads_dir()` mirrors `settings.uploads_dir`'s
historical meaning: an explicit override (``UPLOADS_DIR=/data/uploads`` in the
mono image) wins outright; left unset, uploads live under the data directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings


def data_dir() -> Path:
    """Where this process's persistent data lives. Never creates it."""
    return Path(os.environ.get("CB_DATA_DIR") or (Path.cwd() / "data")).expanduser()


def uploads_dir() -> Path:
    """Where user uploads live. Never creates it.

    An explicit ``settings.uploads_dir`` (from the ``UPLOADS_DIR`` env var)
    wins even when it disagrees with `data_dir()`. Left empty, uploads live at
    ``<data dir>/uploads``, matching every place this was hand-computed before.
    """
    override = settings.uploads_dir
    if override:
        return Path(override).expanduser()
    return data_dir() / "uploads"
