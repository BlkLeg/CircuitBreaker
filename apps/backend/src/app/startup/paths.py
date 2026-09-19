"""Resource-path resolution for the four layouts the backend has to run in.

A repo checkout, the mono/backend Docker image, a PyInstaller bundle and the
deb/rpm share tree all put ``alembic.ini`` and the docs seed somewhere
different, and the startup path has to find them without knowing which one it
is in.  The candidate lists live here rather than at each call site because
``run_alembic_upgrade`` and ``cb migrate`` must hand Alembic the *same* file —
``test_cli_migrate`` asserts they do, and two hand-maintained copies of the
list would be right only until the next packaging change.

Anchors are derived from this package's own location rather than from any one
module's ``__file__`` depth, so moving a caller between modules cannot silently
re-point them a directory up or down.
"""

import os
import sys
from pathlib import Path

#: ``.../src/app`` — the application package root.
APP_DIR = Path(__file__).resolve().parents[1]
#: ``.../apps/backend`` in a checkout, ``/app/backend`` in the Docker image.
BACKEND_DIR = APP_DIR.parents[1]
#: The repository root in a checkout; whatever sits two levels above the
#: backend elsewhere.  Only ever used to build candidates that are then
#: existence-checked, so a meaningless value in a packaged layout is harmless.
REPO_ROOT: Path | None = BACKEND_DIR.parents[1] if len(BACKEND_DIR.parents) > 1 else None

ALEMBIC_INI_FILENAME = "alembic.ini"
DOCS_SEED_FILENAME = "DocsPage.md"


def resolve_existing_path(*candidates: str | Path | None) -> Path | None:
    """Return the first candidate that exists on disk, or None."""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    return None


def share_dir_candidate(*parts: str) -> Path | None:
    """Path under ``CB_SHARE_DIR`` (deb/rpm share tree), when that is set."""
    share_dir = os.environ.get("CB_SHARE_DIR")
    return Path(share_dir).expanduser().joinpath(*parts) if share_dir else None


def bundle_share_candidate(*parts: str) -> Path:
    """Path under ``share/`` next to the running interpreter (native bundle)."""
    return Path(sys.executable).resolve().parent.joinpath("share", *parts)


def meipass_candidate(*parts: str) -> Path | None:
    """Path inside a PyInstaller one-file extraction directory, when running from one."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass).joinpath(*parts) if meipass else None


def alembic_ini_candidates() -> list[str | Path | None]:
    """Every place ``alembic.ini`` may live, most specific first.

    Shared by ``startup.schema.run_alembic_upgrade`` and ``cb migrate`` so the
    two cannot disagree about which config Alembic is run against.
    """
    candidates: list[str | Path | None] = [
        os.environ.get("ALEMBIC_CONFIG"),
        os.environ.get("CB_ALEMBIC_INI"),
        share_dir_candidate("backend", ALEMBIC_INI_FILENAME),
        bundle_share_candidate("backend", ALEMBIC_INI_FILENAME),
        meipass_candidate("backend", ALEMBIC_INI_FILENAME),
        BACKEND_DIR / ALEMBIC_INI_FILENAME,
    ]
    if REPO_ROOT is not None:
        candidates.append(REPO_ROOT / "apps" / "backend" / ALEMBIC_INI_FILENAME)
    return candidates


def docs_seed_candidates() -> list[str | Path | None]:
    """Every place the shipped ``DocsPage.md`` seed may live, most specific first."""
    candidates: list[str | Path | None] = [
        os.environ.get("CB_DOCS_SEED_FILE"),
        share_dir_candidate(DOCS_SEED_FILENAME),
        bundle_share_candidate(DOCS_SEED_FILENAME),
        meipass_candidate(DOCS_SEED_FILENAME),
        BACKEND_DIR / DOCS_SEED_FILENAME,
    ]
    if REPO_ROOT is not None:
        candidates.append(REPO_ROOT / DOCS_SEED_FILENAME)
    return candidates
