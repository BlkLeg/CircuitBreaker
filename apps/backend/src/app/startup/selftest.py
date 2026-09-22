"""Prove this binary contains the application it claims to serve.

PyInstaller builds from a static import graph, so a module reached only through
a runtime string is invisible to it and gets dropped silently. v0.4.2 shipped
exactly that: a signed, attested, SBOM'd, version-parity-checked binary with no
`app.main` inside it. Every native install died on

    ERROR: Error loading ASGI app. Could not import module "app.main".

after the release had been published.

This module is the assertion that was missing. It resolves the ASGI target the
way uvicorn resolves it — import the module, then getattr the attribute, because
importing alone would pass on a module that exists but exports nothing — and
imports every worker module and the Alembic environment.

It deliberately touches no database, no Redis, no NATS, no network and no
filesystem beyond the bundle, so it runs in seconds, in a container with no
services, and on an air-gapped host. That invariant is enforced, not just
claimed: `apps/backend/tests/test_import_purity.py` runs this from a
read-only cwd as an unprivileged user, and
`tests/build/test_import_time_side_effects.py` ratchets every module `app`
imports against writing at import time — both were added after this exact
docstring's claim turned out to be false for `app.api.assets`,
`app.api.static_spa` and `app.db.cve_session`.
"""

from __future__ import annotations

import importlib
import os
import traceback
from dataclasses import dataclass

from app.start import ASGI_TARGET
from app.workers.main import WORKER_MODULES

ALEMBIC_ENV_MODULE = "app.startup.schema"

#: One representative submodule per package that `scripts/build_native_release.py`
#: hidden-imports via `collect_submodules` because it loads part of itself
#: dynamically (`_DYNAMIC_IMPORT_PACKAGES`, same file). `collect_submodules`
#: puts the files in the bundle at build time; nothing proves they actually
#: import until something imports one. gh#104: `proxmoxer.backends` was
#: silently dropped from a PyInstaller build and every Proxmox VE integration
#: died on connect, with every gate green because none of them imported it.
#: `tests/build/test_selftest_targets_match_runtime.py` pins this dict's keys
#: to that tuple, so a package added to one side without the other fails the
#: build.
DYNAMIC_IMPORT_PROBES: dict[str, str] = {
    "proxmoxer": "proxmoxer.backends.https",
    "apscheduler": "apscheduler.triggers.cron",
}


@dataclass(frozen=True)
class SelfTestResult:
    """The outcome of a self-test run.

    Attributes:
        ok: True when every target resolved.
        checked: Fully qualified names of everything that resolved, in order.
        failure: A human-readable description of the first failure, or None.
        detail: The traceback of that failure, or None. Kept apart from
            `failure` so a caller wanting one line still gets one line.
    """

    ok: bool
    checked: list[str]
    failure: str | None
    detail: str | None = None


def _describe(exc: BaseException) -> str:
    """The exception's traceback, for a failure that repr() cannot explain.

    `PermissionError(13, 'Permission denied')` names no file, because the
    errno came from a syscall rather than an open. Without the traceback there
    is nothing to act on — and this module exists to be acted on. The text is a
    Python traceback over the bundle's own modules: no configuration, no
    secrets, no user data.
    """
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def _resolve_asgi_target(target: str, checked: list[str]) -> tuple[str, str | None] | None:
    """Resolve `<module>:<attribute>` as uvicorn does.

    Returns:
        None when the target resolved, else (failure, traceback-or-None).
    """
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        return (
            f'ASGI target {target!r} is not in uvicorn\'s required "<module>:<attribute>" form',
            None,
        )
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — any import failure is the finding
        return (f"could not import ASGI module {module_name!r}: {exc!r}", _describe(exc))
    checked.append(module_name)
    if not hasattr(module, attribute):
        return (f"{module_name!r} has no attribute {attribute!r} for uvicorn to serve", None)
    checked.append(target)
    return None


def run_selftest() -> SelfTestResult:
    """Import everything this binary must be able to load to run.

    Returns:
        A SelfTestResult naming the first failure, or listing what resolved.
    """
    os.environ.setdefault("CB_DB_URL", "postgresql://selftest:dummy@localhost/selftest")
    checked: list[str] = []

    asgi_failure = _resolve_asgi_target(ASGI_TARGET, checked)
    if asgi_failure is not None:
        failure, detail = asgi_failure
        return SelfTestResult(ok=False, checked=checked, failure=failure, detail=detail)

    for worker_type, module_name in sorted(WORKER_MODULES.items()):
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            return SelfTestResult(
                ok=False,
                checked=checked,
                failure=(
                    f"could not import worker module {module_name!r} for worker "
                    f"type {worker_type!r}: {exc!r}"
                ),
                detail=_describe(exc),
            )
        checked.append(module_name)

    try:
        importlib.import_module(ALEMBIC_ENV_MODULE)
    except Exception as exc:  # noqa: BLE001
        return SelfTestResult(
            ok=False,
            checked=checked,
            failure=f"could not import migration entrypoint {ALEMBIC_ENV_MODULE!r}: {exc!r}",
            detail=_describe(exc),
        )
    checked.append(ALEMBIC_ENV_MODULE)

    for package, probe_module in sorted(DYNAMIC_IMPORT_PROBES.items()):
        try:
            importlib.import_module(probe_module)
        except Exception as exc:  # noqa: BLE001
            return SelfTestResult(
                ok=False,
                checked=checked,
                failure=(
                    f"could not import {probe_module!r}, a dynamically-loaded "
                    f"submodule of {package!r} that the build must bundle "
                    f"explicitly: {exc!r}"
                ),
                detail=_describe(exc),
            )
        checked.append(probe_module)

    return SelfTestResult(ok=True, checked=checked, failure=None)


def format_result(result: SelfTestResult) -> str:
    """The failure, and the traceback that explains it.

    Still one line when it succeeds, and when it fails the first line is the
    same summary as before — callers that log only the first line are
    unaffected. The traceback follows, because a bare repr of an errno-only
    exception names nothing an operator can act on.
    """
    if result.ok:
        return f"selftest OK — {len(result.checked)} targets resolved"
    summary = f"selftest FAILED — {result.failure}"
    if result.detail:
        return f"{summary}\n{result.detail}"
    return summary
