"""A unit file with a ${NAME} placeholder must be rendered, never copied.

deploy/systemd/*.service are templates: deploy/setup.sh resolves the paths that
differ per distro — pgbouncer in /usr/sbin on Debian and /usr/bin on Fedora,
redis-server vs valkey-server, docker wherever the distro puts it — and
cb_render_template substitutes them on the way to /etc/systemd/system.

Copy such a file instead of rendering it and the placeholder survives into the
live unit. systemd does not expand variables in the executable half of
ExecStart, so the unit does not "use the environment" — it looks for a program
whose name is the literal text:

    circuitbreaker-docker-proxy.service: Unable to locate executable
      '${CB_DOCKER_BIN}': No such file or directory
    Failed at step EXEC spawning ${CB_DOCKER_BIN}: status=203/EXEC

That shipped in v0.4.2. `fix: resolve pgbouncer and docker paths instead of
hardcoding them` turned two hardcoded paths into ${CB_PGBOUNCER_BIN} and
${CB_DOCKER_BIN}, but only the pgbouncer unit was already going through
cb_render_template; the docker-proxy unit was installed with `cp` and stayed
that way. The proxy then restarted forever, wait-for-services.sh blocked its
full 60s on it, and the install failed at "Starting Circuit Breaker" with
"Backend failed to start" — three services away from the actual cause.

Nothing else catches this. tests/build/test_installer_template_rendering.py
discovers templates *from* the cb_render_template call sites, so a file that is
copied is invisible to it, and the installer journey runs inside a container
with no Docker, where DOCKER_AVAILABLE is false and this unit is never written
at all.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "deploy" / "setup.sh"
UNITS_DIR = ROOT / "deploy" / "systemd"

# The installed tree the installer copies deploy/ to before it runs.
STAGED = "/opt/circuitbreaker/deploy/"

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_RENDERED = re.compile(rf'cb_render_template\s+"{re.escape(STAGED)}([^"]+)"')
_COPIED = re.compile(rf'\bcp\b[^\n]*?"?{re.escape(STAGED)}([^"\s]+)"?')


def _setup_text() -> str:
    return SETUP.read_text(encoding="utf-8")


def _installed_via(pattern: re.Pattern[str]) -> set[str]:
    """deploy-relative paths this installer mechanism writes out."""
    return set(pattern.findall(_setup_text()))


def _unit_files() -> list[Path]:
    units = sorted(p for p in UNITS_DIR.iterdir() if p.is_file())
    assert units, f"no unit files under {UNITS_DIR}"
    return units


def _placeholders(path: Path) -> set[str]:
    return set(_PLACEHOLDER.findall(path.read_text(encoding="utf-8")))


def test_every_templated_unit_is_rendered_and_not_copied():
    rendered = _installed_via(_RENDERED)
    copied = _installed_via(_COPIED)

    offenders: list[str] = []
    for unit in _unit_files():
        names = _placeholders(unit)
        if not names:
            continue
        rel = f"systemd/{unit.name}"
        asked = ", ".join(f"${{{n}}}" for n in sorted(names))
        if rel in copied:
            offenders.append(f"{rel} is installed with `cp` but asks for {asked}")
        elif rel not in rendered:
            offenders.append(f"{rel} asks for {asked} but deploy/setup.sh never renders it")

    assert not offenders, (
        "these unit files reach /etc/systemd/system with their placeholders "
        "intact, and systemd will try to execute the literal text "
        "'${NAME}' (status=203/EXEC):\n  "
        + "\n  ".join(offenders)
        + "\n\nInstall them with cb_render_template, not cp."
    )


def test_every_unit_file_is_installed_exactly_one_way():
    """A unit nothing installs is dead weight; one installed twice has two
    behaviours depending on which call site runs last."""
    rendered = _installed_via(_RENDERED)
    copied = _installed_via(_COPIED)

    offenders: list[str] = []
    for unit in _unit_files():
        rel = f"systemd/{unit.name}"
        mechanisms = [
            name for name, group in (("cb_render_template", rendered), ("cp", copied)) if rel in group
        ]
        if len(mechanisms) != 1:
            found = " and ".join(mechanisms) if mechanisms else "nothing"
            offenders.append(f"{rel}: installed by {found}")

    assert not offenders, (
        "every file in deploy/systemd must be installed by exactly one of "
        "cb_render_template or cp in deploy/setup.sh:\n  " + "\n  ".join(offenders)
    )
