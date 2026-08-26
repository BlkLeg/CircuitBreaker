# Update Detection and Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a running instance correctly detect that a newer release exists in its own channel, and show that fact to an admin in the UI with a command that actually works for how it was installed.

**Architecture:** Version ordering delegates to `packaging` (already a dependency). The channel decision is a pure function over `{channel: [versions]}` with no I/O, driven by a shared JSON fixture. A separate fetch layer builds those channel lists from the GitHub releases list, caches the verdict in memory, and refreshes on a jittered 24h loop. An admin-only endpoint serves the cache; a banner and a Settings panel render it.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, httpx, `packaging`, pytest (asyncio_mode=auto); React 18, Vitest.

**Spec:** `specs/2026-08-25-update-delivery-unity-design.md`

## Global Constraints

- **Never hand-roll version comparison.** `packaging==26.0` is declared in `apps/backend/requirements.txt:51`. Ordering must produce `0.3.4 < 1.0.0-rc.2 < 1.0.0-rc.4 < 1.0.0-rc.10 < 1.0.0`.
- **Prerelease definition is allowlist-shaped and must match `scripts/release_channel.py`:** a stable version is exactly `MAJOR.MINOR.PATCH`; anything else — including anything unparseable — is a prerelease. A typo must never be treated as stable.
- **Channel rule (spec D2):** current is a prerelease → `prerelease` channel; current is stable → `stable` channel.
- **A version absent from its channel list yields `unknown_version` and offers nothing** (spec §3.3). Never guess.
- **`settings.airgap` short-circuits before any socket is opened**, following `app/services/threat_feed.py:207`.
- **Outbound HTTP routes through `configured_egress_proxy_url()`** from `app/core/url_validation.py`, following `app/services/backup/s3_client.py:78`.
- **Cache is in-memory only.** Hardening §8: the container runs `read_only: true` with only `/data` writable. Never write a cache file.
- **The endpoint is admin-only** via `require_role("admin")` (hardening §1). No unauthenticated path, no synthetic admin.
- **The update check must never block startup or any request**, and never raise into a caller.
- Backend tests run from `apps/backend` (`cd apps/backend && pytest`), which has its own config: `pythonpath=["src"]`, `asyncio_mode="auto"`, `timeout=30`.
- **Never print a command that does not work today.** Task 3 encodes only commands verified against the current tree; spec stage 4 replaces them with `cb update` once `cb` supports it.

---

### Task 1: Version ordering

**Files:**
- Create: `apps/backend/src/app/core/version.py`
- Create: `apps/backend/tests/core/__init__.py`
- Test: `apps/backend/tests/core/test_version.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse(raw: str) -> Version | None`, `is_prerelease(raw: str) -> bool`, `is_newer(candidate: str, current: str) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/core/__init__.py` as an empty file, then `apps/backend/tests/core/test_version.py`:

```python
"""Ordering for this project's version scheme.

`1.0.0-rc.10` vs `1.0.0-rc.4` is the case that kills naive implementations:
string comparison and `split(".")` both rank rc.10 below rc.4. The old
update check truncated the prerelease away entirely, so rc.2 and rc.4 were
equal and no rc user was ever offered an upgrade.
"""
import importlib.util
from pathlib import Path

import pytest

from app.core import version

_ROOT = Path(__file__).resolve().parents[4]


def _load_release_channel():
    """scripts/ is a directory of entrypoints, not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "release_channel", _ROOT / "scripts/release_channel.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORDERED = ["0.3.3", "0.3.4", "1.0.0-rc.2", "1.0.0-rc.4", "1.0.0-rc.10", "1.0.0"]


def test_scheme_orders_correctly():
    assert sorted(ORDERED, key=version.parse) == ORDERED


def test_rc10_is_newer_than_rc4():
    assert version.is_newer("1.0.0-rc.10", "1.0.0-rc.4")
    assert not version.is_newer("1.0.0-rc.4", "1.0.0-rc.10")


def test_the_reported_regression():
    """An rc.2 instance must recognise rc.4 as newer."""
    assert version.is_newer("1.0.0-rc.4", "1.0.0-rc.2")


def test_stable_outranks_its_own_candidates():
    assert version.is_newer("1.0.0", "1.0.0-rc.4")


def test_v_prefix_is_tolerated():
    assert version.is_newer("v1.0.0-rc.4", "1.0.0-rc.2")


@pytest.mark.parametrize("raw", ["", "dev-abc1234", "not-a-version", "unknown"])
def test_unparseable_is_never_newer(raw):
    assert version.parse(raw) is None
    assert not version.is_newer(raw, "1.0.0-rc.2")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0.0", False),
        ("0.3.4", False),
        ("1.0.0-rc.4", True),
        ("1.0.0-alpha.1", True),
        # packaging would call these stable; the project's allowlist rule does not.
        ("1.0", True),
        ("1.0.0.post1", True),
        ("dev-abc1234", True),
        ("unknown", True),
    ],
)
def test_prerelease_uses_the_projects_allowlist_rule(raw, expected):
    assert version.is_prerelease(raw) is expected


@pytest.mark.parametrize(
    "raw",
    ["1.0.0", "0.3.4", "1.0.0-rc.4", "1.0.0-alpha.1", "1.0", "1.0.0.post1", "dev-abc1234"],
)
def test_agrees_with_release_channel(raw):
    """Build-time and run-time must not drift on what counts as a prerelease."""
    assert version.is_prerelease(raw) is _load_release_channel().is_prerelease(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/core/test_version.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.version'`

- [ ] **Step 3: Write minimal implementation**

Create `apps/backend/src/app/core/version.py`:

```python
"""One answer to 'which version is newer'.

Ordering delegates to `packaging`, which is already a declared dependency and
handles the case a hand-rolled comparator gets wrong: `1.0.0-rc.10` outranks
`1.0.0-rc.4`. The previous update check compared
`v.lstrip("v").split("-")[0]`, which collapsed every 1.0.0 candidate to
`(1, 0, 0)` and so could never report an rc.2 -> rc.4 upgrade.

`is_prerelease` deliberately does NOT use `Version.is_prerelease`. It mirrors
the allowlist rule in `scripts/release_channel.py` so the build-time and
run-time definitions cannot drift: `1.0` and `1.0.0.post1` are stable to
packaging but are not release versions this project publishes, and treating an
unrecognised string as stable is the failure that must never happen.
"""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

# A stable version is exactly MAJOR.MINOR.PATCH with no suffix.
_STABLE_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _clean(raw: str) -> str:
    return str(raw).strip().lstrip("vV")


def parse(raw: str) -> Version | None:
    """None for anything unparseable — an unknown version is never 'newer'."""
    try:
        return Version(_clean(raw))
    except (InvalidVersion, TypeError):
        return None


def is_prerelease(raw: str) -> bool:
    """True for anything that is not a bare MAJOR.MINOR.PATCH."""
    return not _STABLE_RE.match(_clean(raw))


def is_newer(candidate: str, current: str) -> bool:
    """True only when both parse and candidate sorts strictly above current."""
    left, right = parse(candidate), parse(current)
    if left is None or right is None:
        return False
    return left > right
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && pytest tests/core/test_version.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/core/version.py apps/backend/tests/core/
git commit -m "feat(version): order this project's version scheme correctly"
```

---

### Task 2: Channel selection

**Files:**
- Create: `tests/fixtures/update-channel-cases.json`
- Modify: `apps/backend/src/app/core/update_check.py` (replace `_parse_version`)
- Test: `apps/backend/tests/core/test_update_selection.py`

**Interfaces:**
- Consumes: `app.core.version.is_prerelease`, `is_newer`, `parse`.
- Produces: `UpdateVerdict(status: str, channel: str, available: str | None)`; `select_update(current: str, channels: dict[str, list[str]], withdrawn: Iterable[str] = ()) -> UpdateVerdict`; `channels_from_releases(releases: list[dict]) -> dict[str, list[str]]`.

`status` is `"ok"` or `"unknown_version"`. `available` is `None` when already newest.

- [ ] **Step 1: Write the shared fixture**

Create `tests/fixtures/update-channel-cases.json`. This file is the specification of the channel rule; spec §10 has a bash consumer execute the same cases in a later plan.

```json
{
  "comment": "Shared cases for the update channel rule (spec D2, section 10). Both the Python and the bash implementations must satisfy every case.",
  "cases": [
    {
      "name": "the reported regression: rc.2 is offered rc.4",
      "current": "1.0.0-rc.2",
      "channels": {
        "stable": ["0.3.4", "0.3.3"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "1.0.0-rc.1", "0.3.4", "0.3.3"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "prerelease", "available": "1.0.0-rc.4" }
    },
    {
      "name": "newest prerelease is offered nothing",
      "current": "1.0.0-rc.4",
      "channels": {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "0.3.4"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "prerelease", "available": null }
    },
    {
      "name": "a stable install is not pushed onto a candidate",
      "current": "0.3.4",
      "channels": {
        "stable": ["0.3.4", "0.3.3"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "0.3.4", "0.3.3"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "stable", "available": null }
    },
    {
      "name": "an older stable is offered the newest stable",
      "current": "0.3.3",
      "channels": {
        "stable": ["0.3.4", "0.3.3"],
        "prerelease": ["1.0.0-rc.4", "0.3.4", "0.3.3"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "stable", "available": "0.3.4" }
    },
    {
      "name": "rc.10 outranks rc.4",
      "current": "1.0.0-rc.4",
      "channels": {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.10", "1.0.0-rc.4", "0.3.4"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "prerelease", "available": "1.0.0-rc.10" }
    },
    {
      "name": "a withdrawn release is never offered",
      "current": "1.0.0-rc.2",
      "channels": {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "0.3.4"]
      },
      "withdrawn": ["1.0.0-rc.4"],
      "expected": { "status": "ok", "channel": "prerelease", "available": null }
    },
    {
      "name": "once stable ships, a candidate is offered it",
      "current": "1.0.0-rc.4",
      "channels": {
        "stable": ["1.0.0", "0.3.4"],
        "prerelease": ["1.0.0", "1.0.0-rc.4", "0.3.4"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "prerelease", "available": "1.0.0" }
    },
    {
      "name": "once stable ships, an old stable is offered it",
      "current": "0.3.4",
      "channels": {
        "stable": ["1.0.0", "0.3.4"],
        "prerelease": ["1.0.0", "1.0.0-rc.4", "0.3.4"]
      },
      "withdrawn": [],
      "expected": { "status": "ok", "channel": "stable", "available": "1.0.0" }
    },
    {
      "name": "a build the manifest does not list is not guessed at",
      "current": "1.0.0-dev",
      "channels": {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.4", "0.3.4"]
      },
      "withdrawn": [],
      "expected": { "status": "unknown_version", "channel": "prerelease", "available": null }
    },
    {
      "name": "an empty channel offers nothing and does not raise",
      "current": "1.0.0-rc.2",
      "channels": { "stable": [], "prerelease": [] },
      "withdrawn": [],
      "expected": { "status": "unknown_version", "channel": "prerelease", "available": null }
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/core/test_update_selection.py`:

```python
"""The channel rule, driven by the shared fixture (spec section 10)."""
import json
from pathlib import Path

import pytest

from app.core.update_check import UpdateVerdict, channels_from_releases, select_update

_CASES = json.loads(
    (Path(__file__).resolve().parents[4] / "tests/fixtures/update-channel-cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_shared_fixture_cases(case):
    verdict = select_update(case["current"], case["channels"], case["withdrawn"])
    assert verdict == UpdateVerdict(
        status=case["expected"]["status"],
        channel=case["expected"]["channel"],
        available=case["expected"]["available"],
    )


def test_channels_from_releases_splits_by_kind():
    releases = [
        {"tag_name": "v1.0.0-rc.4", "draft": False},
        {"tag_name": "v1.0.0-rc.2", "draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    assert channels_from_releases(releases) == {
        "stable": ["0.3.4"],
        "prerelease": ["1.0.0-rc.4", "1.0.0-rc.2", "0.3.4"],
    }


def test_channels_from_releases_skips_drafts_and_junk():
    releases = [
        {"tag_name": "v9.9.9", "draft": True},
        {"tag_name": "", "draft": False},
        {"draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    assert channels_from_releases(releases) == {"stable": ["0.3.4"], "prerelease": ["0.3.4"]}


def test_rc2_against_the_live_release_shape_is_offered_rc4():
    """End-to-end over the two pure functions, using the real API shape."""
    releases = [
        {"tag_name": "v1.0.0-rc.4", "draft": False},
        {"tag_name": "v1.0.0-rc.2", "draft": False},
        {"tag_name": "v1.0.0-rc.1", "draft": False},
        {"tag_name": "v0.3.4", "draft": False},
    ]
    verdict = select_update("1.0.0-rc.2", channels_from_releases(releases))
    assert verdict.available == "1.0.0-rc.4"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/core/test_update_selection.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'UpdateVerdict'`

- [ ] **Step 4: Write minimal implementation**

In `apps/backend/src/app/core/update_check.py`, delete `_parse_version` entirely and add above `check_for_update`:

```python
from dataclasses import dataclass
from typing import Iterable

from app.core import version as _version


@dataclass(frozen=True)
class UpdateVerdict:
    """status is 'ok' or 'unknown_version'; available is None when newest."""

    status: str
    channel: str
    available: str | None


def channels_from_releases(releases: list[dict]) -> dict[str, list[str]]:
    """Normalise a GitHub /releases list into per-channel version lists.

    Drafts are never installable. The `prerelease` channel holds everything,
    because a candidate install is offered the newest release of any kind
    (spec D2); `stable` holds only release versions.
    """
    versions: list[str] = []
    for entry in releases:
        if entry.get("draft"):
            continue
        tag = str(entry.get("tag_name") or "").strip().lstrip("vV")
        if tag:
            versions.append(tag)
    return {
        "stable": [v for v in versions if not _version.is_prerelease(v)],
        "prerelease": list(versions),
    }


def select_update(
    current: str,
    channels: dict[str, list[str]],
    withdrawn: Iterable[str] = (),
) -> UpdateVerdict:
    """Newest release in the caller's own channel. Pure — no I/O.

    A `current` that does not appear in its channel is a local or withdrawn
    build. There is no honest comparison to make, so nothing is offered
    (spec section 3.3) — guessing here is how someone gets pushed sideways
    onto a build that is not an upgrade.
    """
    channel = "prerelease" if _version.is_prerelease(current) else "stable"
    blocked = set(withdrawn)
    entries = [v for v in channels.get(channel, ()) if v not in blocked]

    if current not in entries:
        return UpdateVerdict(status="unknown_version", channel=channel, available=None)

    ranked = [v for v in entries if _version.parse(v) is not None]
    newest = max(ranked, key=_version.parse)
    available = newest if _version.is_newer(newest, current) else None
    return UpdateVerdict(status="ok", channel=channel, available=available)
```

Selecting with `max` rather than trusting list order keeps this correct even if a source emits an unsorted list.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && pytest tests/core/test_update_selection.py -v --no-cov`
Expected: PASS (13 passed)

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/update-channel-cases.json apps/backend/src/app/core/update_check.py apps/backend/tests/core/test_update_selection.py
git commit -m "feat(update): pick the newest release in the caller's own channel"
```

---

### Task 3: Install-method identity

**Files:**
- Create: `apps/backend/src/app/core/install_method.py`
- Test: `apps/backend/tests/core/test_install_method.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `detect_install_method() -> str`; `upgrade_command(method: str, target: str | None) -> str`. Methods: `binary`, `docker`, `compose`, `deb`, `rpm`, `apk`, `arch`, `appimage`, `unknown`.

**Why the commands look like this:** `cb update` is not offered yet. `cb:462` refuses binary installs outright, and `cb:57` pins `:latest`, which `release_channel.py` never grants to a prerelease — so `cb update` on a candidate is a downgrade. Every string below works against the tree as it stands today. Spec stage 4 replaces this mapping with `cb update` once `cb` earns it.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/core/test_install_method.py`:

```python
"""How the app was installed, and what an operator should actually run."""
import pytest

from app.core import install_method


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("CB_INSTALL_METHOD", "APPIMAGE"):
        monkeypatch.delenv(var, raising=False)


def test_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("CB_INSTALL_METHOD", "deb")
    assert install_method.detect_install_method() == "deb"


def test_unrecognised_env_value_is_ignored(monkeypatch):
    """A typo must not invent a method the command table cannot serve."""
    monkeypatch.setenv("CB_INSTALL_METHOD", "banana")
    assert install_method.detect_install_method() != "banana"


def test_install_conf_supplies_the_mode(monkeypatch, tmp_path):
    conf = tmp_path / "install.conf"
    conf.write_text('CB_MODE="compose"\nCB_PORT=8088\n')
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", (conf,))
    assert install_method.detect_install_method() == "compose"


def test_appimage_env_is_recognised(monkeypatch, tmp_path):
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", ())
    monkeypatch.setenv("APPIMAGE", "/opt/circuit-breaker.AppImage")
    assert install_method.detect_install_method() == "appimage"


def test_unknown_when_nothing_identifies_the_install(monkeypatch):
    monkeypatch.setattr(install_method, "_INSTALL_CONF_PATHS", ())
    monkeypatch.setattr(install_method, "_in_container", lambda: False)
    monkeypatch.setattr(install_method, "_package_owner", lambda: None)
    assert install_method.detect_install_method() == "unknown"


def test_every_method_has_a_command():
    for method in install_method.KNOWN_METHODS:
        assert install_method.upgrade_command(method, "1.0.0-rc.4").strip()


def test_command_names_the_target_version():
    assert "1.0.0-rc.4" in install_method.upgrade_command("compose", "1.0.0-rc.4")
    assert "1.0.0-rc.4" in install_method.upgrade_command("docker", "1.0.0-rc.4")


def test_unknown_method_gets_documentation_not_a_guess():
    command = install_method.upgrade_command("unknown", "1.0.0-rc.4")
    assert "http" in command
    assert "apt" not in command and "docker" not in command


def test_missing_target_still_returns_usable_text():
    assert install_method.upgrade_command("binary", None).strip()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/core/test_install_method.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.install_method'`

- [ ] **Step 3: Write minimal implementation**

Create `apps/backend/src/app/core/install_method.py`:

```python
"""How this instance was installed, and the upgrade command that fits it.

The UI must never print a command that fails, so the strings here are the
ones that work against the tree as it stands. `cb update` is deliberately
absent: `cb:462` refuses binary installs, and `cb:57` pins `:latest`, which
`scripts/release_channel.py` never grants to a prerelease -- so `cb update`
on a candidate today is a downgrade. Spec stage 4 replaces this table once
`cb` can be trusted.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KNOWN_METHODS = (
    "binary", "docker", "compose", "deb", "rpm", "apk", "arch", "appimage", "unknown",
)

_INSTALL_CONF_PATHS = (
    Path("/etc/circuit-breaker/install.conf"),
    Path.home() / ".circuit-breaker/install.conf",
)

_RELEASES = "https://github.com/BlkLeg/CircuitBreaker/releases"
_INSTALLER = "https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh"
_IMAGE = "ghcr.io/blkleg/circuitbreaker"

_MODE_RE = re.compile(r'^\s*CB_MODE\s*=\s*"?([A-Za-z]+)"?', re.MULTILINE)


def _mode_from_conf() -> str | None:
    for path in _INSTALL_CONF_PATHS:
        try:
            match = _MODE_RE.search(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if match and match.group(1) in KNOWN_METHODS:
            return match.group(1)
    return None


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _package_owner() -> str | None:
    """Ask the OS whether it owns this executable. Never raises."""
    target = sys.executable
    probes = (
        ("deb", ["dpkg", "-S", target]),
        ("rpm", ["rpm", "-qf", target]),
        ("apk", ["apk", "info", "--who-owns", target]),
    )
    for method, cmd in probes:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            # pacman also answers `rpm`-less systems via its own db; check it first.
            if method == "rpm" and shutil.which("pacman"):
                return "arch"
            return method
    return None


def detect_install_method() -> str:
    """First confident answer wins; `unknown` rather than a guess."""
    declared = os.environ.get("CB_INSTALL_METHOD", "").strip()
    if declared in KNOWN_METHODS:
        return declared

    mode = _mode_from_conf()
    if mode:
        return mode

    if os.environ.get("APPIMAGE", "").strip():
        return "appimage"

    owner = _package_owner()
    if owner:
        return owner

    if _in_container():
        return "docker"

    return "unknown"


def upgrade_command(method: str, target: str | None) -> str:
    """The command an operator runs. Verified against the current tree."""
    version = target or "<version>"
    table = {
        "binary": f"curl -fsSL {_INSTALLER} | sudo bash -s -- --upgrade",
        "docker": (
            f"docker pull {_IMAGE}:{version} && "
            f"docker rm -f circuitbreaker && cb start"
        ),
        "compose": f"CB_TAG={version} docker compose up -d --pull always",
        "deb": f"sudo apt-get install --only-upgrade circuit-breaker  # or: {_RELEASES}",
        "rpm": f"sudo dnf upgrade circuit-breaker  # or: {_RELEASES}",
        "apk": f"sudo apk upgrade circuit-breaker  # or: {_RELEASES}",
        "arch": "sudo pacman -Syu circuit-breaker",
        "appimage": f"Download the new AppImage and replace it in place: {_RELEASES}",
        "unknown": f"See the upgrade instructions at {_RELEASES}",
    }
    return table.get(method, table["unknown"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && pytest tests/core/test_install_method.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/core/install_method.py apps/backend/tests/core/test_install_method.py
git commit -m "feat(update): identify the install method and its upgrade command"
```

---

### Task 4: Fetch, cache, and the opt-out

**Files:**
- Modify: `apps/backend/src/app/core/update_check.py`
- Modify: `apps/backend/src/app/core/config.py:92` (add setting beside `airgap`)
- Modify: `docs/installation/configuration.md`
- Test: `apps/backend/tests/core/test_update_fetch.py`

**Interfaces:**
- Consumes: `select_update`, `channels_from_releases`, `detect_install_method`, `upgrade_command`.
- Produces: `UpdateState` (fields `status`, `current`, `available`, `channel`, `checked_at`, `etag`); `async refresh() -> UpdateState`; `current_state() -> UpdateState`; `reset_cache() -> None`.

`status` values: `ok`, `unknown_version`, `disabled`, `airgap`, `unreachable`, `never_checked`.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/core/test_update_fetch.py`:

```python
"""Fetching is allowed to fail; it is never allowed to lie or to block."""
import httpx
import pytest

from app.core import update_check


@pytest.fixture(autouse=True)
def _clean_cache():
    update_check.reset_cache()
    yield
    update_check.reset_cache()


RELEASES = [
    {"tag_name": "v1.0.0-rc.4", "draft": False},
    {"tag_name": "v1.0.0-rc.2", "draft": False},
    {"tag_name": "v0.3.4", "draft": False},
]


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_rc2_learns_about_rc4(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check, "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES)),
    )
    state = await update_check.refresh()
    assert state.status == "ok"
    assert state.available == "1.0.0-rc.4"
    assert state.checked_at is not None


async def test_airgap_opens_no_socket(monkeypatch):
    monkeypatch.setattr(update_check.settings, "airgap", True)

    def _boom():
        raise AssertionError("airgap must short-circuit before any socket")

    monkeypatch.setattr(update_check, "_transport", _boom)
    state = await update_check.refresh()
    assert state.status == "airgap"
    assert state.available is None


async def test_opt_out_opens_no_socket(monkeypatch):
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", False)

    def _boom():
        raise AssertionError("CB_UPDATE_CHECK=false must short-circuit")

    monkeypatch.setattr(update_check, "_transport", _boom)
    state = await update_check.refresh()
    assert state.status == "disabled"


async def test_network_failure_is_unreachable_not_up_to_date(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)

    def _handler(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    state = await update_check.refresh()
    assert state.status == "unreachable"
    assert state.available is None


async def test_a_previous_answer_survives_a_later_failure(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check, "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES)),
    )
    await update_check.refresh()

    def _handler(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    await update_check.refresh()
    assert update_check.current_state().available == "1.0.0-rc.4"


async def test_304_keeps_the_cached_answer(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check, "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json=RELEASES, headers={"ETag": "abc"})),
    )
    await update_check.refresh()

    seen = {}

    def _handler(request):
        seen["inm"] = request.headers.get("If-None-Match")
        return httpx.Response(304)

    monkeypatch.setattr(update_check, "_transport", lambda: _transport(_handler))
    state = await update_check.refresh()
    assert seen["inm"] == "abc"
    assert state.available == "1.0.0-rc.4"


async def test_garbage_payload_does_not_raise(monkeypatch):
    monkeypatch.setattr(update_check.settings, "app_version", "1.0.0-rc.2")
    monkeypatch.setattr(update_check.settings, "airgap", False)
    monkeypatch.setattr(update_check.settings, "update_check", True)
    monkeypatch.setattr(
        update_check, "_transport",
        lambda: _transport(lambda r: httpx.Response(200, json={"message": "rate limited"})),
    )
    state = await update_check.refresh()
    assert state.status == "unreachable"


def test_state_before_any_check_is_never_checked():
    assert update_check.current_state().status == "never_checked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/core/test_update_fetch.py -v --no-cov`
Expected: FAIL — `AttributeError: module 'app.core.update_check' has no attribute 'reset_cache'`

- [ ] **Step 3: Add the setting**

In `apps/backend/src/app/core/config.py`, directly below `airgap: bool = False` (line 92):

```python
    # Outbound release check. Distinct from `airgap`: an operator may allow
    # scanning egress while still declining to contact GitHub. Either one off
    # disables the check.
    update_check: bool = True
```

In `docs/installation/configuration.md`, add a row to the same table that documents `CB_AIRGAP`:

```markdown
| `CB_UPDATE_CHECK` | `true` | Daily check for a newer release in this install's channel. When `false`, no outbound request is made and the UI reports that checking is disabled. `CB_AIRGAP=true` also disables it. |
```

- [ ] **Step 4: Write the implementation**

Replace the body of `check_for_update`/`log_update_notice` in `apps/backend/src/app/core/update_check.py` with:

```python
"""Non-blocking release check.

Two defects made this dead code for the whole 1.0.0-rc window. It asked
`/releases/latest`, which resolves through GitHub's "Latest release" badge and
names the newest *stable* release -- `v0.3.4` throughout the rc window. And it
compared `v.lstrip("v").split("-")[0]`, so `1.0.0-rc.2` and `1.0.0-rc.4` were
both `(1, 0, 0)` and no candidate install could ever be told to upgrade.

The cache is in-memory by design: hardening section 8 runs the container
`read_only: true` with only `/data` writable.
"""

import asyncio
import logging
import random
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.install_method import detect_install_method, upgrade_command
from app.core.url_validation import configured_egress_proxy_url

logger = logging.getLogger("circuitbreaker.update_check")

GITHUB_RELEASES_URL = "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases"
CHECK_TIMEOUT = 5
CHECK_INTERVAL_S = 24 * 60 * 60
JITTER_S = 30 * 60


@dataclass(frozen=True)
class UpdateState:
    status: str = "never_checked"
    current: str = ""
    available: str | None = None
    channel: str = ""
    checked_at: str | None = None
    etag: str | None = None


_state = UpdateState()


def current_state() -> UpdateState:
    return _state


def reset_cache() -> None:
    """Test seam."""
    global _state
    _state = UpdateState()


def _transport() -> httpx.AsyncBaseTransport | None:
    """Test seam; None means httpx's default transport."""
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def refresh() -> UpdateState:
    """Refresh the cached verdict. Never raises, never blocks a caller."""
    global _state
    current = settings.app_version

    if settings.airgap:
        _state = replace(_state, status="airgap", current=current, available=None)
        return _state
    if not settings.update_check:
        _state = replace(_state, status="disabled", current=current, available=None)
        return _state

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"circuit-breaker/{current}",
    }
    if _state.etag:
        headers["If-None-Match"] = _state.etag

    kwargs = {"timeout": CHECK_TIMEOUT, "headers": headers}
    proxy = configured_egress_proxy_url()
    if proxy:
        kwargs["proxy"] = proxy
    transport = _transport()
    if transport is not None:
        kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(GITHUB_RELEASES_URL)
            if resp.status_code == 304:
                _state = replace(_state, checked_at=_now())
                return _state
            if resp.status_code != 200:
                raise httpx.HTTPError(f"status {resp.status_code}")
            payload = resp.json()
            if not isinstance(payload, list):
                raise httpx.HTTPError("release list was not a list")
            verdict = select_update(current, channels_from_releases(payload))
            _state = UpdateState(
                status=verdict.status,
                current=current,
                available=verdict.available,
                channel=verdict.channel,
                checked_at=_now(),
                etag=resp.headers.get("ETag") or _state.etag,
            )
    except Exception as exc:  # network, JSON, schema — all the same to a caller
        logger.debug("Update check failed: %s", exc)
        _state = replace(_state, status="unreachable", current=current, checked_at=_now())
    return _state


async def run_update_check_loop() -> None:
    """Check now, then once a day with jitter until cancelled."""
    while True:
        state = await refresh()
        if state.available:
            logger.info(
                "A newer version of Circuit Breaker is available: %s (current: %s). "
                "To upgrade: %s",
                state.available,
                state.current,
                upgrade_command(detect_install_method(), state.available),
            )
        try:
            await asyncio.sleep(CHECK_INTERVAL_S + random.uniform(0, JITTER_S))
        except asyncio.CancelledError:
            raise
```

Delete `check_for_update` and `log_update_notice`; Task 5 replaces their only call site.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/backend && pytest tests/core/ -v --no-cov`
Expected: PASS (all Task 1-4 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/core/update_check.py apps/backend/src/app/core/config.py apps/backend/tests/core/test_update_fetch.py docs/installation/configuration.md
git commit -m "feat(update): daily cached release check, airgap- and proxy-aware"
```

---

### Task 5: Wire the scheduler

**Files:**
- Modify: `apps/backend/src/app/main.py:1384-1389`
- Test: `apps/backend/tests/core/test_update_lifespan.py`

**Interfaces:**
- Consumes: `run_update_check_loop`.
- Produces: nothing new; the task joins `_worker_tasks` so `main.py:1426-1429` cancels it.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/core/test_update_lifespan.py`:

```python
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
    match = re.search(r"_worker_tasks\.append\(\s*asyncio\.create_task\(\s*run_update_check_loop", source)
    assert match, "update loop must be appended to _worker_tasks"


def test_it_is_not_gated_on_in_process_workers():
    """The check is independent of CB_RUN_INPROCESS_WORKERS."""
    source = _MAIN.read_text()
    phase9 = source.split("Phase 9")[1].split("Phase 10")[0]
    assert "CB_RUN_INPROCESS_WORKERS" not in phase9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/core/test_update_lifespan.py -v --no-cov`
Expected: FAIL — `assert "run_update_check_loop" in source`

- [ ] **Step 3: Write the implementation**

Replace `apps/backend/src/app/main.py:1384-1389` with:

```python
    # ── Phase 9: Update check (non-blocking, daily) ─────────────────────
    # Appended to _worker_tasks so shutdown cancels it. Deliberately outside
    # the CB_RUN_INPROCESS_WORKERS branch: knowing the build is stale is not
    # a worker concern.
    try:
        from app.core.update_check import run_update_check_loop

        _worker_tasks.append(asyncio.create_task(run_update_check_loop()))
    except Exception:
        pass  # Never let update check affect startup
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && pytest tests/core/test_update_lifespan.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/main.py apps/backend/tests/core/test_update_lifespan.py
git commit -m "feat(update): run the release check on a cancellable daily loop"
```

---

### Task 6: The endpoint

**Files:**
- Create: `apps/backend/src/app/api/system.py`
- Modify: `apps/backend/src/app/main.py:1542+` (router registration)
- Test: `apps/backend/tests/api/test_system_update.py`

**Interfaces:**
- Consumes: `current_state`, `detect_install_method`, `upgrade_command`.
- Produces: `GET /api/v1/system/update`, admin-only.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/api/test_system_update.py`. Fixtures come from `apps/backend/tests/conftest.py`: `client` is async (`await client.get(...)`), `auth_headers` is an admin, `viewer_headers` is a viewer. `asyncio_mode="auto"`, so async tests need no decorator.

```python
"""The update endpoint: admin-only, cache-only, honest about its status."""
from app.core import update_check


async def test_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/system/update", headers=viewer_headers)
    assert resp.status_code == 403


async def test_rejects_anonymous(client):
    resp = await client.get("/api/v1/system/update")
    assert resp.status_code in (401, 403)


async def test_reports_an_available_update(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        update_check, "_state",
        update_check.UpdateState(
            status="ok", current="1.0.0-rc.2", available="1.0.0-rc.4",
            channel="prerelease", checked_at="2026-08-25T21:00:00+00:00",
        ),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["update_available"] is True
    assert body["available"] == "1.0.0-rc.4"
    assert body["channel"] == "prerelease"
    assert body["upgrade_command"].strip()
    assert body["release_url"].endswith("/v1.0.0-rc.4")


async def test_up_to_date_is_not_an_update(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        update_check, "_state",
        update_check.UpdateState(status="ok", current="1.0.0-rc.4", available=None,
                                 channel="prerelease", checked_at="2026-08-25T21:00:00+00:00"),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["update_available"] is False
    assert body["release_url"] is None


async def test_disabled_is_not_reported_as_up_to_date(client, auth_headers, monkeypatch):
    """An operator who turned the check off must not read 'you are current'."""
    monkeypatch.setattr(
        update_check, "_state",
        update_check.UpdateState(status="disabled", current="1.0.0-rc.2"),
    )
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "disabled"
    assert body["update_available"] is False


async def test_serves_cache_without_touching_the_network(client, auth_headers, monkeypatch):
    def _boom():
        raise AssertionError("the endpoint must never fetch")

    monkeypatch.setattr(update_check, "_transport", _boom)
    monkeypatch.setattr(update_check, "_state", update_check.UpdateState(status="never_checked"))
    resp = await client.get("/api/v1/system/update", headers=auth_headers)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && pytest tests/api/test_system_update.py -v --no-cov`
Expected: FAIL — 404, the route does not exist

- [ ] **Step 3: Write the implementation**

Create `apps/backend/src/app/api/system.py`:

```python
"""System-level status the UI needs. Cache-only; never does I/O per request."""

from typing import Annotated

from fastapi import APIRouter

from app.core import update_check
from app.core.install_method import detect_install_method, upgrade_command
from app.core.rbac import require_role

router = APIRouter()

_RELEASE_TAG_URL = "https://github.com/BlkLeg/CircuitBreaker/releases/tag/v{version}"


@router.get("/update")
async def get_update_status(_: Annotated[None, require_role("admin")] = None) -> dict:
    """What the cached check last concluded, and what to run about it."""
    state = update_check.current_state()
    method = detect_install_method()
    return {
        "current": state.current or "",
        "available": state.available,
        "update_available": bool(state.available),
        "channel": state.channel,
        "install_method": method,
        "upgrade_command": upgrade_command(method, state.available),
        "release_url": _RELEASE_TAG_URL.format(version=state.available) if state.available else None,
        "enabled": state.status not in ("disabled", "airgap"),
        "checked_at": state.checked_at,
        "status": state.status,
    }
```

Register it in `apps/backend/src/app/main.py` beside the other `include_router` calls:

```python
app.include_router(
    system.router,
    prefix=f"{_V1}/system",
    tags=["system"],
    dependencies=[Depends(require_auth)],
)
```

Add `system` to the API import block at the top of `main.py` alongside its siblings.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && pytest tests/api/test_system_update.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/api/system.py apps/backend/src/app/main.py apps/backend/tests/api/test_system_update.py
git commit -m "feat(api): serve the cached update verdict to admins"
```

---

### Task 7: The banner

**Files:**
- Modify: `apps/frontend/src/api/client.jsx:348` (extend `adminApi`)
- Create: `apps/frontend/src/hooks/useUpdateStatus.js`
- Create: `apps/frontend/src/components/UpdateBanner.jsx`
- Modify: `apps/frontend/src/App.jsx:124`
- Test: `apps/frontend/src/__tests__/UpdateBanner.test.jsx`

**Interfaces:**
- Consumes: `GET /api/v1/system/update`; `isAdmin` from `utils/rbac`; `useAuth` from `context/AuthContext.jsx`.
- Produces: `useUpdateStatus()` returning `{ status, loading }`; default-exported `UpdateBanner`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/UpdateBanner.test.jsx`. Read a neighbouring test such as `server-lifecycle-banner.test.jsx` first and reuse its render helpers and mocking style.

```jsx
/**
 * The banner is the surface that ends silent stranding. It must appear for an
 * admin on a stale build, stay hidden otherwise, and come back when a NEWER
 * release lands after a dismissal.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

const mockGetUpdate = vi.fn();
vi.mock('../api/client.jsx', () => ({
  adminApi: { updateStatus: (...a) => mockGetUpdate(...a) },
}));

const mockUser = { current: { role: 'admin' } };
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser.current }),
}));

import UpdateBanner from '../components/UpdateBanner.jsx';

const AVAILABLE = {
  current: '1.0.0-rc.2',
  available: '1.0.0-rc.4',
  update_available: true,
  channel: 'prerelease',
  install_method: 'binary',
  upgrade_command: 'curl -fsSL https://example/install.sh | sudo bash -s -- --upgrade',
  release_url: 'https://github.com/BlkLeg/CircuitBreaker/releases/tag/v1.0.0-rc.4',
  enabled: true,
  checked_at: '2026-08-25T21:00:00+00:00',
  status: 'ok',
};

beforeEach(() => {
  localStorage.clear();
  mockUser.current = { role: 'admin' };
  mockGetUpdate.mockReset();
  mockGetUpdate.mockResolvedValue({ data: AVAILABLE });
});

test('shows the available version and the command for this install', async () => {
  render(<UpdateBanner />);
  expect(await screen.findByText(/1\.0\.0-rc\.4/)).toBeInTheDocument();
  expect(screen.getByText(/sudo bash -s -- --upgrade/)).toBeInTheDocument();
});

test('renders nothing when up to date', async () => {
  mockGetUpdate.mockResolvedValue({
    data: { ...AVAILABLE, available: null, update_available: false, release_url: null },
  });
  const { container } = render(<UpdateBanner />);
  await vi.waitFor(() => expect(mockGetUpdate).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test('renders nothing for a non-admin and never calls the admin endpoint', async () => {
  mockUser.current = { role: 'viewer' };
  const { container } = render(<UpdateBanner />);
  await Promise.resolve();
  expect(mockGetUpdate).not.toHaveBeenCalled();
  expect(container).toBeEmptyDOMElement();
});

test('dismissal hides it', async () => {
  render(<UpdateBanner />);
  await userEvent.click(await screen.findByRole('button', { name: /dismiss/i }));
  expect(screen.queryByText(/1\.0\.0-rc\.4/)).not.toBeInTheDocument();
});

test('a dismissal does not suppress a later, newer release', async () => {
  localStorage.setItem('cb.updateDismissed', '1.0.0-rc.4');
  mockGetUpdate.mockResolvedValue({
    data: { ...AVAILABLE, available: '1.0.0-rc.5' },
  });
  render(<UpdateBanner />);
  expect(await screen.findByText(/1\.0\.0-rc\.5/)).toBeInTheDocument();
});

test('a dismissal does suppress the same release', async () => {
  localStorage.setItem('cb.updateDismissed', '1.0.0-rc.4');
  const { container } = render(<UpdateBanner />);
  await vi.waitFor(() => expect(mockGetUpdate).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/UpdateBanner.test.jsx`
Expected: FAIL — cannot resolve `../components/UpdateBanner.jsx`

- [ ] **Step 3: Write the implementation**

Add to `adminApi` in `apps/frontend/src/api/client.jsx`:

```javascript
  updateStatus: () => client.get('/system/update'),
```

Create `apps/frontend/src/hooks/useUpdateStatus.js`:

```javascript
import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../api/client.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { isAdmin } from '../utils/rbac';

const REFRESH_MS = 60 * 60 * 1000;

/**
 * The cached update verdict. Admin-only: the endpoint is admin-scoped, so a
 * viewer must not call it and take a 403 on every page load.
 */
export function useUpdateStatus() {
  const { user } = useAuth();
  const allowed = isAdmin(user);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(allowed);

  const load = useCallback(async () => {
    if (!allowed) return;
    try {
      const resp = await adminApi.updateStatus();
      setStatus(resp?.data ?? null);
    } catch {
      setStatus(null); // an unreachable endpoint is not an update claim
    } finally {
      setLoading(false);
    }
  }, [allowed]);

  useEffect(() => {
    if (!allowed) {
      setStatus(null);
      setLoading(false);
      return undefined;
    }
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [allowed, load]);

  return { status, loading };
}

export default useUpdateStatus;
```

Create `apps/frontend/src/components/UpdateBanner.jsx`:

```jsx
import React, { useState } from 'react';
import { ArrowUpCircle, X } from 'lucide-react';
import { useUpdateStatus } from '../hooks/useUpdateStatus.js';

const DISMISS_KEY = 'cb.updateDismissed';

function readDismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null; // private mode / blocked storage must not break the banner
  }
}

/**
 * Admin-only notice that a newer release exists in this install's channel.
 *
 * Dismissal is stored per-version, not as a boolean: dismissing rc.4 must not
 * hide rc.5. Silent stranding is the bug this component exists to prevent.
 */
export default function UpdateBanner() {
  const { status } = useUpdateStatus();
  const [dismissed, setDismissed] = useState(() => readDismissed());

  if (!status?.update_available || !status.available) return null;
  if (dismissed === status.available) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, status.available);
    } catch {
      /* storage unavailable — hide for this session only */
    }
    setDismissed(status.available);
  };

  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 16px',
        background: 'var(--color-info-bg, #1e3a5f)',
        color: 'var(--color-text, #e5e7eb)',
        fontSize: 13,
      }}
    >
      <ArrowUpCircle size={16} aria-hidden="true" />
      <span>
        <strong>{status.available}</strong> is available — you are on {status.current}.
      </span>
      <code style={{ opacity: 0.85 }}>{status.upgrade_command}</code>
      {status.release_url && (
        <a href={status.release_url} target="_blank" rel="noreferrer noopener">
          Release notes
        </a>
      )}
      <button type="button" onClick={dismiss} aria-label="Dismiss" style={{ marginLeft: 'auto' }}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
```

Mount it in `apps/frontend/src/App.jsx`, importing beside `MasqueradeBanner` (line 23) and rendering directly after it (line 124):

```jsx
      <MasqueradeBanner />
      <UpdateBanner />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/UpdateBanner.test.jsx`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/api/client.jsx apps/frontend/src/hooks/useUpdateStatus.js apps/frontend/src/components/UpdateBanner.jsx apps/frontend/src/App.jsx apps/frontend/src/__tests__/UpdateBanner.test.jsx
git commit -m "feat(ui): surface an available update to admins"
```

---

### Task 8: The Settings panel

**Files:**
- Create: `apps/frontend/src/components/settings/UpdateStatusPanel.jsx`
- Modify: `apps/frontend/src/pages/SettingsPage.jsx:1740-1748` (the `system` tab's About section)
- Test: `apps/frontend/src/__tests__/UpdateStatusPanel.test.jsx`

**Interfaces:**
- Consumes: `useUpdateStatus()` from Task 7.
- Produces: default-exported `UpdateStatusPanel`.

**No new tab.** `SETTINGS_TABS` already has a `system` entry (`SettingsNav.jsx:69`), and `SettingsPage.jsx:1742` already renders a `SettingSection title="About"`. That section currently shows `import.meta.env.VITE_APP_VERSION || 'dev'` — a build-time variable that reads `dev` in any build that did not set it, and which cannot know whether a newer release exists. This task replaces that paragraph with the live panel.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/UpdateStatusPanel.test.jsx`:

```jsx
/**
 * The permanent home for version facts, so dismissing the banner does not
 * destroy the only place they are visible.
 */
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

const mockStatus = { current: null };
vi.mock('../hooks/useUpdateStatus.js', () => ({
  useUpdateStatus: () => ({ status: mockStatus.current, loading: false }),
}));

import UpdateStatusPanel from '../components/settings/UpdateStatusPanel.jsx';

test('shows installed and available versions and the command', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2', available: '1.0.0-rc.4', update_available: true,
    channel: 'prerelease', install_method: 'binary',
    upgrade_command: 'sudo bash install.sh --upgrade',
    release_url: 'https://example/tag/v1.0.0-rc.4', enabled: true,
    checked_at: '2026-08-25T21:00:00+00:00', status: 'ok',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText('1.0.0-rc.2')).toBeInTheDocument();
  expect(screen.getByText('1.0.0-rc.4')).toBeInTheDocument();
  expect(screen.getByText(/sudo bash install\.sh --upgrade/)).toBeInTheDocument();
});

test('says checking is disabled rather than implying up to date', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2', available: null, update_available: false,
    channel: 'prerelease', install_method: 'binary', upgrade_command: 'x',
    release_url: null, enabled: false, checked_at: null, status: 'disabled',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText(/disabled/i)).toBeInTheDocument();
  expect(screen.queryByText(/up to date/i)).not.toBeInTheDocument();
});

test('says it could not reach the release source', () => {
  mockStatus.current = {
    current: '1.0.0-rc.2', available: null, update_available: false,
    channel: 'prerelease', install_method: 'binary', upgrade_command: 'x',
    release_url: null, enabled: true, checked_at: '2026-08-25T21:00:00+00:00',
    status: 'unreachable',
  };
  render(<UpdateStatusPanel />);
  expect(screen.getByText(/could not/i)).toBeInTheDocument();
});

test('renders nothing rather than a broken panel when status is unavailable', () => {
  mockStatus.current = null;
  const { container } = render(<UpdateStatusPanel />);
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/frontend && npx vitest run src/__tests__/UpdateStatusPanel.test.jsx`
Expected: FAIL — cannot resolve `../components/settings/UpdateStatusPanel.jsx`

- [ ] **Step 3: Write the implementation**

Create `apps/frontend/src/components/settings/UpdateStatusPanel.jsx`:

```jsx
import React from 'react';
import { useUpdateStatus } from '../../hooks/useUpdateStatus.js';

const STATUS_TEXT = {
  ok: 'Up to date.',
  disabled: 'Update checking is disabled (CB_UPDATE_CHECK=false).',
  airgap: 'Update checking is disabled by air-gap mode.',
  unreachable: 'Could not reach the release source at the last check.',
  never_checked: 'No check has run yet.',
  unknown_version: 'This build is not a published release, so no comparison was made.',
};

function Row({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value ?? '—'}</span>
    </div>
  );
}

/**
 * Permanent home for version facts. Each status renders its own sentence:
 * "disabled" and "unreachable" must never read as "you are up to date".
 */
export default function UpdateStatusPanel() {
  const { status } = useUpdateStatus();
  if (!status) return null;

  const summary = status.update_available
    ? `Version ${status.available} is available.`
    : STATUS_TEXT[status.status] || STATUS_TEXT.never_checked;

  return (
    <div>
      <Row label="Installed version" value={status.current} />
      <Row label="Available version" value={status.available} />
      <Row label="Channel" value={status.channel} />
      <Row label="Install method" value={status.install_method} />
      <Row label="Last checked" value={status.checked_at} />
      <p style={{ fontSize: 13, marginTop: 8 }}>{summary}</p>
      {status.update_available && (
        <>
          <p style={{ fontSize: 13, marginBottom: 4 }}>To upgrade:</p>
          <code style={{ display: 'block', padding: 8, background: 'var(--color-bg-subtle, #111827)' }}>
            {status.upgrade_command}
          </code>
        </>
      )}
    </div>
  );
}
```

In `apps/frontend/src/pages/SettingsPage.jsx`, import the panel alongside the other settings components, then replace the body of the existing About section (lines 1742-1748) so the static build-time version becomes the live panel:

```jsx
                <SettingSection title="About">
                  <UpdateStatusPanel />
                </SettingSection>
```

The removed paragraph read `import.meta.env.VITE_APP_VERSION || 'dev'`. The panel's `current` comes from the API, which reads `settings.app_version` — resolved from the shipped `VERSION` file by `app/core/config.py:36`, so it is correct in a packaged build where the Vite variable is not.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/frontend && npx vitest run src/__tests__/UpdateStatusPanel.test.jsx`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the whole suite for regressions**

Run: `cd apps/backend && pytest tests/ -q` then `cd apps/frontend && npx vitest run`
Expected: no new failures. Investigate any failure before continuing — do not proceed on a red suite.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/settings/UpdateStatusPanel.jsx apps/frontend/src/pages/SettingsPage.jsx apps/frontend/src/__tests__/UpdateStatusPanel.test.jsx
git commit -m "feat(settings): show live version and update status in About"
```

---

## Verification before claiming completion

Per `superpowers:verification-before-completion`, run these and paste real output. Do not report a row as passing on the strength of a unit test alone.

| Check | Command |
|---|---|
| Backend suite | `cd apps/backend && pytest tests/ -q` |
| Repo-root suite | `pytest tests/ -q` |
| Frontend suite | `cd apps/frontend && npx vitest run` |
| Lint | `cd apps/frontend && npx eslint src --max-warnings=0` |
| Live behaviour | Start the app, confirm the banner appears for an admin on a stale `APP_VERSION` and does not for a current one |

The live check matters: every test above mocks the network, so the shape of the real GitHub response is unproven by the suite. Run the app with `APP_VERSION=1.0.0-rc.2` and confirm it offers rc.4.

## Out of scope for this plan

Spec stages 3–5 are separate plans, each producing working software on its own:

- **Plan 2 — Signed manifest.** `pages.yml` publishes `updates.json` + `.asc`; backend prefers it over the GitHub API and gains `unverified`.
- **Plan 3 — `cb update` unity.** Install-method markers in `nfpm.yaml`/`PKGBUILD`/AppImage, dispatch per method, `next` tag in `release_channel.py`, and the bash half of the shared fixture from Task 2.
- **Plan 4 — Repositories and signature verification.** Signed APT/YUM repos on Pages; `.asc` verification in `install.sh`.
