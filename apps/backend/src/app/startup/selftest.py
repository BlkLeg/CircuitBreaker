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
services, and on an air-gapped host.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

from app.start import ASGI_TARGET
from app.workers.main import WORKER_MODULES

ALEMBIC_ENV_MODULE = "app.startup.schema"


@dataclass(frozen=True)
class SelfTestResult:
    """The outcome of a self-test run.

    Attributes:
        ok: True when every target resolved.
        checked: Fully qualified names of everything that resolved, in order.
        failure: A human-readable description of the first failure, or None.
    """

    ok: bool
    checked: list[str]
    failure: str | None


def _resolve_asgi_target(target: str, checked: list[str]) -> str | None:
    """Resolve `<module>:<attribute>` as uvicorn does. Returns a failure or None."""
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        return f'ASGI target {target!r} is not in uvicorn\'s required "<module>:<attribute>" form'
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — any import failure is the finding
        return f"could not import ASGI module {module_name!r}: {exc!r}"
    checked.append(module_name)
    if not hasattr(module, attribute):
        return f"{module_name!r} has no attribute {attribute!r} for uvicorn to serve"
    checked.append(target)
    return None


def run_selftest() -> SelfTestResult:
    """Import everything this binary must be able to load to run.

    Returns:
        A SelfTestResult naming the first failure, or listing what resolved.
    """
    os.environ.setdefault("CB_DB_URL", "postgresql://selftest:dummy@localhost/selftest")
    checked: list[str] = []

    failure = _resolve_asgi_target(ASGI_TARGET, checked)
    if failure is not None:
        return SelfTestResult(ok=False, checked=checked, failure=failure)

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
            )
        checked.append(module_name)

    try:
        importlib.import_module(ALEMBIC_ENV_MODULE)
    except Exception as exc:  # noqa: BLE001
        return SelfTestResult(
            ok=False,
            checked=checked,
            failure=f"could not import migration entrypoint {ALEMBIC_ENV_MODULE!r}: {exc!r}",
        )
    checked.append(ALEMBIC_ENV_MODULE)

    return SelfTestResult(ok=True, checked=checked, failure=None)


def format_result(result: SelfTestResult) -> str:
    """One line, suitable for a CI log or a doctor check."""
    if result.ok:
        return f"selftest OK — {len(result.checked)} targets resolved"
    return f"selftest FAILED — {result.failure}"
