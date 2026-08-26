"""
POST /api/v1/ipam/scan/{network_id} — the CIDR size guard.

The endpoint auto-populates IPAM rows from a network's stored CIDR, and it is
only ever meant to do that for small subnets. The guard that enforces "small"
has to run *before* the host generator is expanded, because the CIDR it is
guarding against is attacker-influenced: `NetworkBase.validate_cidr` accepts any
syntactically valid network, including an IPv6 /32, and `ip_network(...).hosts()`
for a /32 is a generator over 2**96 - 1 addresses. Materialising that list first
and measuring it afterwards means the measurement never happens — the worker
thread allocates roughly 150 MB/s of IPv6Address objects until the box dies.

So the tests below pin the *ordering*, not just the accept/reject boundary: the
first one counts how many host objects the endpoint pulls before it answers.
"""

import ipaddress

import pytest

pytestmark = pytest.mark.asyncio

_IPAM = "/api/v1/ipam"

# How many host objects the endpoint may pull before it makes up its mind. The
# real bound is 1024 (a /22's num_addresses); this leaves a little slack so the
# test fails on "expanded an unbounded generator", not on an off-by-one.
_PULL_BUDGET = 4096


class _CountingNetwork:
    """A stand-in for an ip_network that counts host-generator consumption.

    Everything except `hosts()` delegates to the real network object, so the
    endpoint sees genuine `num_addresses`, `version` and `prefixlen` values.
    `hosts()` yields real addresses but stops after `_PULL_BUDGET` of them
    instead of running forever, which is what keeps this test from taking the
    machine's memory with it when the guard is in the wrong place.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.pulled = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def hosts(self):
        for host in self._inner.hosts():
            if self.pulled >= _PULL_BUDGET:
                return
            self.pulled += 1
            yield host


@pytest.fixture
def counting_ip_network(monkeypatch):
    """Wrap `ipaddress.ip_network` so one specific CIDR comes back counted.

    Only the CIDR the test asks about is wrapped; every other caller in the
    request path (middleware, audit) keeps the real function.
    """
    real = ipaddress.ip_network
    holder: dict[str, _CountingNetwork] = {}

    def install(cidr: str) -> _CountingNetwork:
        counted = _CountingNetwork(real(cidr, strict=False))
        holder["net"] = counted

        def fake(address, strict=True):
            if str(address) == cidr:
                return counted
            return real(address, strict=strict)

        monkeypatch.setattr(ipaddress, "ip_network", fake)
        return counted

    return install


async def test_scan_answers_an_ipv6_slash_32_without_expanding_the_host_generator(
    client, auth_headers, factories, counting_ip_network
):
    counted = counting_ip_network("2001:db8::/32")
    net = factories.network(name="ipv6-scan-guard-net", cidr="2001:db8::/32")

    resp = await client.post(f"{_IPAM}/scan/{net.id}", headers=auth_headers)

    assert resp.status_code == 400
    assert counted.pulled <= _PULL_BUDGET - 1, (
        f"the endpoint pulled {counted.pulled} hosts off a 2**96-address generator "
        "before rejecting the CIDR; the size check has to come first"
    )


@pytest.mark.timeout(5)
async def test_scan_rejects_a_real_ipv6_slash_32_with_400(client, auth_headers, factories):
    """The same case with no instrumentation at all.

    The short timeout is deliberate: if the guard ever moves back behind the
    `list(...)`, this test must fail on the clock rather than sit there
    allocating until the runner is swapped to death.
    """
    net = factories.network(name="ipv6-scan-real-net", cidr="2001:db8::/32")

    resp = await client.post(f"{_IPAM}/scan/{net.id}", headers=auth_headers)

    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"]


async def test_scan_rejects_an_ipv4_slash_21_with_400(client, auth_headers, factories):
    """A /21 is 2046 hosts — over the documented /22 = 1022 ceiling."""
    net = factories.network(name="ipv4-slash-21-net", cidr="10.44.0.0/21")

    resp = await client.post(f"{_IPAM}/scan/{net.id}", headers=auth_headers)

    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"]


async def test_scan_still_populates_addresses_for_a_slash_24(client, auth_headers, factories):
    """The accept side of the boundary is unchanged by the guard's placement."""
    net = factories.network(name="ipv4-slash-24-scan-net", cidr="10.45.7.0/24")

    resp = await client.post(f"{_IPAM}/scan/{net.id}", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 254
    assert body[0]["address"] == "10.45.7.1"
    assert body[-1]["address"] == "10.45.7.254"
