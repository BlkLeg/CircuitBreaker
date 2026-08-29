"""Safe (no NET_RAW) discovery: ICMP ping + TCP connect scan + Docker socket."""

import contextlib
import ipaddress
import logging
import os
import socket
import subprocess
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Port service mapping (duplicated to avoid circular imports)
PORT_SERVICE_MAP = {
    80: {"name": "HTTP", "type": "web_server"},
    443: {"name": "HTTPS", "type": "web_server"},
    8006: {"name": "Proxmox", "type": "hypervisor"},
    8060: {"name": "TrueNAS", "type": "storage_appliance"},
    22: {"name": "SSH", "type": "remote_access"},
    3389: {"name": "RDP", "type": "remote_access"},
    161: {"name": "SNMP", "type": "monitoring"},
    8443: {"name": "UniFi", "type": "controller"},
    623: {"name": "IPMI", "type": "out_of_band"},
}

# Common ports probed in safe TCP connect scan (no raw sockets)
SAFE_TCP_PORTS = [22, 23, 80, 139, 161, 443, 445, 3389, 8006, 8060, 8080, 8443, 8888]

# Largest network scan_subnet_safe will expand.  Mirrors
# discovery_network._MAX_CIDR_ADDRESSES (a /12) on purpose — see the comment in
# scan_subnet_safe for why the value is repeated here instead of imported.
_MAX_SCAN_ADDRESSES = 1_048_576

# How many addresses the sweep holds in memory, and hands to the thread pool, at a
# time.  The size guard above bounds the *range*; this bounds the *allocation* inside
# an accepted range, which is a separate problem: a /12 is under the limit and still
# a million host strings and a million eagerly-submitted Futures.  4096 is large
# enough that the pool never starves (max_workers tops out at 100) and small enough
# that peak footprint is a fixed few hundred KB regardless of CIDR size.
_SWEEP_BATCH_ADDRESSES = 4096


def _ping_host(ip: str, timeout: float = 1.0) -> bool:
    """Return True if host responds to ICMP ping.

    Tries ping3 (unprivileged ICMP via SOCK_DGRAM when supported) first,
    then falls back to the system ping binary (setuid/setcap in most distros).
    """
    try:
        import ping3  # optional dep

        result = ping3.ping(ip, timeout=timeout, unit="ms")
        if result is not None and result is not False:
            return True
    except Exception:
        pass

    # Subprocess fallback — /bin/ping is setuid or has cap_net_raw in most images
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False


def _tcp_probe(ip: str, ports: list[int] | None = None, timeout: float = 0.5) -> list[int]:
    """Return list of open TCP ports using connect scan (no raw sockets required)."""
    if ports is None:
        ports = SAFE_TCP_PORTS
    open_ports: list[int] = []
    for port in ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            if s.connect_ex((ip, port)) == 0:
                open_ports.append(port)
            s.close()
        except OSError:
            pass
    return open_ports


def _iter_host_batches(hosts: Iterable[object], batch_size: int) -> Iterator[list[str]]:
    """Yield lists of at most *batch_size* address strings from a lazy host iterator.

    ``ipaddress.IPv4Network.hosts()`` is a generator, and keeping it one is the point:
    ``[str(ip) for ip in network.hosts()]`` materialises the entire range up front, and
    ``ThreadPoolExecutor.map`` then submits every element as a Future before running
    any of them.  Consuming in batches keeps both costs proportional to the batch and
    not to the CIDR.  Do not "tidy" the callers back into a single list.
    """
    iterator = iter(hosts)
    while True:
        batch = [str(ip) for ip in islice(iterator, batch_size)]
        if not batch:
            return
        yield batch


def scan_subnet_safe(cidr: str, max_workers: int = 100) -> list[dict]:
    """Ping sweep + TCP connect scan with no raw socket privileges.

    Returns a list of dicts: {"ip": str, "open_ports": list[int], "ping_alive": bool}
    Only hosts that responded to ping OR have at least one open port are returned.

    Raises ValueError for a range larger than _MAX_SCAN_ADDRESSES; the scan-job
    runner treats that the same way it treats any other scan failure.
    """
    network = ipaddress.IPv4Network(cidr, strict=False)

    # Size-check the network before expanding it.  This is B06's defect one layer
    # down: the comprehension below was unconditional, so the only thing standing
    # between this function and a /8 was whatever the caller happened to validate.
    # That is not a guarantee this function can rely on — it is a plain module-level
    # helper, importable and callable directly, and the sweep in
    # discovery_service.py reaches it through run_in_executor with the job's stored
    # target string.  For a /8 the comprehension allocates 16.7 million str objects
    # and then hands the same 16.7 million items to ThreadPoolExecutor.map, which
    # submits every one of them as a Future up front rather than lazily: gigabytes
    # of allocation before the first ICMP packet leaves the box, on a worker thread
    # with no timeout around it.
    #
    # num_addresses is an O(1) integer on the network object, so testing it first
    # means nothing at all is materialised for a range we are going to refuse.
    #
    # The limit is deliberately the same 1_048_576 that
    # discovery_network._validate_cidr already enforces one layer up, so no CIDR
    # that reaches this function through the normal scan path changes verdict: this
    # closes the direct-call hole, it does not tighten scan policy.  If either
    # number moves, move both — the constant is duplicated here rather than
    # imported for the same reason PORT_SERVICE_MAP above is (circular import).
    if network.num_addresses > _MAX_SCAN_ADDRESSES:
        raise ValueError(
            f"CIDR {cidr} is too large for a safe sweep "
            f"(max {_MAX_SCAN_ADDRESSES} addresses). Use a smaller range (e.g. /24)."
        )

    # Phase 1: parallel ICMP ping sweep, one bounded batch at a time.  The results
    # kept across batches are only the addresses that answered, which is bounded by
    # what is actually on the wire rather than by the size of the range.
    alive: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for batch in _iter_host_batches(network.hosts(), _SWEEP_BATCH_ADDRESSES):
            alive.extend(ip for ip, up in zip(batch, ex.map(_ping_host, batch), strict=False) if up)
    alive_ips = set(alive)

    # Phase 2: TCP probe all alive hosts (and hosts skipped by ping as fallback).
    # If ping found nothing (firewall blocks ICMP), probe all hosts via TCP — the
    # range is re-walked lazily rather than kept from phase 1, for the same reason.
    if alive:
        target_batches = _iter_host_batches(alive, _SWEEP_BATCH_ADDRESSES)
    else:
        target_batches = _iter_host_batches(network.hosts(), _SWEEP_BATCH_ADDRESSES)

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=50) as ex:
        for batch in target_batches:
            for ip, open_ports in zip(batch, ex.map(_tcp_probe, batch), strict=False):
                if ip in alive_ips or open_ports:
                    found.append(
                        {
                            "ip": ip,
                            "open_ports": open_ports,
                            "ping_alive": ip in alive_ips,
                        }
                    )

    return found


# How long the pre-flight below waits for the daemon's endpoint to accept a
# connection. It is a *connect* timeout on a socket that is closed immediately
# afterwards, not a request timeout, so it can be short: a local socket answers
# in microseconds and a TCP API proxy on the LAN in single-digit milliseconds.
_DOCKER_PROBE_TIMEOUT_S = 2.0


def _probe_docker_endpoint(base_url: str, timeout: float) -> None:
    """Connect to the Docker endpoint and hang up, raising OSError if it refuses.

    Exists so that `docker_client` can decide whether the daemon is reachable
    *using a socket this module owns and closes* — see the second leak described
    there. Transports this cannot dial (``ssh://``, ``npipe://``) are not probed;
    they get the client's own error handling, unchanged.
    """
    parsed = urlparse(base_url)
    if parsed.scheme in ("unix", "http+unix", "unix+http"):
        # urlparse puts an absolute socket path in `path` (netloc is empty for
        # the documented `unix:///var/run/docker.sock` triple slash).
        path = parsed.path or parsed.netloc
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path)
        return
    if parsed.scheme in ("tcp", "http", "https"):
        port = parsed.port or (2376 if parsed.scheme == "https" else 2375)
        with socket.create_connection((parsed.hostname or "localhost", port), timeout=timeout):
            pass
        return


@contextlib.contextmanager
def docker_client(base_url: str, **kwargs: Any) -> Iterator[Any]:
    """Yield a Docker API client and always close the socket it opens.

    Two leaks live here, and both surface far from their cause: the socket is
    only ever reported when the garbage collector gets to it, which under
    pytest's unraisable-exception hook fails whichever unrelated test happens to
    be running (`ResourceWarning: unclosed <socket.socket ... family=1 ...>`).

    1. `DockerClient` is not a context manager in docker 7.2 — it has `close()`
       and nothing else — and every call site here used to drop the reference
       instead of calling it. The client owns a `requests.Session` whose
       keep-alive connection is an AF_UNIX socket for the default `unix://`
       transport, and dropping the reference does not close it.
    2. `DockerClient(...)` negotiates the API version *inside its constructor*
       (`APIClient._retrieve_server_version`), so an unreachable daemon raises
       `DockerException` out of the constructor with the half-built session —
       and its socket — already unreachable to the caller. No `finally:
       client.close()` can reach that one; the object is garbage before the
       assignment happens. This is why the leak fires on hosts with no Docker at
       all: `/var/run/docker.sock` exists, the user is not in the `docker`
       group, and the constructor dies on `PermissionError` having already
       connected.

    Hence the pre-flight: probe the endpoint with a socket this module closes,
    and only build the client once something is listening and willing. An
    absent, dead or forbidden daemon still raises `DockerException`, which is
    what every caller here already handles.
    """
    import importlib

    docker_module = importlib.import_module("docker")
    try:
        _probe_docker_endpoint(base_url, _DOCKER_PROBE_TIMEOUT_S)
    except (OSError, ValueError) as exc:
        # ValueError as well as OSError: urlparse defers parsing the port until
        # `.port` is read, so a malformed CB_DOCKER_HOST surfaces here rather
        # than at construction. Either way the caller gets the DockerException
        # it already handles.
        raise docker_module.errors.DockerException(
            f"Docker daemon at {base_url} is not reachable: {exc}"
        ) from exc

    client = docker_module.DockerClient(base_url=base_url, **kwargs)
    try:
        yield client
    finally:
        client.close()


def docker_discover(
    socket_path: str = "/var/run/docker.sock",
    network_types: list[str] | None = None,
    enable_port_scan: bool = False,
) -> list[dict]:
    """Enhanced Docker discovery with network topology and port scanning.

    Args:
        socket_path: Path to the Docker socket
        network_types: List of network types to scan ('bridge', 'overlay', 'host', 'custom')
        enable_port_scan: Whether to perform port scanning on containers

    Returns a list of dicts with enhanced container and network metadata.
    """
    if network_types is None:
        network_types = ["bridge"]

    docker_host = os.environ.get("CB_DOCKER_HOST", "").strip()
    base_url = docker_host if docker_host else f"unix://{socket_path}"

    try:
        with docker_client(base_url) as client:
            containers: list[dict] = []
            networks_info = {}

            # First, gather network information
            try:
                networks = client.networks.list()
                for net in networks:
                    net_attr = net.attrs
                    driver = net_attr.get("Driver", "")

                    # Filter networks based on requested types
                    net_type = "custom"
                    if driver == "bridge" and net.name in ["bridge", "docker0"]:
                        net_type = "bridge"
                    elif driver == "overlay":
                        net_type = "overlay"
                    elif driver == "host":
                        net_type = "host"
                    elif driver == "bridge":
                        net_type = "bridge"

                    if net_type in network_types:
                        networks_info[net.id] = {
                            "name": net.name,
                            "driver": driver,
                            "type": net_type,
                            "subnet": net_attr.get("IPAM", {})
                            .get("Config", [{}])[0]
                            .get("Subnet", ""),
                            "gateway": net_attr.get("IPAM", {})
                            .get("Config", [{}])[0]
                            .get("Gateway", ""),
                            "scope": net_attr.get("Scope", ""),
                            "containers": [],
                        }
            except Exception as exc:
                logger.warning("Failed to enumerate Docker networks: %s", exc)

            # Process containers with enhanced network information
            for c in client.containers.list(all=True):
                net_settings = c.attrs.get("NetworkSettings", {})
                container_networks = net_settings.get("Networks", {})

                # Get primary IP (prioritize bridge networks)
                primary_ip = net_settings.get("IPAddress", "")
                primary_network = None
                all_networks = []

                for net_name, net_config in container_networks.items():
                    net_ip = net_config.get("IPAddress", "")
                    if net_ip:
                        network_entry = {
                            "name": net_name,
                            "ip": net_ip,
                            "mac": net_config.get("MacAddress", ""),
                            "gateway": net_config.get("Gateway", ""),
                            "network_id": net_config.get("NetworkID", ""),
                        }
                        all_networks.append(network_entry)

                        # Set primary IP to first available or prefer bridge
                        if not primary_ip or net_name == "bridge":
                            primary_ip = net_ip
                            primary_network = network_entry

                # Enhanced port information
                open_ports = []
                if enable_port_scan and c.status == "running":
                    ports = c.attrs.get("NetworkSettings", {}).get("Ports", {})
                    for container_port, host_bindings in ports.items():
                        port_num = (
                            int(container_port.split("/")[0]) if "/" in container_port else None
                        )
                        protocol = container_port.split("/")[1] if "/" in container_port else "tcp"

                        port_info = {
                            "port": port_num,
                            "protocol": protocol,
                            "container_port": container_port,
                            "exposed": host_bindings is not None,
                            "host_bindings": host_bindings or [],
                        }

                        # Try to identify service based on port
                        if port_num in PORT_SERVICE_MAP:
                            port_info.update(PORT_SERVICE_MAP[port_num])

                        open_ports.append(port_info)

                container_data = {
                    "name": c.name,
                    "ip": primary_ip or None,
                    "status": c.status,
                    "image": (c.image.tags or [None])[0],
                    "container_id": c.short_id,
                    "full_id": c.id,
                    "created": c.attrs.get("Created", ""),
                    "networks": all_networks,
                    "primary_network": primary_network,
                    "open_ports": open_ports,
                    "port_count": len(open_ports),
                    "labels": c.attrs.get("Config", {}).get("Labels", {}),
                    "env_vars": c.attrs.get("Config", {}).get("Env", []),
                    "mounts": [
                        {
                            "source": m.get("Source", ""),
                            "destination": m.get("Destination", ""),
                            "type": m.get("Type", ""),
                        }
                        for m in c.attrs.get("Mounts", [])[:5]
                    ],  # Limit to first 5 mounts
                }

                # Add container to relevant networks
                for network in all_networks:
                    net_id = network.get("network_id")
                    if net_id in networks_info:
                        networks_info[net_id]["containers"].append(
                            {"name": c.name, "id": c.short_id, "ip": network["ip"]}
                        )

                containers.append(container_data)

            # Add network topology information to results
            if networks_info:
                containers.append(
                    {
                        "type": "network_topology",
                        "networks": list(networks_info.values()),
                        "network_count": len(networks_info),
                    }
                )

            return containers

    except Exception as exc:
        logger.warning("Docker discovery failed: %s", exc)
        return []


def is_docker_socket_available(socket_path: str = "/var/run/docker.sock") -> bool:
    """Return True if the Docker daemon is reachable via socket or CB_DOCKER_HOST."""
    docker_host = os.environ.get("CB_DOCKER_HOST", "").strip()
    if docker_host:
        return True
    return os.path.exists(socket_path)
