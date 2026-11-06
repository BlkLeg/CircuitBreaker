"""The backend's three dependency files must tell one story.

`apps/backend/pyproject.toml` declares the constraints, `poetry.lock` resolves
them, and `requirements.txt` is generated from the lock. Each file is consumed
by a different thing:

  * CI installs the backend with `pip install -e "apps/backend/[dev]"`, which
    reads pyproject.toml and ignores the lock entirely.
  * Every shipped image (`Dockerfile`, `Dockerfile.mono`,
    `docker/backend.Dockerfile`) installs `-r requirements.txt`.
  * The security gate's pip-audit step audits `requirements.txt`.

So a security floor raised in pyproject.toml reaches users only if the lock is
regenerated too, and an audit that passes on requirements.txt only speaks for
the images if that file still matches the lock it claims to come from. These
tests pin both halves.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
PYPROJECT = BACKEND / "pyproject.toml"
LOCK_FILE = BACKEND / "poetry.lock"
REQUIREMENTS = BACKEND / "requirements.txt"
GENERATOR = ROOT / "scripts" / "gen_requirements.py"

_PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^;\s]+)")


def _load_generator():
    """Import scripts/gen_requirements.py, which is a script, not a package."""
    spec = importlib.util.spec_from_file_location("gen_requirements", GENERATOR)
    assert spec and spec.loader, f"cannot load {GENERATOR}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pinned_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line.strip())
        if match:
            versions[canonicalize_name(match["name"])] = match["version"]
    return versions


def test_requirements_txt_still_matches_the_lock() -> None:
    """requirements.txt says "do not edit manually" and nothing enforced it.

    Hand-editing this file is the tempting fix when pip-audit fails the gate:
    it is the file pip-audit reads, so the gate goes green immediately. But the
    lock is still the source, so the next `python3 scripts/gen_requirements.py`
    silently restores the vulnerable pin — and the images, which install from
    this file, carry it in the meantime only if someone regenerates. Equally,
    bumping the lock and forgetting to regenerate leaves the audited file
    describing a dependency set no image actually installs.
    """
    expected = _load_generator().render(LOCK_FILE)
    actual = REQUIREMENTS.read_text(encoding="utf-8")
    assert actual == expected, (
        "apps/backend/requirements.txt is out of sync with poetry.lock. "
        "It is generated, not written: run `python3 scripts/gen_requirements.py` "
        "and commit the result, rather than editing the pins by hand."
    )


def test_every_pinned_version_satisfies_its_declared_constraint() -> None:
    """A floor raised in pyproject.toml must reach the images and the audit.

    anyio is why this exists: `anyio>=4.0,<4.15` resolved to 4.12.1 in the
    lock, and when CVE-2026-63374 / CVE-2026-64847 landed, the fix was to raise
    the floor to the fixed release. Raising it in pyproject.toml alone would
    have fixed the environment CI tests in and left the shipped images and the
    pip-audit input pinned to the vulnerable build, because neither reads
    pyproject.toml. This fails when the two disagree in either direction.
    """
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    pinned = _pinned_versions()

    violations: list[str] = []
    for spec in declared["dependencies"]:
        requirement = Requirement(spec)
        version = pinned.get(canonicalize_name(requirement.name))
        if version is None:
            continue
        if not requirement.specifier.contains(version, prereleases=True):
            violations.append(
                f"{requirement.name}: pyproject declares "
                f"'{requirement.specifier}' but requirements.txt pins {version}"
            )

    assert not violations, (
        "pyproject.toml and requirements.txt disagree. Re-run `poetry lock` in "
        "apps/backend and then `python3 scripts/gen_requirements.py`, so the "
        "constraint CI installs against and the pin the images install are the "
        "same decision:\n  " + "\n  ".join(violations)
    )


# pytest 9.2 deprecated `_pytest.python.CallSpec2`; anyio's pytest plugin
# imports it unconditionally until 4.15.1, which tries `CallSpec` first.
_FIRST_PYTEST_WITHOUT_CALLSPEC2 = "9.2.0"
_FIRST_ANYIO_WITH_CALLSPEC = "4.15.1"


def _declared_specifier(group: list[str], name: str) -> Requirement:
    """Return the single requirement for ``name`` declared in ``group``."""
    matches = [Requirement(spec) for spec in group if canonicalize_name(Requirement(spec).name) == name]
    assert len(matches) == 1, f"expected exactly one {name} requirement, found {len(matches)}"
    return matches[0]


def test_pytest_ceiling_tracks_the_anyio_ceiling() -> None:
    """pytest may only reach 9.2 once anyio may reach 4.15.1.

    CI installs `apps/backend/[dev]` from pyproject.toml without the lock, so
    the newest pytest the range allows is what CI runs. When pytest 9.2.0 was
    published, every backend shard, Lint and the fresh-install migration job
    went red at once: anyio 4.14.x's pytest plugin imports `CallSpec2`, the
    rename warning is an error under filterwarnings, and pytest exits 3
    before collecting a single test. anyio is held below 4.15 for starlette, so
    the two ceilings are one decision. This fails if pytest's range admits 9.2
    while anyio's range still excludes the release that copes with it.
    """
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    anyio = _declared_specifier(project["dependencies"], "anyio")
    pytest_req = _declared_specifier(project["optional-dependencies"]["dev"], "pytest")

    anyio_can_cope = anyio.specifier.contains(_FIRST_ANYIO_WITH_CALLSPEC, prereleases=True)
    pytest_reaches_rename = pytest_req.specifier.contains(_FIRST_PYTEST_WITHOUT_CALLSPEC2, prereleases=True)

    assert anyio_can_cope or not pytest_reaches_rename, (
        f"pyproject.toml allows pytest '{pytest_req.specifier}' but anyio "
        f"'{anyio.specifier}'. anyio below {_FIRST_ANYIO_WITH_CALLSPEC} cannot "
        f"load its pytest plugin on pytest >= {_FIRST_PYTEST_WITHOUT_CALLSPEC2}. "
        "Cap pytest below 9.2, or lift the anyio ceiling (and check starlette's "
        "TestClient) first."
    )
