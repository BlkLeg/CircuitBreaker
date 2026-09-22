"""The test suite must never write uploads into the working tree.

Left unset, `settings.uploads_dir` derives to the relative "<data dir>/uploads"
(see `app.core.paths.uploads_dir`), so without the conftest redirect every
profile-photo test drops a real PNG into apps/backend/data/uploads/profiles/.
That residue destroys `git status` as a review signal. These tests pin the
redirect itself rather than the symptom, so they fail immediately if the env
override in pytest_configure is lost.
"""

from pathlib import Path

# Repo working tree root that must stay clean: <repo>/apps/backend.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_upload_root_is_outside_the_backend_working_tree() -> None:
    from app.core.paths import uploads_dir

    resolved = uploads_dir().resolve()
    assert resolved.is_absolute()
    assert not resolved.is_relative_to(_BACKEND_ROOT), (
        f"uploads_dir {resolved} is inside the working tree; the test suite "
        "would leave upload residue in apps/backend/data/"
    )


def test_profile_photo_dir_follows_the_redirected_upload_root() -> None:
    """auth_service resolves the profiles dir from app.core.paths.uploads_dir()
    on every call — prove it follows the conftest redirect rather than some
    other, stale value."""
    from app.core.paths import uploads_dir
    from app.services.auth_service import _profiles_dir

    assert _profiles_dir().resolve().is_relative_to(uploads_dir().resolve())
    assert not _profiles_dir().resolve().is_relative_to(_BACKEND_ROOT)
