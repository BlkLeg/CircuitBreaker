"""Safe (no NET_RAW) discovery: ICMP ping + TCP connect scan + Docker socket."""

import ipaddress
import logging
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

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


def scan_subnet_safe(cidr: str, max_workers: int = 100) -> list[dict]:
    """Ping sweep + TCP connect scan with no raw socket privileges.

    Returns a list of dicts: {"ip": str, "open_ports": list[int], "ping_alive": bool}
    Only hosts that responded to ping OR have at least one open port are returned.
    """
    network = ipaddress.IPv4Network(cidr, strict=False)
    hosts = [str(ip) for ip in network.hosts()]
    if not hosts:
        return []

    workers = min(max_workers, len(hosts))

    # Phase 1: parallel ICMP ping sweep
    with ThreadPoolExecutor(max_workers=workers) as ex:
        ping_results = list(ex.map(_ping_host, hosts))
    alive_ips = {ip for ip, up in zip(hosts, ping_results, strict=False) if up}

    # Phase 2: TCP probe all alive hosts (and hosts skipped by ping as fallback)
    # If ping found nothing (firewall blocks ICMP), probe all hosts via TCP
    probe_targets = list(alive_ips) if alive_ips else hosts

    with ThreadPoolExecutor(max_workers=min(50, len(probe_targets))) as ex:
        port_results = list(ex.map(_tcp_probe, probe_targets))

    found: list[dict] = []
    for ip, open_ports in zip(probe_targets, port_results, strict=False):
        if ip in alive_ips or open_ports:
            found.append(
                {
                    "ip": ip,
                    "open_ports": open_ports,
                    "ping_alive": ip in alive_ips,
                }
            )

    return found


def docker_discover(
    socket_path: str = "/var/run/docker.sock",
    network_types: list[str] = None,
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

    try:
        import docker  # optional dep

        client = docker.DockerClient(base_url=f"unix://{socket_path}")
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
                        "subnet": net_attr.get("IPAM", {}).get("Config", [{}])[0].get("Subnet", ""),
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
                    port_num = int(container_port.split("/")[0]) if "/" in container_port else None
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
    """Return True if the Docker socket exists at the given path."""
    return os.path.exists(socket_path)
