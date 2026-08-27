"""Regression tests for B45 — ``scan_subnet_safe`` must size-check before it expands.

The sweep used to build ``[str(ip) for ip in network.hosts()]`` unconditionally and
only then look at how many hosts it had.  These tests pin the order: the refusal has
to happen *before* ``hosts()`` is ever touched, because for a large IPv4 range the
expansion is the damage.
"""

from __future__ import annotations

import ipaddress
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import discovery_safe


class _HostsExpanded(AssertionError):
    """Raised by the spy below so an unguarded expansion fails fast instead of hanging.

    Without this, running the test against the unfixed module really would walk
    16.7 million addresses and then start pinging them.
    """


@pytest.fixture
def hosts_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every ``IPv4Network.hosts()`` call and abort it immediately."""
    expanded: list[str] = []

    def _spy(self: ipaddress.IPv4Network):  # type: ignore[no-untyped-def]
        expanded.append(str(self))
        raise _HostsExpanded(f"hosts() was expanded for {self} before any size check")

    monkeypatch.setattr(ipaddress.IPv4Network, "hosts", _spy)
    return expanded


def test_oversize_cidr_refused_before_hosts_are_materialised(hosts_spy: list[str]) -> None:
    with pytest.raises(ValueError) as exc:
        discovery_safe.scan_subnet_safe("10.0.0.0/8")

    assert "too large" in str(exc.value)
    assert hosts_spy == [], f"hosts() was called for {hosts_spy} despite the range being refused"


def test_guard_boundary_matches_the_upstream_cidr_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A /12 (1_048_576 addresses) is accepted; a /11 is not.

    1_048_576 is exactly ``discovery_network._MAX_CIDR_ADDRESSES``, so this guard
    refuses only what the scan-job validator one layer up already refuses.
    """
    monkeypatch.setattr(ipaddress.IPv4Network, "hosts", lambda self: iter(()))

    assert discovery_safe.scan_subnet_safe("10.0.0.0/12") == []

    with pytest.raises(ValueError):
        discovery_safe.scan_subnet_safe("10.0.0.0/11")


def test_normal_subnet_still_sweeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must not disturb an ordinary /29 sweep."""
    alive = {"192.0.2.1"}
    monkeypatch.setattr(discovery_safe, "_ping_host", lambda ip, timeout=1.0: ip in alive)
    monkeypatch.setattr(
        discovery_safe, "_tcp_probe", lambda ip, *a, **kw: [80] if ip in alive else []
    )

    results = discovery_safe.scan_subnet_safe("192.0.2.0/29")

    assert [r["ip"] for r in results] == ["192.0.2.1"]
    assert results[0]["open_ports"] == [80]
    assert results[0]["ping_alive"] is True


def test_sweep_submits_work_in_bounded_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The size guard bounds the range; this bounds the allocation inside the range.

    Refusing anything above a /12 keeps parity with the scan-job validator, but a /12
    is still 1,048,574 addresses, and the sweep used to turn the whole range into a
    list of strings and then hand that same list to ``ThreadPoolExecutor.map`` — which
    submits every item as a Future up front rather than lazily.  Hundreds of megabytes
    of strings and Future objects were therefore allocated before the first ICMP
    packet left the box, through the *normal validated* scan path, not through the
    direct-call hole the guard closes.

    So the sweep walks ``network.hosts()`` in batches and submits one batch at a time.
    Peak footprint becomes a function of the batch size instead of the CIDR size, and
    the observable that pins it is the length of the iterable each ``map`` call is
    handed.  A /19 is used here because it is comfortably larger than one batch while
    still running in a second with the probes stubbed out.

    The second assertion is the one that stops this from being satisfiable by simply
    scanning less: every host in the range must still be swept, in both phases.
    """
    submitted: list[int] = []
    real_map = ThreadPoolExecutor.map

    def _spy_map(self, fn, iterable, *args, **kwargs):  # type: ignore[no-untyped-def]
        items = list(iterable)
        submitted.append(len(items))
        return real_map(self, fn, items, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "map", _spy_map)
    monkeypatch.setattr(discovery_safe, "_ping_host", lambda ip, timeout=1.0: False)
    monkeypatch.setattr(discovery_safe, "_tcp_probe", lambda ip, *a, **kw: [])

    host_count = 8190  # a /19: 8192 addresses less network and broadcast

    assert discovery_safe.scan_subnet_safe("10.0.0.0/19") == []

    assert submitted, "the sweep submitted no work at all"
    assert max(submitted) <= 4096, (
        f"a single map() call was handed {max(submitted)} of the {host_count} hosts; "
        "the whole range is being materialised and submitted up front"
    )
    assert sum(submitted) == 2 * host_count, (
        f"expected every host swept in both phases ({2 * host_count} submissions), "
        f"got {sum(submitted)} — the batching dropped hosts"
    )
