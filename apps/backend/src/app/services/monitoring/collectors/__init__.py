"""Check collectors for the monitoring engine.

Each collector runs blocking network I/O and returns a CheckResult. It must
NEVER raise for an unreachable target — failure is a datum (up=False with a
reason in msg). No DB access here so collectors stay unit-testable by mocking
the private probe helpers in each module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    metric: str
    value: float
    error_reason: str | None = None


@dataclass(frozen=True)
class CheckResult:
    up: bool
    samples: list[Sample] = field(default_factory=list)
    msg: str = ""
    details: dict | None = None


CollectorFn = Callable[[str, dict], CheckResult]

COLLECTORS: dict[str, CollectorFn] = {}


def register(check_type: str, fn: CollectorFn) -> None:
    COLLECTORS[check_type] = fn


# Import for side effect: each module registers its collectors.
from app.services.monitoring.collectors import dns_check, net, web  # noqa: E402,F401
