"""The packaged service must be able to write to the directory it was given.

Found by Tier 3's first real run (Phase 2, F1). The rpm installed cleanly, the
binary reported the right version, and then the service crash-looped:

    OSError: [Errno 30] Read-only file system: '/data'

`packaging/postinstall.sh` generates the env file without CB_DATA_DIR, four
modules fall back to `/data` when it is unset (main.py, acme_service.py,
agent_install.py, certificate_activation.py), and `/data` is the *container*
path -- absent on a native host, and unwritable anyway because the unit runs
under ProtectSystem=strict.

The code default is deliberately left alone: docker/*.sh all read
`${CB_DATA_DIR:-/data}`, so `/data` is correct there and changing it would move
the bug rather than fix it. What was wrong is that the packaged install never
said which directory it meant.

The second test below is the one worth having. Asserting that the env names some
path would have passed with any string in it; the invariant that actually failed
is that the named path must be one the unit grants write access to. That couples
the two files, so neither can be edited into disagreement again.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTINSTALL = REPO_ROOT / "packaging" / "postinstall.sh"
UNIT = REPO_ROOT / "packaging" / "circuit-breaker.service"


def _declared_data_dir() -> str:
    match = re.search(r"^CB_DATA_DIR=(\S+)\s*$", POSTINSTALL.read_text(encoding="utf-8"), re.M)
    assert match, (
        "postinstall.sh must write CB_DATA_DIR into the generated env; without "
        "it the service falls back to /data and cannot start on a native host"
    )
    return match.group(1)


def _read_write_paths() -> list[str]:
    match = re.search(r"^ReadWritePaths=(.+)$", UNIT.read_text(encoding="utf-8"), re.M)
    assert match, "the unit must declare ReadWritePaths under ProtectSystem=strict"
    return match.group(1).split()


def test_generated_env_names_a_data_dir():
    assert _declared_data_dir()


def test_the_data_dir_is_writable_under_the_units_hardening():
    """ProtectSystem=strict makes everything read-only except ReadWritePaths."""
    data_dir = _declared_data_dir()
    writable = _read_write_paths()
    assert any(data_dir == p or data_dir.startswith(p.rstrip("/") + "/") for p in writable), (
        f"CB_DATA_DIR is {data_dir}, which ProtectSystem=strict makes read-only: "
        f"ReadWritePaths grants only {writable}. This is the exact shape of the "
        f"crash Tier 3 caught -- the service starts, tries to write, and dies."
    )


def test_the_package_creates_the_directory_it_names():
    """Naming a directory the package never creates fails the same way."""
    data_dir = _declared_data_dir()
    text = POSTINSTALL.read_text(encoding="utf-8")
    assert re.search(rf"mkdir -p[^\n]*{re.escape(data_dir)}", text), (
        f"postinstall.sh names {data_dir} but never creates it"
    )


def test_an_upgrade_backfills_every_path_that_predates_this_fix():
    """postinstall writes the env only when absent, so an existing install would
    upgrade into the same crash it had before -- the file it already has is
    exactly the one missing these lines.

    Checked per variable rather than by matching the loop's text, so the next
    path added to the generated env has to be added to the backfill too.
    """
    text = POSTINSTALL.read_text(encoding="utf-8")
    backfill = text[text.index("for _kv in"):] if "for _kv in" in text else ""
    assert backfill, "postinstall must backfill paths into a pre-existing env file"
    for var in ("CB_DATA_DIR", "UPLOADS_DIR"):
        assert f'"{var}=' in backfill, (
            f"{var} is written for fresh installs but never backfilled, so an "
            f"upgrade keeps the defect"
        )


CONFIG = REPO_ROOT / "apps/backend/src/app/core/config.py"


def _relative_path_defaults() -> dict[str, str]:
    """Settings whose default is a RELATIVE path, keyed by their env var name.

    A relative default is resolved against the process working directory. The
    unit sets no WorkingDirectory, so systemd runs the service from `/` and
    `data/uploads` becomes `/data/uploads` -- which does not exist and cannot be
    created, because ProtectSystem=strict makes / read-only. The value looks
    harmless in the source and is a crash on a packaged host.
    """
    out: dict[str, str] = {}
    for match in re.finditer(
        r"^\s+([a-z_]+(?:_dir|_path)):\s*str\s*=\s*\"([^\"]*)\"",
        CONFIG.read_text(encoding="utf-8"), re.M,
    ):
        field, default = match.group(1), match.group(2)
        if default and not default.startswith("/"):
            out[field.upper()] = default
    return out


def test_the_package_pins_every_relative_path_default():
    """Close the class, not the instance.

    Tier 3 caught CB_DATA_DIR first; fixing it surfaced UPLOADS_DIR immediately
    behind it, the same defect one layer down. Both are settings whose default is
    only correct when something else sets the working directory or the env, and
    neither failed anywhere except on a real packaged install. Rather than wait
    for the tier to find the third one, every relative default has to be pinned
    by the generated env.
    """
    env_text = POSTINSTALL.read_text(encoding="utf-8")
    missing = [
        f"{var} (default {default!r})"
        for var, default in _relative_path_defaults().items()
        if not re.search(rf"^{var}=", env_text, re.M)
    ]
    assert not missing, (
        "these settings default to a relative path, which resolves against the "
        "service's working directory -- `/` under systemd -- and cannot be "
        "created under ProtectSystem=strict. The package must name an absolute "
        "path for each:\n  " + "\n  ".join(missing)
    )


def test_every_path_the_package_pins_is_writable_or_shipped():
    """A pinned path still has to be one the service can actually use: either
    inside ReadWritePaths, or under the read-only tree the package installs."""
    env_text = POSTINSTALL.read_text(encoding="utf-8")
    writable = _read_write_paths()
    shipped_ro = ["/usr/local/share/circuit-breaker", "/usr/local/bin"]
    for match in re.finditer(r"^((?:CB_)?[A-Z_]*(?:DIR|INI))=(/\S+)$", env_text, re.M):
        var, path = match.group(1), match.group(2)
        allowed = writable + shipped_ro
        assert any(path == p or path.startswith(p.rstrip("/") + "/") for p in allowed), (
            f"{var}={path} is neither writable (ReadWritePaths={writable}) nor "
            f"inside the read-only tree the package installs"
        )


# ── the production gates, not just the paths ────────────────────────────────
#
# Everything above closes the *path* class: a setting whose default is only
# correct when something else sets the working directory. Tier 3's first run of
# the Phase 3 tree found the class one door down, and it failed the same way --
# install clean, right version, then a crash loop:
#
#     CRITI [app.main] STARTUP FAILED: CB_EGRESS_PROXY_URL is required in
#     production so public outbound HTTP clients cannot bypass controlled
#     egress; set CB_ALLOW_DIRECT_EGRESS=true to run without a proxy on hosts
#     that have none
#
# `validate_core_dependencies` refuses to boot when CB_EGRESS_PROXY_URL is
# empty and CB_ALLOW_DIRECT_EGRESS is unset. Every other shipped path already
# answers it -- deploy/setup.sh, docker-compose.yml, docker/.env.example and
# deploy/.env.template all default the waiver to true -- and
# docs/installation/configuration.md states as fact that it is `true` in "the
# installer-generated /etc/circuitbreaker/.env". The deb/rpm postinstall was the
# one path that said nothing, so the package printed "Next steps: systemctl
# start circuit-breaker" and that command could not work on any host.
#
# The waiver is not a weakening: allow_direct_egress() waives the proxy
# requirement alone. The SSRF and outbound-URL policy still apply, and the
# Redis, NATS, rate-limit and secret gates are deliberately out of its reach.

STARTUP_VALIDATION = REPO_ROOT / "apps/backend/src/app/core/startup_validation.py"


def _generated_env() -> dict[str, str]:
    """The key/values the package writes into /etc/circuit-breaker/*.env."""
    text = POSTINSTALL.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M)
    }


def test_the_generated_env_answers_the_production_egress_gate():
    env = _generated_env()
    proxy = env.get("CB_EGRESS_PROXY_URL", "")
    waiver = env.get("CB_ALLOW_DIRECT_EGRESS", "").lower()
    assert proxy or waiver in {"1", "true", "yes"}, (
        "the packaged install cannot start: validate_core_dependencies() raises "
        "when CB_EGRESS_PROXY_URL is empty and CB_ALLOW_DIRECT_EGRESS is unset, "
        "and the generated env sets neither. Found by the first execution of the "
        "fedora-rpm-amd64 row -- the service crash-looped 13 times in the 120s "
        "boot window."
    )


def test_every_production_gate_the_backend_names_required_is_answered():
    """Close the class, not the instance.

    Any gate that fails startup with 'CB_X is required in production' has to be
    answered by the generated env -- either by setting CB_X, or by the waiver the
    error message itself names. A gate added later with no answer here is the
    same outage as this one, and this test is what makes it fail in CI instead of
    on an operator's host.
    """
    validation = STARTUP_VALIDATION.read_text(encoding="utf-8")
    env = _generated_env()
    unanswered = []
    for match in re.finditer(r"\"(CB_[A-Z0-9_]+) is required in production(.*?)\"\s*\n?", validation, re.S):
        required, tail = match.group(1), match.group(2)
        waivers = re.findall(r"set (CB_[A-Z0-9_]+)=true", tail + validation[match.end():match.end() + 400])
        answered = bool(env.get(required, "")) or any(
            env.get(w, "").lower() in {"1", "true", "yes"} for w in waivers
        )
        if not answered:
            unanswered.append(f"{required} (waivers offered: {waivers or 'none'})")
    assert not unanswered, (
        "these gates refuse to boot in production and the packaged env answers "
        "neither them nor their waiver:\n  " + "\n  ".join(unanswered)
    )


def test_an_upgrade_backfills_the_egress_decision():
    """An install from before this fix has an env file without the key, and the
    generator only writes when the file is absent -- so without a backfill every
    existing host upgrades straight into the crash loop. This is exactly why the
    CB_DATA_DIR backfill above exists.
    """
    text = POSTINSTALL.read_text(encoding="utf-8")
    backfill = text[text.index("for _kv in"):] if "for _kv in" in text else ""
    assert backfill, "postinstall must backfill into a pre-existing env file"
    assert '"CB_ALLOW_DIRECT_EGRESS=' in backfill or '"CB_EGRESS_PROXY_URL=' in backfill, (
        "the egress decision is written for fresh installs but never backfilled, "
        "so upgrading a working 0.3.x host onto this version stops it booting"
    )
