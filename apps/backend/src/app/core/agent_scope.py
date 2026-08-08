"""The shared agent network-scope evaluator (Slice 3 §3, D-1).

Turns what an agent reported about its own interfaces (`agent_networks.facts`)
plus the administrator's `remote_probe` grant config into a versioned effective
scope, and answers "may this agent reach that destination?". Remote probing
(Slice 3) and local discovery (Slice 4) both consume it: two subtly different
CIDR or special-use rule sets would mean an agent could be told one thing at
assignment time and enforce another at connect time, which is exactly the gap
independent enforcement exists to close. `apps/agent/internal/netscope` is the
Go mirror, and `fixtures/agent_scope_corpus.json` is what keeps the two honest.

Deliberately *not* built on `core.url_validation._is_forbidden_ip` (it rejects
`is_private`, which is the whole address space remote probing exists to reach)
nor on `core.network_acl.is_ip_in_cidrs` (it fails open on an empty list — an
agent that reported no usable network must be able to probe nothing at all).

Two ordering rules carry the security weight:

* Special-use denial runs *before* any allow rule, so no `additional_cidrs`
  entry can hand an agent loopback, link-local or cloud-metadata reachability.
* A hostname is only as safe as its worst answer: every resolved address must
  pass on its own, which is what makes a rebinding resolver useless.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.network_acl import _RFC1918_NETWORKS

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

SCOPE_MODE_DIRECT_PRIVATE = "direct_private"
SCOPE_MODES = frozenset({SCOPE_MODE_DIRECT_PRIVATE})

# Machine-readable decision reasons. They travel into probe-run audit rows, agent
# capability-violation events and the Go mirror's corpus expectations, so they are
# constants rather than prose.
REASON_IN_SCOPE = "in_scope"
REASON_SPECIAL_USE = "special_use"
REASON_EXCLUDED = "excluded_cidr"
REASON_EMPTY_SCOPE = "empty_scope"
REASON_OUT_OF_SCOPE = "out_of_scope"
REASON_INVALID_DESTINATION = "invalid_destination"
REASON_UNRESOLVED_HOSTNAME = "unresolved_hostname"
REASON_PREFIX_TOO_WIDE = "prefix_too_wide"

# The widest prefix that may ever be dispatched as a discovery target, whatever
# the grant or the agent's own report says. A /16 is 65 536 addresses and a /48
# of IPv6 ULA is the standard site allocation; anything wider is a routing
# mistake being read as a scope, and no bounded job can cover it. Expressed as a
# *minimum prefix length* because that is the direction the comparison runs.
MIN_SCOPE_PREFIX_V4 = 16
MIN_SCOPE_PREFIX_V6 = 48

# IPv6 unique local addresses. `network_acl.is_rfc1918` answers False for every v6
# network and has no ULA equivalent, so the private-space test is defined here for
# both families rather than half-borrowed.
_ULA_V6 = ipaddress.IPv6Network("fc00::/7")

# Never reachable, whatever the grant says. Wider than the strictly named cases so
# that "unspecified", "limited broadcast" and the reserved space around them cannot
# be probed either: 0.0.0.0/8 covers this-network, 240.0.0.0/4 covers reserved plus
# 255.255.255.255, and 169.254.0.0/16 covers the IPv4 cloud-metadata address. Its
# IPv6 counterpart sits inside ULA and would otherwise be derived as in-scope on any
# EC2 host, so it is listed explicitly.
_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("224.0.0.0/4"),
    ipaddress.IPv4Network("240.0.0.0/4"),
    ipaddress.IPv6Network("::/128"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("ff00::/8"),
    ipaddress.IPv6Network("fd00:ec2::254/128"),
)

# Interfaces whose networks are not "directly connected" in §3's sense: a loopback
# has no peers and a point-to-point tunnel carries a route, not a shared segment.
_EXCLUDED_INTERFACE_FLAGS = frozenset({"loopback", "pointtopoint"})

_HOSTNAME_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class EffectiveScope:
    """What one agent may reach, and the version of that answer.

    `networks` is the allow list (derived plus centrally approved), `direct_networks`
    the directly connected subset of it — the agent additionally requires a
    destination to be directly connected unless an override covers it, so the two
    cannot be collapsed. `version` changes when, and only when, one of the four
    fields below it changes; it is what lets a scheduler decide whether in-flight
    work is still authorized without diffing CIDR lists.

    `networks` is an allow list, not the reachable set: `evaluate` subtracts both
    `excluded_networks` and the static special-use blocklist from it. Anything
    rendering scope for a human has to show that difference, or it will claim
    reachability the evaluator refuses.
    """

    networks: tuple[str, ...]
    direct_networks: tuple[str, ...]
    excluded_networks: tuple[str, ...]
    hostnames: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class Decision:
    """The evaluator's answer. `address` names the resolved address that decided a
    hostname's fate, so a refusal can say *which* answer was unacceptable."""

    allowed: bool
    reason: str
    address: str | None = None


def normalize_scope_cidr(value: object, *, field: str = "cidr") -> str:
    """Validate one administrator-supplied scope CIDR, returning its canonical form.

    Raises ValueError, which `schemas/agents.py::_validate_capability_map` already
    turns into a 422 at both approve and capabilities-update. `/0` is refused
    outright per §3 — a default route is not a scope, and accepting it as a
    convenient shortcut would make every other rule here advisory.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} entries must be strings")
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise ValueError(
            f"{field} entry '{value}' is not a valid CIDR (example: 10.0.0.0/24)"
        ) from exc
    if net.prefixlen == 0:
        raise ValueError(
            f"{field} entry '{value}' covers the whole address space; "
            "0.0.0.0/0 and ::/0 are not allowed"
        )
    return str(net)


def normalize_scope_cidrs(values: object, *, field: str = "cidrs") -> list[str]:
    """Validate a list of scope CIDRs, de-duplicated and ordered."""
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list of CIDR strings")
    return _sorted_networks(
        ipaddress.ip_network(normalize_scope_cidr(v, field=field)) for v in values
    )


def normalize_scope_hostname(value: object, *, field: str = "additional_hostnames") -> str:
    """Validate one approved-hostname pattern, returning its canonical form.

    Accepts an exact name or a single leading `*.` wildcard. An IP literal is
    refused with a pointer at `additional_cidrs`: written here it would look
    approved while never matching, since IP destinations never take the hostname
    path.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} entries must be strings")
    name = value.strip().lower().rstrip(".")
    if not name:
        raise ValueError(f"{field} entries must not be empty")
    if len(name) > 253:
        raise ValueError(f"{field} entry '{value}' is longer than 253 characters")
    labels = name[2:].split(".") if name.startswith("*.") else name.split(".")
    if not labels or any(not _HOSTNAME_LABEL_RE.match(label) for label in labels):
        raise ValueError(f"{field} entry '{value}' is not a hostname or '*.example.com' pattern")
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return name
    raise ValueError(f"{field} entry '{value}' is an IP address; use additional_cidrs")


def derive_scope(
    facts: Sequence[Mapping[str, Any]] | None, config: Mapping[str, Any] | None
) -> EffectiveScope:
    """Build an agent's effective scope from its reported networks and grant config.

    `facts` is `agent_networks.facts` as written by `agent_registry.record_network_facts`;
    `config` is a `remote_probe` grant config as `structured_grants_dict` renders it
    (registry defaults merged over the persisted value), so a bare `{}` is legitimate
    and every key is optional here.

    Nothing in here raises. It runs at dispatch time on data an agent supplied, so a
    malformed address is dropped rather than allowed to fail a check that would then
    read as the target being down; administrator input has already been through
    `normalize_scope_cidr` at write time.
    """
    cfg = dict(config or {})
    mode = cfg.get("scope_mode", SCOPE_MODE_DIRECT_PRIVATE)
    # An unrecognized mode derives nothing rather than everything: a config written
    # by a newer backend must not be read here as "no restriction".
    direct = _direct_networks(facts) if mode == SCOPE_MODE_DIRECT_PRIVATE else []
    # `/0` cannot reach an allow list even if one slipped past normalization — the
    # same fail-closed reason `normalize_scope_cidr` rejects it at write time.
    additional = [net for net in _parse_cidrs(cfg.get("additional_cidrs")) if net.prefixlen > 0]
    excluded = _parse_cidrs(cfg.get("excluded_cidrs"))

    networks = _sorted_networks(direct + additional)
    direct_networks = _sorted_networks(direct)
    excluded_networks = _sorted_networks(excluded)
    hostnames = sorted({_canonical_hostname(h) for h in cfg.get("additional_hostnames") or []})
    return EffectiveScope(
        networks=tuple(networks),
        direct_networks=tuple(direct_networks),
        excluded_networks=tuple(excluded_networks),
        hostnames=tuple(hostnames),
        version=_scope_version(networks, direct_networks, excluded_networks, hostnames),
    )


def evaluate(
    scope: EffectiveScope, destination: str, resolved: Sequence[str] | None = None
) -> Decision:
    """Decide whether *destination* is permitted under *scope*.

    An IP literal is judged directly. A hostname is judged by *resolved*, which the
    caller supplies — this module never resolves anything, so the same answer set can
    be checked at dispatch and re-checked at the agent immediately before connecting.
    A name with no answers is refused rather than assumed reachable.
    """
    host = (destination or "").strip()
    if not host:
        return Decision(False, REASON_INVALID_DESTINATION)

    literal = _parse_address(host)
    if literal is not None:
        return _evaluate_address(scope, literal)

    if resolved is None or not list(resolved):
        return Decision(False, REASON_UNRESOLVED_HOSTNAME)
    for candidate in resolved:
        address = _parse_address(candidate)
        if address is None:
            return Decision(False, REASON_INVALID_DESTINATION, str(candidate))
        decision = _evaluate_address(scope, address)
        if not decision.allowed:
            return decision
    return Decision(True, REASON_IN_SCOPE)


def network_in_scope(scope: EffectiveScope, cidr: str) -> Decision:
    """Decide whether every address in *cidr* is permitted under *scope*.

    `evaluate` answers about one address; Slice 4 hands an agent a whole prefix,
    so the containment question has to be first-class. Enumerating the prefix and
    calling `evaluate` per address is not an implementation — a /16 is 65 536
    calls — and a second copy of the rules on the discovery side is exactly the
    divergence `fixtures/agent_scope_corpus.json` exists to forbid.

    The rule order matches `_evaluate_address` deliberately, because the security
    weight is in the order and not in the individual tests:

    1. **Width first.** A prefix wider than the `MIN_SCOPE_PREFIX_*` ceiling is
       refused before anything else, so no derived-or-granted network can smuggle
       an unbounded job through by being legitimately in scope.
    2. **Special use.** Refused if the prefix *overlaps* blocked space at all —
       not merely if it is contained in it — since a request covering both a
       usable segment and link-local is still a request for link-local.
    3. **Exclusions.** Also on overlap, for the same reason: an administrator
       excluding a /25 must not be walked around by asking for the enclosing /24.
    4. **Containment.** Only then, and only as full containment in a single
       allow-list network. A prefix half inside a reported subnet describes
       addresses on a segment the agent never reported.

    Like `derive_scope`, nothing here raises: it runs at dispatch time against
    values an agent or a stored grant supplied, and an unparseable prefix is a
    refusal (`invalid_destination`) rather than an exception that would read as
    the target being unreachable.
    """
    try:
        network = ipaddress.ip_network(str(cidr).strip(), strict=False)
    except (ValueError, TypeError):
        return Decision(False, REASON_INVALID_DESTINATION)

    text = str(network)
    minimum = MIN_SCOPE_PREFIX_V4 if network.version == 4 else MIN_SCOPE_PREFIX_V6
    if network.prefixlen < minimum:
        return Decision(False, REASON_PREFIX_TOO_WIDE, text)
    if any(_overlaps(blocked, network) for blocked in _BLOCKED_NETWORKS):
        return Decision(False, REASON_SPECIAL_USE, text)
    if any(_overlaps(excluded, network) for excluded in _parsed(scope.excluded_networks)):
        return Decision(False, REASON_EXCLUDED, text)

    networks = _parsed(scope.networks)
    if not networks:
        return Decision(False, REASON_EMPTY_SCOPE, text)
    if any(_contains_network(allowed, network) for allowed in networks):
        return Decision(True, REASON_IN_SCOPE, text)
    return Decision(False, REASON_OUT_OF_SCOPE, text)


def address_count(cidrs: Iterable[str]) -> int:
    """How many addresses a set of target prefixes covers, for the job ceiling.

    Unparseable entries are skipped rather than raising, matching `derive_scope`'s
    posture — but note the asymmetry with `network_in_scope`, which *refuses* an
    unparseable prefix. That is the safe pairing: the counter must never be the
    thing that decides a malformed target is acceptable, and by the time this is
    consulted every prefix has already been through `network_in_scope`.

    Duplicates and overlaps are counted once, so asking for `10.0.0.0/24` twice
    does not spuriously exhaust the ceiling.
    """
    collapsed = ipaddress.collapse_addresses(_parse_cidrs(list(cidrs)))  # type: ignore[arg-type]
    return sum(network.num_addresses for network in collapsed)


def hostname_is_approved(scope: EffectiveScope, host: str) -> bool:
    """Whether *host* matches an `additional_hostnames` entry.

    Approval names a routed use case an administrator signed off on; it is consulted
    alongside the agent's directly-connected requirement (§3), never instead of
    `evaluate` — an approved name whose addresses fall outside scope is still refused,
    or whoever controls that name's DNS would control the agent's scope.
    """
    name = _canonical_hostname(host)
    return any(
        name.endswith(pattern[1:]) if pattern.startswith("*.") else name == pattern
        for pattern in scope.hostnames
    )


def _evaluate_address(scope: EffectiveScope, address: IPAddress) -> Decision:
    text = str(address)
    if any(_contains(net, address) for net in _BLOCKED_NETWORKS):
        return Decision(False, REASON_SPECIAL_USE, text)
    networks = _parsed(scope.networks)
    # A subnet-directed broadcast is only recognizable against the prefix that
    # defines it, so it is checked here rather than in the static blocklist. Against
    # *any* scope network, not just the matching one: a /16 that also covers the
    # address must not make its /24's broadcast probeable.
    if any(_is_directed_broadcast(net, address) for net in networks):
        return Decision(False, REASON_SPECIAL_USE, text)
    if any(_contains(net, address) for net in _parsed(scope.excluded_networks)):
        return Decision(False, REASON_EXCLUDED, text)
    if not networks:
        return Decision(False, REASON_EMPTY_SCOPE, text)
    if any(_contains(net, address) for net in networks):
        return Decision(True, REASON_IN_SCOPE, text)
    return Decision(False, REASON_OUT_OF_SCOPE, text)


def _parsed(cidrs: Iterable[str]) -> list[IPNetwork]:
    return [ipaddress.ip_network(cidr) for cidr in cidrs]


def _contains(network: IPNetwork, address: IPAddress) -> bool:
    """Membership across both families. No explicit version match, unlike
    `network_acl.is_cidr_allowed`: that one compares prefixes with `subnet_of`,
    which raises across families, whereas `in` simply answers False."""
    return address in network


def _overlaps(left: IPNetwork, right: IPNetwork) -> bool:
    """Whether two prefixes share any address. `overlaps` raises across families,
    which `_contains` deliberately avoids for addresses; here the version test is
    explicit because both operands are networks."""
    return left.version == right.version and left.overlaps(right)


def _contains_network(outer: IPNetwork, inner: IPNetwork) -> bool:
    """Full containment across both families. `subnet_of` raises on a mismatched
    version, so the guard is not optional."""
    return outer.version == inner.version and inner.subnet_of(outer)  # type: ignore[arg-type]


def _is_directed_broadcast(network: IPNetwork, address: IPAddress) -> bool:
    # /31 and /32 have no broadcast address (RFC 3021), and IPv6 has none at all.
    if network.version != 4 or network.prefixlen > 30:
        return False
    return address.version == 4 and address == network.broadcast_address


def _parse_address(value: str) -> IPAddress | None:
    """Parse a destination address, collapsing IPv4-mapped IPv6 to its IPv4 form so
    `::ffff:169.254.169.254` cannot take a v6-only path around the v4 rules."""
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _parse_cidrs(values: object) -> list[IPNetwork]:
    if not isinstance(values, list):
        return []
    networks: list[IPNetwork] = []
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError:
            continue
    return networks


def _direct_networks(facts: Sequence[Any] | None) -> list[IPNetwork]:
    """The private IPv4 and IPv6 ULA prefixes the agent is directly attached to.

    Down interfaces are not filtered here: the agent reports only up interfaces
    (`internal/hostinfo/netfacts.go`), and an absent `flags` list — an older or
    minimal report — must not be read as "down" and silently empty an agent's scope.
    """
    networks: list[IPNetwork] = []
    for entry in facts or []:
        if not isinstance(entry, Mapping):
            continue
        flags = {str(flag).lower() for flag in entry.get("flags") or []}
        if flags & _EXCLUDED_INTERFACE_FLAGS:
            continue
        for network in _parse_cidrs(entry.get("addrs")):
            if _is_private_network(network):
                networks.append(network)
    return networks


def _is_private_network(network: IPNetwork) -> bool:
    """Whether the *whole* prefix is private, not merely its host address: a
    192.168.8.2/8 report describes 192.0.0.0/8, most of which is public, and putting
    that in scope would be a routing mistake widening a grant."""
    if isinstance(network, ipaddress.IPv4Network):
        return any(network.subnet_of(private) for private in _RFC1918_NETWORKS)
    return network.subnet_of(_ULA_V6)


def _sorted_networks(networks: Iterable[IPNetwork]) -> list[str]:
    """Canonical, de-duplicated CIDR strings. Ordering is part of the scope version,
    so it must not depend on the order interfaces or config entries were written in."""
    return [
        str(net)
        for net in sorted(
            set(networks), key=lambda n: (n.version, int(n.network_address), n.prefixlen)
        )
    ]


def _canonical_hostname(host: str) -> str:
    return str(host).strip().lower().rstrip(".")


def _scope_version(
    networks: Sequence[str],
    direct: Sequence[str],
    excluded: Sequence[str],
    hostnames: Sequence[str],
) -> str:
    """A digest of the scope's four dimensions, not of what produced them.

    Facts arriving in a different order, or an unrelated grant key changing, must
    leave it alone: consumers treat a moved version as "this agent's authorization
    changed" and cancel in-flight work on it.
    """
    payload = "|".join(
        [
            "agent-scope/v1",
            ",".join(networks),
            ",".join(direct),
            ",".join(excluded),
            ",".join(hostnames),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
