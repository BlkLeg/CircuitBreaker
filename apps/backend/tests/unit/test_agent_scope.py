"""The shared agent network-scope evaluator (Task 3, design §3).

Slice 4's discovery imports this module unchanged, so these tests pin the rules
themselves rather than one caller's use of them: what a `direct_private` grant
derives from reported interface facts, what an administrator may narrow or widen,
and — the part no override may touch — what stays blocked regardless.
"""

from __future__ import annotations

import pytest

from app.core.agent_scope import (
    MIN_SCOPE_PREFIX_V4,
    MIN_SCOPE_PREFIX_V6,
    REASON_EMPTY_SCOPE,
    REASON_EXCLUDED,
    REASON_IN_SCOPE,
    REASON_INVALID_DESTINATION,
    REASON_OUT_OF_SCOPE,
    REASON_PREFIX_TOO_WIDE,
    REASON_SPECIAL_USE,
    address_count,
    derive_scope,
    evaluate,
    hostname_is_approved,
    network_in_scope,
    normalize_scope_cidr,
    normalize_scope_cidrs,
    normalize_scope_hostname,
)

_ETH0 = {"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/24", "fd00:a::5/64"]}


def _config(**overrides: object) -> dict[str, object]:
    """A `remote_probe` grant config as `structured_grants_dict` renders it —
    registry defaults merged over the persisted value, so every key is present."""
    config: dict[str, object] = {
        "enabled": True,
        "max_concurrent": 20,
        "scope_mode": "direct_private",
        "excluded_cidrs": [],
        "additional_cidrs": [],
        "additional_hostnames": [],
    }
    config.update(overrides)
    return config


def test_derived_scope_contains_only_private_ipv4_and_ipv6_ula() -> None:
    facts = [
        _ETH0,
        {
            "name": "eth1",
            "flags": ["broadcast", "up"],
            "addrs": ["172.16.4.9/20", "192.168.8.2/24"],
        },
        # Prefixes whose *network address* is private but whose span is not.
        # Privacy has to hold for the whole prefix or a misconfigured /7 hands the
        # agent public 11.0.0.0/8, and a /6 hands it everything above ULA.
        {"name": "eth2", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/7", "fd00:a::5/6"]},
    ]

    scope = derive_scope(facts, _config())

    assert scope.direct_networks == (
        "10.0.0.0/24",
        "172.16.0.0/20",
        "192.168.8.0/24",
        "fd00:a::/64",
    )
    assert scope.networks == scope.direct_networks
    assert evaluate(scope, "10.0.0.9").allowed
    assert evaluate(scope, "fd00:a::99").allowed
    assert evaluate(scope, "11.0.0.1").reason == "out_of_scope"
    assert evaluate(scope, "fec0::1").reason == "out_of_scope"


def test_derived_scope_excludes_loopback_link_local_multicast_and_public() -> None:
    facts = [
        {"name": "lo", "flags": ["loopback", "up"], "addrs": ["127.0.0.1/8", "::1/128"]},
        {
            "name": "eth0",
            "flags": ["broadcast", "up"],
            # A public lease, a v4 link-local autoconfiguration address and the
            # interface's own v6 link-local all sit beside the usable prefix.
            "addrs": ["10.0.0.5/24", "203.0.113.7/24", "169.254.9.9/16", "fe80::1/64"],
        },
        {"name": "docker0", "flags": ["broadcast", "up"], "addrs": ["224.0.0.1/4"]},
    ]

    scope = derive_scope(facts, _config())

    assert scope.direct_networks == ("10.0.0.0/24",)
    assert evaluate(scope, "203.0.113.7").reason == "out_of_scope"
    assert evaluate(scope, "127.0.0.1").reason == "special_use"
    assert evaluate(scope, "fe80::1").reason == "special_use"


def test_point_to_point_interfaces_are_not_directly_connected() -> None:
    """§3 excludes point-to-point tunnel routes: a VPN peer address is a route,
    not a subnet the agent shares a link with."""
    facts = [_ETH0, {"name": "wg0", "flags": ["pointtopoint", "up"], "addrs": ["10.9.0.2/24"]}]

    scope = derive_scope(facts, _config())

    assert scope.direct_networks == ("10.0.0.0/24", "fd00:a::/64")
    assert evaluate(scope, "10.9.0.7").reason == "out_of_scope"


def test_excluded_cidrs_narrow_the_derived_scope() -> None:
    scope = derive_scope([_ETH0], _config(excluded_cidrs=["10.0.0.128/25"]))

    assert evaluate(scope, "10.0.0.9").allowed
    denied = evaluate(scope, "10.0.0.200")
    assert (denied.allowed, denied.reason) == (False, "excluded_cidr")


def test_additional_cidrs_widen_it() -> None:
    scope = derive_scope([_ETH0], _config(additional_cidrs=["10.40.0.0/16"]))

    assert scope.direct_networks == ("10.0.0.0/24", "fd00:a::/64")
    assert scope.networks == ("10.0.0.0/24", "10.40.0.0/16", "fd00:a::/64")
    assert evaluate(scope, "10.40.7.1").allowed


def test_scope_permanently_blocks_special_use_even_when_explicitly_added() -> None:
    """The special-use denial is applied before any allow rule, so an administrator
    cannot hand an agent loopback, link-local or metadata reachability by widening."""
    scope = derive_scope(
        [_ETH0],
        _config(
            additional_cidrs=[
                "127.0.0.0/8",
                "169.254.0.0/16",
                "224.0.0.0/4",
                "255.255.255.255/32",
                "0.0.0.0/8",
                "fe80::/10",
                "fd00:ec2::254/128",
            ]
        ),
    )

    for destination in (
        "127.0.0.1",
        "169.254.1.1",
        "169.254.169.254",
        "224.0.0.251",
        "255.255.255.255",
        "0.0.0.0",
        "::",
        "::1",
        "fe80::1",
        "ff02::1",
        "fd00:ec2::254",
        # The subnet-directed broadcast of a network that *is* in scope.
        "10.0.0.255",
        # IPv4-mapped IPv6 must be evaluated as its IPv4 form, not slip past
        # the v4 rules down a v6-only path.
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
    ):
        decision = evaluate(scope, destination)
        assert (destination, decision.allowed, decision.reason) == (
            destination,
            False,
            "special_use",
        )


def test_ipv4_mapped_ipv6_destination_is_evaluated_as_its_ipv4_form() -> None:
    scope = derive_scope([_ETH0], _config())

    assert evaluate(scope, "::ffff:10.0.0.9").allowed
    assert evaluate(scope, "::ffff:203.0.113.7").reason == "out_of_scope"


def test_empty_effective_scope_denies_every_destination() -> None:
    """The fail-open guard: `network_acl.is_ip_in_cidrs` treats an empty list as
    "allow all", which for a probe grant would turn "this agent reported no usable
    networks" into "this agent may probe anything"."""
    scope = derive_scope([], _config())

    assert scope.networks == ()
    for destination in ("10.0.0.9", "192.168.1.1", "fd00:a::9", "203.0.113.7"):
        decision = evaluate(scope, destination)
        assert (destination, decision.allowed, decision.reason) == (
            destination,
            False,
            "empty_scope",
        )


def test_normalize_remote_probe_config_rejects_default_routes() -> None:
    """§3: `0.0.0.0/0` and `::/0` are rejected in v1 rather than treated as
    convenient shortcuts. Task 5's capability normalizer delegates here."""
    for default_route in ("0.0.0.0/0", "::/0"):
        with pytest.raises(ValueError, match="whole address space"):
            normalize_scope_cidr(default_route, field="additional_cidrs")
        with pytest.raises(ValueError, match="whole address space"):
            normalize_scope_cidrs([default_route], field="excluded_cidrs")

    assert normalize_scope_cidrs(["10.0.0.7/24", "10.0.0.0/24"], field="additional_cidrs") == [
        "10.0.0.0/24"
    ]
    with pytest.raises(ValueError, match="not a valid CIDR"):
        normalize_scope_cidr("10.0.0.0/33", field="additional_cidrs")
    with pytest.raises(ValueError, match="must be a list"):
        normalize_scope_cidrs("10.0.0.0/24", field="additional_cidrs")


def test_hostname_target_requires_every_resolved_address_in_scope() -> None:
    """The DNS-rebinding rule: a name is only as safe as its worst answer."""
    scope = derive_scope([_ETH0], _config())

    assert evaluate(scope, "nas.lan", resolved=["10.0.0.9", "fd00:a::9"]).allowed

    rebound = evaluate(scope, "nas.lan", resolved=["10.0.0.9", "203.0.113.7"])
    assert (rebound.allowed, rebound.reason, rebound.address) == (
        False,
        "out_of_scope",
        "203.0.113.7",
    )

    unresolved = evaluate(scope, "nas.lan")
    assert (unresolved.allowed, unresolved.reason) == (False, "unresolved_hostname")


def test_approved_hostname_pattern_never_bypasses_the_address_check() -> None:
    """`additional_hostnames` marks a routed use case as centrally approved; it is
    consulted alongside the agent's directly-connected rule, never instead of the
    address check, or an attacker holding the name's DNS would hold the scope."""
    scope = derive_scope(
        [_ETH0], _config(additional_hostnames=["Nas.LAN.", "*.branch.example.com"])
    )

    assert scope.hostnames == ("*.branch.example.com", "nas.lan")
    assert hostname_is_approved(scope, "NAS.lan")
    assert hostname_is_approved(scope, "db.branch.example.com")
    assert not hostname_is_approved(scope, "branch.example.com")
    assert not hostname_is_approved(scope, "nas.lan.attacker.test")

    assert evaluate(scope, "nas.lan", resolved=["203.0.113.7"]).reason == "out_of_scope"


def test_normalize_scope_hostname_canonicalizes_and_rejects_non_hostnames() -> None:
    """The pattern grammar is pinned at the delegate, not at one caller: Task 5's
    `additional_hostnames` normalizer calls this, and so will Slice 4."""
    assert normalize_scope_hostname("Nas.LAN.") == "nas.lan"
    assert normalize_scope_hostname("*.Branch.example.com ") == "*.branch.example.com"

    for rejected in (
        # An IP literal here would read as approved while never matching, since an
        # IP destination never takes the hostname path.
        "10.0.0.1",
        "fd00:a::9",
        # A bare wildcard is every name; the wildcard is only a leading label.
        "*",
        "*.*.example.com",
        "",
        "nas..lan",
        ".".join(["a" * 50] * 5),
        123,
    ):
        with pytest.raises(ValueError):
            normalize_scope_hostname(rejected)


def test_scope_version_changes_only_when_effective_scope_changes() -> None:
    facts = [_ETH0, {"name": "eth1", "flags": ["broadcast", "up"], "addrs": ["192.168.8.2/24"]}]
    baseline = derive_scope(facts, _config())

    # Reordered facts and an unrelated config key describe the same scope.
    assert (
        derive_scope(list(reversed(facts)), _config(max_concurrent=4)).version == baseline.version
    )
    # Every dimension of the scope moves it.
    assert derive_scope([_ETH0], _config()).version != baseline.version
    assert (
        derive_scope(facts, _config(additional_cidrs=["10.40.0.0/16"])).version != baseline.version
    )
    assert (
        derive_scope(facts, _config(excluded_cidrs=["10.0.0.128/25"])).version != baseline.version
    )
    assert (
        derive_scope(facts, _config(additional_hostnames=["nas.lan"])).version != baseline.version
    )


# --- Whole-prefix containment (Slice 4, D-15) ---------------------------------
#
# `evaluate` answers about one address. Slice 4 dispatches a *prefix* to an
# agent, so "is every address in this CIDR permitted" has to be a first-class
# question — asking it by enumerating a /16 is not an implementation, and a
# second copy of the rules on the discovery side is exactly the divergence the
# shared corpus exists to forbid.


def test_network_in_scope_accepts_a_prefix_wholly_inside_a_derived_network() -> None:
    scope = derive_scope([_ETH0], _config())

    assert network_in_scope(scope, "10.0.0.0/25").allowed is True
    assert network_in_scope(scope, "10.0.0.0/24").reason == REASON_IN_SCOPE


def test_network_in_scope_rejects_a_prefix_that_only_overlaps() -> None:
    """A /23 straddling the derived /24 is not in scope even though half of it is.

    Containment, not intersection: dispatching the /23 would hand the agent 256
    addresses on a segment it never reported.
    """
    scope = derive_scope([_ETH0], _config())

    decision = network_in_scope(scope, "10.0.0.0/23")

    assert decision.allowed is False
    assert decision.reason == REASON_OUT_OF_SCOPE


def test_network_in_scope_denies_special_use_before_any_allow_rule() -> None:
    """The §7 ordering rule, restated for prefixes: no `additional_cidrs` entry
    can hand an agent loopback or link-local reachability."""
    scope = derive_scope([_ETH0], _config(additional_cidrs=["169.254.0.0/24"]))

    decision = network_in_scope(scope, "169.254.0.0/24")

    assert decision.allowed is False
    assert decision.reason == REASON_SPECIAL_USE


def test_network_in_scope_denies_a_prefix_overlapping_an_exclusion() -> None:
    """Partial overlap is enough. An exclusion is an administrator saying "not
    that segment"; honoring it only for fully-contained prefixes would let a
    wider request walk straight through it."""
    scope = derive_scope([_ETH0], _config(excluded_cidrs=["10.0.0.128/25"]))

    decision = network_in_scope(scope, "10.0.0.0/24")

    assert decision.allowed is False
    assert decision.reason == REASON_EXCLUDED


def test_network_in_scope_denies_everything_when_scope_is_empty() -> None:
    scope = derive_scope([], _config())

    assert network_in_scope(scope, "10.0.0.0/24").reason == REASON_EMPTY_SCOPE


def test_network_in_scope_rejects_prefixes_wider_than_the_hard_ceiling() -> None:
    """A ceiling that holds even when the agent genuinely reported that prefix:
    a /8 on an interface is a routing mistake, and 16 million addresses is not a
    discovery job whatever the grant says."""
    scope = derive_scope(
        [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/8"]}], _config()
    )

    decision = network_in_scope(scope, "10.0.0.0/8")

    assert decision.allowed is False
    assert decision.reason == REASON_PREFIX_TOO_WIDE
    assert MIN_SCOPE_PREFIX_V4 == 16


def test_network_in_scope_rejects_malformed_and_default_route_prefixes() -> None:
    scope = derive_scope([_ETH0], _config())

    assert network_in_scope(scope, "not-a-cidr").reason == REASON_INVALID_DESTINATION
    assert network_in_scope(scope, "0.0.0.0/0").reason == REASON_PREFIX_TOO_WIDE
    assert network_in_scope(scope, "::/0").reason == REASON_PREFIX_TOO_WIDE


def test_network_in_scope_applies_a_separate_ipv6_ceiling() -> None:
    facts = [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["fd00:a::5/40"]}]
    scope = derive_scope(facts, _config())

    assert network_in_scope(scope, "fd00:a::/40").reason == REASON_PREFIX_TOO_WIDE
    assert MIN_SCOPE_PREFIX_V6 == 48


def test_address_count_sums_prefixes_and_counts_a_host_route_as_one() -> None:
    assert address_count(["10.0.0.0/24"]) == 256
    assert address_count(["10.0.0.0/24", "10.0.1.0/25"]) == 384
    assert address_count(["10.0.0.7/32"]) == 1
    assert address_count(["fd00::/120"]) == 256


def test_address_count_ignores_unparseable_entries() -> None:
    """Same fail-soft posture as `derive_scope`: this runs at dispatch time on
    data that has already been normalized, and a parse failure here must not
    read as "zero addresses, therefore under the limit"."""
    assert address_count(["10.0.0.0/24", "garbage"]) == 256
    assert address_count([]) == 0
