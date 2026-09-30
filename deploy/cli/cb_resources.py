"""Read-only, stdlib-only resource accounting for the local CB installation.

No backend imports, service changes, or process-name matching. Raw observations
are separate from rates so missing samples and restarted scopes cannot become
plausible-looking zeros or spikes.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import http.client
import io
import json
import math
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.parse
from pathlib import Path

WORKERS = (
    "discovery",
    "notification",
    "telemetry",
    "integration",
    "monitor_scheduler",
    "monitor_poll",
    "monitor_probe_dispatch",
)
GAUGES = {
    "memory_bytes": "bytes",
    "cache_bytes": "bytes",
    "swap_bytes": "bytes",
    "tasks": "tasks",
}
COUNTERS = {
    "cpu_ns": "nanoseconds",
    "read_bytes": "bytes",
    "write_bytes": "bytes",
    "rx_bytes": "bytes",
    "tx_bytes": "bytes",
    "periods": "periods",
    "throttled_periods": "periods",
    "oom_kills": "events",
}
RATES = {
    "cpu_cores": ("cpu_ns", 1e-9, "cores"),
    "read_bytes_per_second": ("read_bytes", 1, "bytes/second"),
    "write_bytes_per_second": ("write_bytes", 1, "bytes/second"),
    "rx_bytes_per_second": ("rx_bytes", 1, "bytes/second"),
    "tx_bytes_per_second": ("tx_bytes", 1, "bytes/second"),
}
PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "ControlGroup",
    "FragmentPath",
    "ExecStart",
    "EnvironmentFiles",
    "Slice",
    "InvocationID",
    "CPUUsageNSec",
    "MemoryCurrent",
    "MemorySwapCurrent",
    "TasksCurrent",
    "IOReadBytes",
    "IOWriteBytes",
    "IPAccounting",
    "IPIngressBytes",
    "IPEgressBytes",
    "MemoryHigh",
    "MemoryMax",
    "CPUQuotaPerSecUSec",
    "AllowedCPUs",
)


class CollectionError(Exception):
    """An actionable, secret-free collection failure."""


def metric(value, unit, source, reason=None):
    return {
        "value": value,
        "unit": unit,
        "source": source,
        "reason": reason if value is None else None,
    }


def integer(value):
    try:
        value = int(value)
        # systemd uses UINT64_MAX as an unavailable accounting value.
        return value if 0 <= value < 2**64 - 1 else None
    except (TypeError, ValueError):
        return None


def run(args, *, input=None):
    if input is not None:
        return exchange(args, input)
    try:
        result = subprocess.run(
            args, input=input, capture_output=True, timeout=8, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(
            f"{args[0]} unavailable or timed out; check access to the runtime"
        ) from exc
    if result.returncode:
        # Runtime stderr can contain URLs, credentials, and full commands.
        raise CollectionError(
            f"{args[0]} request failed; check runtime availability and permissions"
        )
    return result.stdout


def exchange(args, request):
    """Keep transport stdin open until the HTTP response has arrived.

    communicate(input=...) half-closes dial-stdio immediately. That can cancel
    the daemon's request context while it is still assembling stats or /info.
    A watchdog bounds reads without prematurely signalling EOF to the daemon.
    """
    try:
        with subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as process:
            timer = threading.Timer(8, process.kill)
            timer.start()
            try:
                process.stdin.write(request)
                process.stdin.flush()
                output = process.stdout.read()
                process.stdin.close()
                process.wait(timeout=1)
                if process.returncode:
                    raise CollectionError(
                        "Docker transport failed or timed out; check daemon access and permissions"
                    )
                return output
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(
            "Docker transport unavailable or timed out; check daemon access and permissions"
        ) from exc


def load_identity():
    override = os.environ.get("CB_IDENTITY_PATH")
    candidates = (
        [Path(override)]
        if override
        else [
            Path("/etc/circuitbreaker/install-identity.json"),
            Path("/etc/circuit-breaker/install-identity.json"),
            *(
                [Path(os.environ["CB_DATA_DIR"]) / "install-identity.json"]
                if os.environ.get("CB_DATA_DIR")
                else []
            ),
            Path.home() / ".circuit-breaker/install-identity.json",
        ]
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise CollectionError(
                "Install identity is unreadable; run with an account allowed to read it (for example sudo cb resources)"
            ) from exc
        except (OSError, ValueError) as exc:
            raise CollectionError(
                "Install identity is malformed or unreadable; repair it using the installer"
            ) from exc
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != 1
            or data.get("mode") not in ("native", "proxmox", "package", "mono")
            or not data.get("version")
            or not data.get("installed_at")
            or not isinstance(data.get("service_names", []), list)
            or any(not isinstance(name, str) for name in data.get("service_names", []))
            or any(
                not isinstance(data[field], str)
                for field in ("data_dir", "container_name", "env_file", "compose_file")
                if field in data
            )
        ):
            raise CollectionError(
                "Invalid install identity; repair it using the installer"
            )
        return data, path
    raise CollectionError(
        "Install identity is missing; re-run the installer, then cb info. Legacy install.conf cannot establish resource ownership"
    )


def observation(name, state, source, *, owned=True, key=None):
    reason = "accounting unavailable"
    return {
        "id": name,
        "state": state,
        "owned": owned,
        "source": source,
        "key": key,
        "at": time.monotonic(),
        "boundary": None,
        "metrics": {k: metric(None, u, source, reason) for k, u in GAUGES.items()},
        "counters": {k: metric(None, u, source, reason) for k, u in COUNTERS.items()},
        "limits": [],
        "pressure": {},
    }


class Cgroups:
    def __init__(self, root=Path("/sys/fs/cgroup")):
        self.root = root

    def path(self, group):
        if not group or ".." in Path(group).parts:
            return None
        path = self.root / group.lstrip("/")
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return None
        return path

    @staticmethod
    def read(path, filename):
        try:
            return (path / filename).read_text().strip(), None
        except PermissionError:
            return None, "permission denied"
        except OSError:
            return None, "controller unavailable"

    def fill(self, row, group):
        path = self.path(group)
        if path is None:
            return
        try:
            stat = path.stat()
        except OSError:
            return
        row["boundary"] = str(path)
        row["key"] = (row["key"], stat.st_dev, stat.st_ino)

        def scalar(name, filename):
            text, error = self.read(path, filename)
            # Preserve useful systemd counters when a v2 controller is absent.
            if text is not None or row["metrics"][name]["value"] is None:
                row["metrics"][name] = metric(
                    integer(text), GAUGES[name], filename, error or "invalid counter"
                )

        for name, filename in (
            ("memory_bytes", "memory.current"),
            ("swap_bytes", "memory.swap.current"),
            ("tasks", "pids.current"),
        ):
            scalar(name, filename)
        for filename, mapping in (
            (
                "cpu.stat",
                {
                    "usage_usec": ("cpu_ns", 1000),
                    "nr_periods": ("periods", 1),
                    "nr_throttled": ("throttled_periods", 1),
                },
            ),
            ("memory.events", {"oom_kill": ("oom_kills", 1)}),
        ):
            text, _ = self.read(path, filename)
            for line in (text or "").splitlines():
                parts = line.split()
                if (
                    len(parts) == 2
                    and parts[0] in mapping
                    and integer(parts[1]) is not None
                ):
                    name, factor = mapping[parts[0]]
                    row["counters"][name] = metric(
                        int(parts[1]) * factor, COUNTERS[name], filename
                    )
        text, _ = self.read(path, "memory.stat")
        for line in (text or "").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "file":
                row["metrics"]["cache_bytes"] = metric(
                    integer(parts[1]), "bytes", "memory.stat"
                )
        text, _ = self.read(path, "io.stat")
        if text is not None:
            totals = {"rbytes": 0, "wbytes": 0}
            for line in text.splitlines():
                for field in line.split()[1:]:
                    key, _, value = field.partition("=")
                    if key in totals and integer(value) is not None:
                        totals[key] += int(value)
            for key, name in (("rbytes", "read_bytes"), ("wbytes", "write_bytes")):
                row["counters"][name] = metric(totals[key], "bytes", "io.stat")
        for resource in ("cpu", "memory", "io"):
            text, _ = self.read(path, f"{resource}.pressure")
            if text is not None:
                row["pressure"][resource] = text
        row["limits"] = self.limits(path)

    def limits(self, path):
        result = []
        original = path
        while path == self.root or self.root in path.parents:
            limits = {"scope": str(path), "shared_ancestor": path != original}
            for filename in (
                "memory.high",
                "memory.max",
                "memory.current",
                "cpu.max",
                "cpuset.cpus.effective",
            ):
                value, _ = self.read(path, filename)
                if value is not None:
                    limits[filename] = value
            if len(limits) > 2:
                result.append(limits)
            if path == self.root:
                break
            path = path.parent
        return result


def systemd_properties(output):
    return [
        dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        for block in output.decode().strip().split("\n\n")
        if block.strip()
    ]


def unit_registry(mode):
    if mode == "package":
        return [
            "circuit-breaker.service",
            "circuit-breaker-discovery.service",
            "circuit-breaker-nats.service",
            *(
                f"circuit-breaker-worker@{w}.service"
                for w in WORKERS
                if w != "discovery"
            ),
        ]
    return [
        *(
            f"circuitbreaker-{s}.service"
            for s in ("backend", "postgres", "pgbouncer", "redis", "nats")
        ),
        *(f"circuitbreaker-worker@{w}.service" for w in WORKERS),
        "cb-helperd.service",
        "circuitbreaker-docker-proxy.service",
        "circuitbreaker-healthcheck.service",
    ]


def belongs(props, identity):
    """Verify a shipped unit/template and its installation-specific metadata."""
    name = props.get("Id", "")
    fragment = Path(props.get("FragmentPath", "")).name
    template = re.sub(r"@[^.]+(?=\.service$)", "@", name)
    if fragment not in (name, template):
        return False
    exec_start = props.get("ExecStart", "")
    env = props.get("EnvironmentFiles", "")
    if name == "circuitbreaker-postgres.service":
        data = identity.get("data_dir")
        return (
            isinstance(data, str)
            and data.startswith("/")
            and f"{data.rstrip('/')}/postgres" in exec_start
        )
    if identity["mode"] == "package":
        if name == "circuit-breaker-nats.service":
            return (
                "/var/lib/circuit-breaker/nats" in exec_start
                and "/etc/circuit-breaker/circuit-breaker.env" in env
            )
        return (
            "/usr/local/bin/circuit-breaker" in exec_start
            and "/etc/circuit-breaker/circuit-breaker.env" in env
        )
    if name in (
        "circuitbreaker-redis.service",
        "circuitbreaker-nats.service",
        "circuitbreaker-pgbouncer.service",
    ):
        config = {
            "redis": "/etc/redis/redis.conf",
            "nats": "/etc/nats/nats.conf",
            "pgbouncer": "/etc/pgbouncer/pgbouncer.ini",
        }
        role = name.removeprefix("circuitbreaker-").removesuffix(".service")
        return (
            props.get("Slice") == "circuitbreaker.slice" and config[role] in exec_start
        )
    return "/opt/circuitbreaker/" in exec_start or (
        name == "circuitbreaker-docker-proxy.service"
        and "/etc/circuitbreaker/docker-proxy.env" in exec_start
    )


class NativeCollector:
    def __init__(self, identity, *, execute=run, cgroups=None):
        self.identity = identity
        self.execute = execute
        self.cgroups = cgroups or Cgroups()
        self.host = local_capacity(identity["mode"])

    def collect(self):
        names = unit_registry(self.identity["mode"])
        recorded = [
            n if n.endswith(".service") else n + ".service"
            for n in self.identity.get("service_names", [])
        ]
        warnings = [
            "External dependencies, remote agents, browser usage, and unregistered shell jobs are outside local totals."
        ]
        unknown = set(recorded) - set(names) - {"nginx.service"}
        if unknown:
            warnings.append(
                "Identity contains unregistered services; their ownership cannot be verified and they are excluded."
            )
        if self.identity["mode"] != "package":
            names.append("nginx.service")
        raw = self.execute(
            [
                "systemctl",
                "show",
                "--no-pager",
                "--property=" + ",".join(PROPERTIES),
                "--",
                *names,
            ]
        )
        rows = []
        if unknown:
            rows.append(
                observation("unregistered identity services", "unverified", "identity")
            )
        seen = set()
        for props in systemd_properties(raw):
            name = props.get("Id")
            if not name or name in seen:
                continue
            seen.add(name)
            if props.get("LoadState") == "not-found":
                optional = {
                    "cb-helperd.service",
                    "circuitbreaker-docker-proxy.service",
                    "circuitbreaker-healthcheck.service",
                    "circuit-breaker-nats.service",
                    "nginx.service",
                }
                if name in recorded or name not in optional:
                    warnings.append(f"Expected service {name} is missing.")
                    rows.append(observation(name, "missing", "systemd"))
                continue
            shared = name == "nginx.service"
            if not shared and (name not in names or not belongs(props, self.identity)):
                warnings.append(f"Ownership of {name} could not be verified; excluded.")
                rows.append(observation(name, "unverified", "systemd"))
                continue
            row = observation(
                name,
                props.get("ActiveState", "unknown"),
                "systemd",
                owned=not shared,
                key=props.get("InvocationID") or None,
            )
            for name_, prop in (
                ("memory_bytes", "MemoryCurrent"),
                ("swap_bytes", "MemorySwapCurrent"),
                ("tasks", "TasksCurrent"),
            ):
                row["metrics"][name_] = metric(
                    integer(props.get(prop)),
                    GAUGES[name_],
                    f"systemd.{prop}",
                    "accounting unavailable",
                )
            for name_, prop in (
                ("cpu_ns", "CPUUsageNSec"),
                ("read_bytes", "IOReadBytes"),
                ("write_bytes", "IOWriteBytes"),
                ("rx_bytes", "IPIngressBytes"),
                ("tx_bytes", "IPEgressBytes"),
            ):
                value = integer(props.get(prop))
                if (
                    name_ in ("rx_bytes", "tx_bytes")
                    and props.get("IPAccounting") != "yes"
                ):
                    value = None
                row["counters"][name_] = metric(
                    value,
                    COUNTERS[name_],
                    f"systemd.{prop}",
                    "accounting unavailable or disabled",
                )
            row["limits"] = [
                {
                    "scope": name,
                    "shared_ancestor": False,
                    **{
                        key: props[key]
                        for key in (
                            "MemoryHigh",
                            "MemoryMax",
                            "CPUQuotaPerSecUSec",
                            "AllowedCPUs",
                        )
                        if props.get(key)
                    },
                }
            ]
            self.cgroups.fill(row, props.get("ControlGroup"))
            row["at"] = time.monotonic()
            rows.append(row)
        if not any(
            r["owned"] and r["state"] not in ("missing", "unverified") for r in rows
        ):
            raise CollectionError(
                "No app-owned services could be verified; check the install identity and systemd permissions"
            )
        # Sum disjoint services, not target dependencies or a possibly shared slice.
        warnings.append(
            "Totals cover verified service cgroups; residual charges directly on parent slices are not attributed."
        )
        if any(
            r["id"] == "circuitbreaker-docker-proxy.service" and r["state"] == "active"
            for r in rows
        ):
            try:
                # This service uses the local system daemon. Never merge a user's
                # remote Docker context into native host resource accounting.
                payload, _, _ = DockerCollector(
                    {"container_name": "cb-docker-proxy"},
                    api=LocalDockerAPI(),
                    proxy=True,
                ).collect()
                rows.extend(payload)
            except CollectionError:
                rows.append(
                    observation("docker-proxy payload", "unavailable", "local-docker")
                )
                warnings.append(
                    "Docker proxy payload could not be verified/read on the local daemon; totals are partial. Check Docker socket permissions."
                )
        if any(not r["owned"] for r in rows):
            warnings.append(
                "nginx is shared/unattributed and excluded from app totals."
            )
        return rows, self.host, warnings


def local_capacity(mode):
    memory = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return {
        "name": socket.gethostname(),
        "scope": "visible guest/host (not guaranteed physical capacity)",
        "cpus": os.cpu_count(),
        "memory_bytes": memory,
        "effective_capacity": None,
        "effective_capacity_reason": "ancestor quotas and guest boundaries may restrict visible capacity",
    }


class _ResponseSocket:
    def __init__(self, data):
        self.data = data

    def makefile(self, *_args):
        return io.BytesIO(self.data)


class DockerAPI:
    """Docker's transport handles context, SSH, TLS and DOCKER_HOST for us."""

    def __init__(self, execute=run):
        self.execute = execute

    def endpoint(self):
        """Describe the selected daemon without userinfo or URL query secrets."""
        try:
            context = self.execute(["docker", "context", "show"]).decode().strip()
            if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
                endpoint = os.environ["DOCKER_HOST"]
            else:
                endpoint = json.loads(
                    self.execute(
                        [
                            "docker",
                            "context",
                            "inspect",
                            context,
                            "--format",
                            "{{json .Endpoints.docker.Host}}",
                        ]
                    )
                )
            parsed = urllib.parse.urlsplit(endpoint)
            return f"{parsed.scheme}://{parsed.hostname or 'local socket'}" + (
                f":{parsed.port}" if parsed.port else ""
            )
        except (CollectionError, ValueError, TypeError):
            return "selected Docker CLI context (endpoint unavailable)"

    def get(self, path):
        request = (
            f"GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n".encode(
                "ascii"
            )
        )
        data = self.execute(["docker", "system", "dial-stdio"], input=request)
        try:
            response = http.client.HTTPResponse(_ResponseSocket(data))
            response.begin()
            if response.status != 200:
                raise CollectionError(
                    f"Docker API returned HTTP {response.status}; check the recorded container and runtime permissions"
                )
            value = json.loads(response.read())
            if not isinstance(value, dict):
                raise TypeError("not an object")
            return value
        except (ValueError, TypeError, http.client.HTTPException) as exc:
            raise CollectionError(
                "Docker returned an invalid resource response"
            ) from exc


class LocalDockerAPI(DockerAPI):
    """Native system service accounting must use the local system socket."""

    def endpoint(self):
        return "unix://local socket"

    def get(self, path):
        connection = http.client.HTTPConnection("localhost", timeout=8)
        try:
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(8)
            connection.sock.connect("/var/run/docker.sock")
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200:
                raise CollectionError("Local Docker resource lookup failed")
            data = json.loads(response.read())
            if not isinstance(data, dict):
                raise CollectionError("Local Docker returned invalid resource data")
            return data
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise CollectionError(
                "Local Docker socket is unavailable or unreadable"
            ) from exc
        finally:
            connection.close()


class DockerCollector:
    def __init__(self, identity, *, api=None, proxy=False):
        self.identity = identity
        self.api = api or DockerAPI()
        self.host = None
        self.proxy = proxy

    def collect(self):
        container = self.identity.get("container_name")
        if not isinstance(container, str) or not container:
            raise CollectionError(
                "Mono identity has no container_name; repair the host install identity"
            )
        info = self.api.get(
            "/containers/" + urllib.parse.quote(container, safe="") + "/json"
        )
        if self.proxy:
            image = info.get("Config", {}).get("Image", "")
            mounts = info.get("Mounts", [])
            if (
                info.get("Name") != "/cb-docker-proxy"
                or not image.startswith("tecnativa/docker-socket-proxy:")
                or not any(
                    m.get("Source") == "/var/run/docker.sock"
                    and m.get("Destination") == "/var/run/docker.sock"
                    for m in mounts
                )
            ):
                raise CollectionError(
                    "Docker proxy container does not match the installed service"
                )
        container_id = info["Id"]
        if self.host is None:
            daemon = self.api.get("/info")
            # Denominators ALWAYS come from the daemon, never this CLI machine.
            self.host = {
                "name": daemon.get("Name"),
                "scope": "Docker daemon host/VM",
                "cpus": daemon.get("NCPU"),
                "memory_bytes": daemon.get("MemTotal"),
                "effective_capacity": None,
                "effective_capacity_reason": "container and ancestor limits may restrict daemon capacity",
            }
            self.host["endpoint"] = (
                self.api.endpoint() if isinstance(self.api, DockerAPI) else "fixture"
            )
        state = info.get("State", {})
        row = observation(
            container_id,
            state.get("Status", "unknown"),
            "docker-engine",
            key=(container_id, state.get("StartedAt")),
        )
        row["boundary"] = "docker:" + container_id
        row["label"] = "Docker proxy payload" if self.proxy else "Mono container"
        config = info.get("HostConfig", {})
        row["limits"] = [
            {
                "scope": container_id,
                "shared_ancestor": False,
                **{
                    k: config.get(k)
                    for k in (
                        "Memory",
                        "MemoryReservation",
                        "MemorySwap",
                        "NanoCpus",
                        "CpuQuota",
                        "CpuPeriod",
                        "CpusetCpus",
                    )
                },
            }
        ]
        warnings = [
            "Container total includes embedded services; external dependencies and remote agents are excluded.",
            "Docker exposes container limits; hidden ancestor limits may also apply.",
        ]
        if not state.get("Running"):
            warnings.append(
                "Container is stopped; runtime counters are unavailable, not assumed zero."
            )
            return [row], self.host, warnings
        stats = self.api.get(
            f"/containers/{container_id}/stats?stream=false&one-shot=true"
        )
        row["at"] = time.monotonic()
        # Engine responses can reuse a cached observation; use the daemon's
        # observation time for deltas, never the time we received that cache.
        if stats.get("read"):
            try:
                row["at"] = dt.datetime.fromisoformat(
                    stats["read"].replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                raise CollectionError(
                    "Docker returned an invalid sample timestamp"
                ) from None
        memory = stats.get("memory_stats", {})
        memstats = memory.get("stats", {})
        row["metrics"]["memory_bytes"] = metric(
            integer(memory.get("usage")),
            "bytes",
            "docker.memory_stats.usage",
            "accounting unavailable",
        )
        row["metrics"]["cache_bytes"] = metric(
            integer(
                memstats.get("file", memstats.get("total_cache", memstats.get("cache")))
            ),
            "bytes",
            "docker.memory_stats.stats",
            "cache counter unavailable",
        )
        row["metrics"]["swap_bytes"] = metric(
            integer(memstats.get("swap", memstats.get("total_swap"))),
            "bytes",
            "docker.memory_stats.stats",
            "swap counter unavailable",
        )
        row["metrics"]["tasks"] = metric(
            integer(stats.get("pids_stats", {}).get("current")),
            "tasks",
            "docker.pids_stats",
            "accounting unavailable",
        )
        cpu = stats.get("cpu_stats", {})
        row["counters"]["cpu_ns"] = metric(
            integer(cpu.get("cpu_usage", {}).get("total_usage")),
            "nanoseconds",
            "docker.cpu_stats",
            "CPU counter unavailable",
        )
        for name, key in (
            ("periods", "periods"),
            ("throttled_periods", "throttled_periods"),
        ):
            row["counters"][name] = metric(
                integer(cpu.get("throttling_data", {}).get(key)),
                "periods",
                "docker.cpu_stats.throttling_data",
                "throttling counter unavailable",
            )
        ios = stats.get("blkio_stats", {}).get("io_service_bytes_recursive")
        if isinstance(ios, list):
            for op, name in (("read", "read_bytes"), ("write", "write_bytes")):
                value = sum(i["value"] for i in ios if str(i.get("op")).lower() == op)
                row["counters"][name] = metric(value, "bytes", "docker.blkio_stats")
        network = config.get("NetworkMode", "")
        if network == "host" or network.startswith("container:"):
            warnings.append(
                "Shared network namespace: app network usage is unavailable."
            )
        elif isinstance(stats.get("networks"), dict) and stats["networks"]:
            for name in ("rx_bytes", "tx_bytes"):
                row["counters"][name] = metric(
                    sum(n[name] for n in stats["networks"].values()),
                    "bytes",
                    "docker.networks",
                )
        return [row], self.host, warnings


class ContainerCollector:
    """Inside mono, read the container's cgroup without a Docker socket."""

    def __init__(self, identity, *, cgroups=None):
        self.identity = identity
        self.cgroups = cgroups or Cgroups()
        self.host = local_capacity("mono")
        self.host["scope"] = "container-visible guest/host capacity"

    def collect(self):
        try:
            group = next(
                line[3:]
                for line in Path("/proc/self/cgroup").read_text().splitlines()
                if line.startswith("0::")
            )
        except (OSError, StopIteration) as exc:
            raise CollectionError(
                "Container cgroup v2 is unavailable; run cb resources on the Docker host"
            ) from exc
        path = self.cgroups.path(group)
        if path is None or not (path / "memory.current").exists():
            raise CollectionError(
                "Container accounting boundary is hidden; run cb resources on the Docker host"
            )
        row = observation("mono-container", "running", "cgroup-v2", key=group)
        self.cgroups.fill(row, group)
        return (
            [row],
            self.host,
            [
                "Container-local accounting includes this collector; external dependencies are excluded.",
                "Network namespace ownership and enclosing limits cannot be verified inside the container; network usage is unavailable.",
            ],
        )


def with_rates(current, previous):
    old = {r["id"]: r for r in previous}
    for row in current:
        prior = old.get(row["id"])
        elapsed = row["at"] - prior["at"] if prior else 0
        valid = prior is not None and row["key"] == prior["key"] and elapsed > 0
        row["interval_seconds"] = elapsed if valid else None
        for name, (counter, scale, unit) in RATES.items():
            value = row["counters"][counter]["value"]
            before = prior["counters"][counter]["value"] if valid else None
            available = value is not None and before is not None and value >= before
            reason = row["counters"][counter]["reason"] or "warming up or counter reset"
            row["metrics"][name] = metric(
                (value - before) / elapsed * scale if available else None,
                unit,
                row["counters"][counter]["source"],
                reason,
            )
        for name, numerator, denominator in (
            ("throttled_period_percent", "throttled_periods", "periods"),
        ):
            values = (
                [
                    r["counters"][c]["value"]
                    for r in (row, prior)
                    for c in (numerator, denominator)
                ]
                if valid
                else []
            )
            value = None
            if values and all(v is not None for v in values):
                a, b, c, d = values
                if b > d and a >= c:
                    value = min(100, 100 * (a - c) / (b - d))
            row["metrics"][name] = metric(
                value, "percent of periods", "counter delta", "no valid elapsed periods"
            )
    return current


def report(rows, host, warnings, elapsed):
    included = []
    for row in rows:
        boundary = row["boundary"]
        duplicate = boundary and any(
            r["owned"]
            and r is not row
            and r["boundary"]
            and (
                boundary.startswith(r["boundary"] + "/")
                or (boundary == r["boundary"] and rows.index(r) < rows.index(row))
            )
            for r in rows
        )
        row["included_in_totals"] = bool(row["owned"] and not duplicate)
        if row["included_in_totals"]:
            included.append(row)
    totals = {}
    for name, unit in {**GAUGES, **{k: v[2] for k, v in RATES.items()}}.items():
        values = [r["metrics"][name]["value"] for r in included]
        available = [v for v in values if v is not None]
        totals[name] = metric(
            sum(available) if available else None,
            unit,
            "disjoint owned scopes",
            "no measurements available",
        )
        totals[name]["complete"] = len(available) == len(values) and bool(values)
        totals[name]["measured_components"] = len(available)
        totals[name]["expected_components"] = len(values)
    for name, numerator, denom in (
        ("visible_cpu_percent", "cpu_cores", host.get("cpus")),
        ("visible_memory_percent", "memory_bytes", host.get("memory_bytes")),
    ):
        value = totals[numerator]["value"]
        totals[name] = metric(
            100 * value / denom if value is not None and denom else None,
            "percent",
            "visible capacity",
            "capacity unavailable",
        )
        totals[name]["complete"] = totals[numerator]["complete"]
    # Sampling keys are private implementation details, not stable identifiers.
    public_rows = [{k: v for k, v in r.items() if k not in ("key", "at")} for r in rows]
    return {
        "schema_version": 1,
        "sampled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "interval_seconds": elapsed,
        "measurement_host": host,
        "scope": "verified local app-owned services/containers",
        "components": public_rows,
        "totals": totals,
        "warnings": warnings,
    }


def pretty(value, unit="bytes"):
    if value is None:
        return "n/a"
    if unit == "cores":
        return f"{value:.2f}"
    if value == 0:
        return "0 B"
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or suffix == "TiB":
            return f"{value:.1f} {suffix}"
        value /= 1024


def short_name(name):
    """A unit or scope name as a person would say it: `circuitbreaker-api.service` -> `api`."""
    name = name.removesuffix(".service")
    for prefix in ("circuitbreaker-", "circuit-breaker-"):
        name = name.removeprefix(prefix)
    return name.replace("worker@", "worker: ")


def component_label(row):
    return short_name(row.get("label") or row["id"]) + (
        " (shared)" if not row["owned"] else ""
    )


def limit_summary(limit):
    parts = []
    maximum = limit.get("memory.max", limit.get("MemoryMax", limit.get("Memory")))
    if maximum is not None:
        value = integer(maximum)
        unlimited = maximum in ("max", "infinity") or ("Memory" in limit and value == 0)
        bound = "unlimited" if unlimited else pretty(value)
        current = integer(limit.get("memory.current"))
        parts.append(
            "RAM "
            + (pretty(current) + " / " if current is not None else "cap ")
            + bound
        )
    high = integer(limit.get("memory.high", limit.get("MemoryHigh")))
    if high is not None:
        parts.append("RAM high " + pretty(high))
    cpu = limit.get("cpu.max", "").split()
    if len(cpu) == 2 and integer(cpu[0]) is not None and integer(cpu[1]):
        parts.append(f"CPU cap {int(cpu[0]) / int(cpu[1]):.2f} cores")
    elif limit.get("NanoCpus"):
        parts.append(f"CPU cap {limit['NanoCpus'] / 1e9:.2f} cores")
    elif (limit.get("CpuQuota") or 0) > 0 and limit.get("CpuPeriod"):
        parts.append(f"CPU cap {limit['CpuQuota'] / limit['CpuPeriod']:.2f} cores")
    elif limit.get("CPUQuotaPerSecUSec") not in (None, "infinity"):
        parts.append(f"CPU time budget {limit['CPUQuotaPerSecUSec']} per second")
    cpus = limit.get("cpuset.cpus.effective", limit.get("CpusetCpus"))
    if cpus:
        parts.append("CPU set " + cpus)
    return ", ".join(parts)


BAR_WIDTH = 20


def bar(percent, *, fancy):
    """A fixed-width capacity bar; ASCII when the terminal cannot print block glyphs."""
    if percent is None:
        return ""
    filled = round(min(max(percent, 0.0), 100.0) / 100 * BAR_WIDTH)
    full, empty = ("█", "░") if fancy else ("#", "-")
    return "[" + full * filled + empty * (BAR_WIDTH - filled) + "]"


def stdout_is_unicode():
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    return encoding in ("utf8", "utf16", "utf32")


def sampled_time(iso):
    try:
        moment = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso)
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


# Below this, a stall or throttle rate is background noise, not something to act on.
ATTENTION_PERCENT = 1.0


def pressure_summary(resource, text):
    """`some avg10=1.25 avg60=...` -> `memory pressure: tasks stalled 1.3% of the last 10s`."""
    for line in text.splitlines():
        match = re.search(r"avg10=([\d.]+)", line)
        if match and float(match[1]) >= ATTENTION_PERCENT:
            who = "all tasks" if line.startswith("full") else "tasks"
            return f"{resource} pressure: {who} stalled {float(match[1]):.1f}% of the last 10s"
    return None


def cpu_count(cpuset):
    """Number of CPUs in a cpuset list such as `0-3,6`, or None if unparseable."""
    total = 0
    for part in str(cpuset).split(","):
        bounds = part.strip().split("-")
        try:
            low, high = int(bounds[0]), int(bounds[-1])
        except ValueError:
            return None
        total += high - low + 1
    return total or None


def limit_parts(limit, cpus):
    """The constraints in one limit record, as short phrases.

    Drops what does not constrain anything: an unlimited memory ceiling and a
    CPU set that already spans every visible CPU."""
    memory, cpu = [], []
    maximum = limit.get("memory.max", limit.get("MemoryMax", limit.get("Memory")))
    value = integer(maximum)
    unlimited = maximum in (None, "max", "infinity") or (
        "Memory" in limit and value == 0
    )
    if not unlimited and value is not None:
        memory.append(pretty(value).replace(".0 ", " "))
    high = integer(limit.get("memory.high", limit.get("MemoryHigh")))
    if high is not None:
        memory.append(f"high {pretty(high).replace('.0 ', ' ')}")
    quota = limit.get("cpu.max", "").split()
    cores = None
    if len(quota) == 2 and integer(quota[0]) is not None and integer(quota[1]):
        cores = int(quota[0]) / int(quota[1])
    elif limit.get("NanoCpus"):
        cores = limit["NanoCpus"] / 1e9
    elif (limit.get("CpuQuota") or 0) > 0 and limit.get("CpuPeriod"):
        cores = limit["CpuQuota"] / limit["CpuPeriod"]
    if cores is not None:
        cpu.append(f"{cores:g} CPU")
    elif limit.get("CPUQuotaPerSecUSec") not in (None, "infinity"):
        cpu.append(f"{limit['CPUQuotaPerSecUSec']}/s CPU time")
    cpuset = limit.get("cpuset.cpus.effective", limit.get("CpusetCpus"))
    if cpuset and not (cpus and cpu_count(cpuset) == cpus):
        cpu.append(f"CPUs {cpuset}")
    return memory, cpu


def own_limit(row, cpus):
    """A component's own caps as `512 MiB, 0.5 CPU`; `-` when it has none."""
    memory, cpu = [], []
    for limit in row.get("limits", []):
        if limit.get("shared_ancestor"):
            continue
        m, c = limit_parts(limit, cpus)
        memory += [x for x in m if x not in memory]
        cpu += [x for x in c if x not in cpu]
    return ", ".join(memory + cpu) or "-"


# Metrics a reader recognises, grouped the way USAGE reports them.
MEASURED = (
    ("CPU", ("cpu_cores",)),
    ("Memory", ("memory_bytes",)),
    ("Swap", ("swap_bytes",)),
    ("Disk I/O", ("read_bytes_per_second", "write_bytes_per_second")),
    ("Network", ("rx_bytes_per_second", "tx_bytes_per_second")),
)


def render(data, *, sort="cpu_cores", expanded=True, width=100, fancy=None):
    if fancy is None:
        fancy = stdout_is_unicode()
    total = data["totals"]
    host = data["measurement_host"]
    cpus = host.get("cpus")
    wide = width >= 110

    def amount(name, rate=False):
        m = total[name]
        text = pretty(m["value"], m["unit"])
        return text + ("/s" if rate and m["value"] is not None else "")

    def partial(*names):
        # Name the gap once per line, after the numbers, never inside a unit.
        for n in names:
            m = total[n]
            if m["value"] is not None and not m.get("complete", True):
                return f"  ({m['measured_components']} of {m['expected_components']} measured)"
        return ""

    scope = host.get("scope", "collection failed")
    lines = [
        f"Circuit Breaker resources - {data['mode']}"
        + (f" on {host['name']}" if host.get("name") else " (host unavailable)"),
        (
            f"Sampled {sampled_time(data['sampled_at'])} over "
            f"{data['interval_seconds']:.1f}s - {scope}"
        ),
        "",
        "USAGE",
    ]

    cpu_share = total["visible_cpu_percent"]["value"]
    memory_share = total["visible_memory_percent"]["value"]
    cores = amount("cpu_cores") + (
        " cores" if total["cpu_cores"]["value"] is not None else ""
    )
    cpu_line = f"  CPU      {cores:<16}"
    if cpu_share is not None:
        cpu_line += f"{bar(cpu_share, fancy=fancy)} {cpu_share:5.1f}% of {cpus} CPUs"
    else:
        cpu_line += f"{cpus or '?'} CPUs visible"
    lines.append(cpu_line + partial("cpu_cores"))
    memory_line = f"  Memory   {amount('memory_bytes'):<16}"
    if memory_share is not None:
        memory_line += (
            f"{bar(memory_share, fancy=fancy)} {memory_share:5.1f}% of "
            f"{pretty(host.get('memory_bytes'))}"
        )
    lines.append(memory_line + partial("memory_bytes"))
    lines.append(
        f"           cache {amount('cache_bytes')}, swap {amount('swap_bytes')}"
    )
    lines.append(
        f"  Disk     read {amount('read_bytes_per_second', True)}, "
        f"write {amount('write_bytes_per_second', True)}"
        + partial("read_bytes_per_second", "write_bytes_per_second")
    )
    lines.append(
        f"  Network  in {amount('rx_bytes_per_second', True)}, "
        f"out {amount('tx_bytes_per_second', True)}"
        + partial("rx_bytes_per_second", "tx_bytes_per_second")
    )
    if cpu_share is not None or memory_share is not None:
        lines.append(
            "  Shares are of visible capacity; limits above this install may be lower."
        )

    def ordering(r):
        # Everything idle reads as 0.00 cores; memory then name keeps it stable.
        return (
            -round(r["metrics"][sort]["value"] or 0, 2 if sort == "cpu_cores" else 0),
            -(r["metrics"]["memory_bytes"]["value"] or 0),
            component_label(r),
        )

    rows = sorted(data["components"], key=ordering)
    hidden = []
    shown = []
    for row in rows:
        if not expanded and "worker@" in row["id"]:
            hidden.append(row)
        else:
            shown.append(row)
    if hidden:
        group = {
            "id": f"workers ({len(hidden)}), e to expand",
            "owned": True,
            "state": "group",
            "metrics": {},
            "limits": [],
        }
        for name in (
            "cpu_cores",
            "memory_bytes",
            "read_bytes_per_second",
            "write_bytes_per_second",
        ):
            values = [r["metrics"][name]["value"] for r in hidden]
            group["metrics"][name] = {
                "value": sum(values) if all(v is not None for v in values) else None
            }
        shown.append(group)

    lines += [
        "",
        f"COMPONENTS  (sorted by {'CPU' if sort == 'cpu_cores' else 'memory'})",
    ]
    if shown:
        name_width = min(
            32, max(len("Component"), *(len(component_label(r)) for r in shown))
        )
        caps = [own_limit(r, cpus) for r in shown]
        cap_width = max(len("Limit"), *(len(c) for c in caps))
        header = f"  {'Component':<{name_width}}  {'CPU':>5}  {'Memory':>10}"
        if wide:
            header += f"  {'Read/s':>10}  {'Write/s':>10}"
        lines.append(header + f"  {'Limit':<{cap_width}}  State")
        for row, cap in zip(shown, caps):
            m = row["metrics"]
            line = (
                f"  {component_label(row)[:name_width]:<{name_width}}"
                f"  {pretty(m['cpu_cores']['value'], 'cores'):>5}"
                f"  {pretty(m['memory_bytes']['value']):>10}"
            )
            if wide:
                line += (
                    f"  {pretty(m['read_bytes_per_second']['value']):>10}"
                    f"  {pretty(m['write_bytes_per_second']['value']):>10}"
                )
            lines.append(line + f"  {cap:<{cap_width}}  {row['state']}")
    else:
        lines.append("  No components measured.")

    # Only ceilings shared by several components get their own section; a
    # component's own caps are its Limit column above.
    shared, attention = [], []
    scopes = set()
    for row in rows:
        for limit in row["limits"]:
            scope = limit["scope"]
            if not limit.get("shared_ancestor") or scope in scopes:
                continue
            scopes.add(scope)
            memory, cpu = limit_parts(limit, cpus)
            if not memory and not cpu:
                continue
            current = integer(limit.get("memory.current"))
            phrases = []
            if memory:
                phrases.append(
                    "RAM "
                    + (f"{pretty(current)} of " if current is not None else "")
                    + ", ".join(memory)
                )
            phrases += cpu
            label = Path(scope).name if scope.startswith("/") else scope
            shared.append((label, ", ".join(phrases) + "  (whole slice)"))
        name = component_label(row)
        throttle = row["metrics"]["throttled_period_percent"]["value"]
        if throttle and throttle >= ATTENTION_PERCENT:
            attention.append((name, f"CPU throttled in {throttle:.1f}% of periods"))
        oom = row["counters"]["oom_kills"]["value"]
        if oom:
            attention.append((name, f"{oom} out-of-memory kill(s) since it started"))
        for resource, text in row["pressure"].items():
            summary = pressure_summary(resource, text)
            if summary:
                attention.append((name, summary))

    for title, entries in (("SHARED LIMITS", shared), ("ATTENTION", attention)):
        if entries:
            label_width = min(32, max(len(label) for label, _ in entries))
            lines += ["", title]
            lines += [f"  {label:<{label_width}}  {text}" for label, text in entries]
    if data["warnings"]:
        lines += ["", "NOTICES"]
        lines += [f"  - {w}" for w in data["warnings"]]

    gaps = []
    # Count over the components the totals cover, so "3 of 16" agrees with USAGE.
    counted = [r for r in rows if r.get("included_in_totals", True)]
    for label, names in MEASURED:
        missing = [
            r for r in counted if any(r["metrics"][n]["value"] is None for n in names)
        ]
        if not missing:
            continue
        reasons = sorted(
            {
                r["metrics"][n]["reason"]
                for r in missing
                for n in names
                if r["metrics"][n]["value"] is None and r["metrics"][n]["reason"]
            }
        )
        who = (
            ", ".join(component_label(r) for r in missing)
            if len(missing) <= 3
            else f"{len(missing)} of {len(counted)} components"
        )
        gaps.append(
            f"  {label + ':':<10}{who}"
            + (f"  ({'; '.join(reasons)})" if reasons else "")
        )
    if gaps:
        lines += ["", "NOT MEASURED"] + gaps
    return "\n".join(line.rstrip() for line in lines)


# The web app's default (Gruvbox) palette, so the terminal view reads as the
# same product: --color-primary, --color-danger, --color-success and
# --color-warning from apps/frontend/src/styles/main.css, plus Gruvbox grey for
# de-emphasis. Each role carries a 24-bit colour and its nearest xterm-256 slot.
THEME = {
    "primary": ((0xFE, 0x80, 0x19), 208),
    "danger": ((0xFB, 0x49, 0x34), 203),
    "success": ((0xB8, 0xBB, 0x26), 142),
    "warning": ((0xD7, 0x99, 0x21), 172),
    "muted": ((0x92, 0x83, 0x74), 245),
}
SECTIONS = (
    "USAGE",
    "COMPONENTS",
    "SHARED LIMITS",
    "ATTENTION",
    "NOTICES",
    "NOT MEASURED",
)


def color_mode(stream):
    """None for plain text, else "truecolor" or "256". Honours NO_COLOR and TERM=dumb."""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return None
    if not hasattr(stream, "isatty") or not stream.isatty():
        return None
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    return "256"


def paint(text, role, mode, *, bold=False):
    if not mode or not text:
        return text
    (r, g, b), slot = THEME[role]
    color = f"38;2;{r};{g};{b}" if mode == "truecolor" else f"38;5;{slot}"
    return f"\033[{'1;' if bold else ''}{color}m{text}\033[0m"


def colorize(text, mode):
    """Theme rendered output. Runs after layout, wrapping and paging, so escape
    codes never count toward a line's width; plain output is unchanged."""
    if not mode:
        return text
    out, section = [], None
    for index, line in enumerate(text.split("\n")):
        stripped = line.strip()
        head = stripped.split("  (")[0]
        if head in SECTIONS:
            section = head
            rest = stripped[len(head) :]
            out.append(
                paint(head, "primary", mode, bold=True) + paint(rest, "muted", mode)
            )
            continue
        if index == 0 and line.startswith("Circuit Breaker"):
            out.append(
                paint("Circuit Breaker", "primary", mode, bold=True)
                + line[len("Circuit Breaker") :]
            )
            continue
        if index == 1 or stripped.startswith("Shares are of visible"):
            out.append(paint(line, "muted", mode))
            continue
        if section == "COMPONENTS" and stripped.startswith("Component "):
            out.append(paint(line, "muted", mode))
            continue
        if section == "ATTENTION" and stripped:
            out.append(paint(line, "danger", mode))
            continue
        if section == "NOTICES" and stripped:
            out.append(paint(line, "warning", mode))
            continue
        if section == "NOT MEASURED" and stripped:
            out.append(paint(line, "muted", mode))
            continue
        line = re.sub(
            r"\[([█#]*)([░-]*)\]( +)([\d.]+)%",
            lambda m: (
                paint("[", "muted", mode)
                + paint(
                    m[1],
                    "danger"
                    if float(m[4]) >= 90
                    else "warning"
                    if float(m[4]) >= 75
                    else "primary",
                    mode,
                )
                + paint(m[2], "muted", mode)
                + paint("]", "muted", mode)
                + m[3]
                + m[4]
                + "%"
            ),
            line,
        )
        line = re.sub(
            r"\(partial: [^)]*\)", lambda m: paint(m[0], "warning", mode), line
        )
        line = re.sub(r"\bn/a\b", lambda m: paint(m[0], "muted", mode), line)
        if section == "COMPONENTS":
            line = re.sub(
                r"  (active|running)$",
                lambda m: "  " + paint(m[1], "success", mode),
                line,
            )
            line = re.sub(
                r"  (failed|dead|restarting)$",
                lambda m: "  " + paint(m[1], "danger", mode),
                line,
            )
            # A oneshot unit (healthcheck) is normally inactive between runs.
            line = re.sub(
                r"  (inactive|exited)$",
                lambda m: "  " + paint(m[1], "muted", mode),
                line,
            )
        out.append(line)
    return "\n".join(out)


@contextlib.contextmanager
def terminal(enabled):
    if not enabled:
        yield
        return
    import termios
    import tty

    settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()
        yield
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


def interval(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "interval must be a number of seconds >= 1"
        ) from exc
    if not math.isfinite(number) or number < 1:
        raise argparse.ArgumentTypeError(
            "interval must be a finite number of seconds >= 1"
        )
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cb resources",
        description="Show CPU, memory, swap, disk I/O, network usage, and resource limits for this Circuit Breaker installation.",
    )
    parser.add_argument(
        "--watch", action="store_true", help="refresh until q or Ctrl-C"
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON snapshot, or JSON Lines with --watch"
    )
    parser.add_argument(
        "--interval",
        type=interval,
        default=2.0,
        help="sampling interval in seconds (default: 2; minimum: 1)",
    )
    args = parser.parse_args(argv)
    identity, identity_path = load_identity()
    if identity["mode"] == "mono":
        # Only the identity placed in this container's data volume authorizes
        # observing our own cgroup. A host identity may select a different app.
        inside = (
            Path("/.dockerenv").exists()
            and identity_path
            == Path(identity.get("data_dir") or "/data") / "install-identity.json"
        )
        collector = (
            ContainerCollector(identity) if inside else DockerCollector(identity)
        )
    else:
        collector = NativeCollector(identity)
    interactive = (
        args.watch and not args.json and sys.stdout.isatty() and sys.stdin.isatty()
    )
    sort, expanded, scroll = "cpu_cores", not interactive, 0
    previous, _, _ = collector.collect()
    last = time.monotonic()
    with terminal(interactive):
        while True:
            deadline = last + args.interval
            while time.monotonic() < deadline:
                wait = max(0, deadline - time.monotonic())
                if interactive:
                    if select.select([sys.stdin], [], [], wait)[0]:
                        key = sys.stdin.read(1)
                        if key == "q":
                            return 0
                        if key in ("c", "m"):
                            sort = "cpu_cores" if key == "c" else "memory_bytes"
                        if key == "e":
                            expanded = not expanded
                        if key == "j":
                            scroll += 4
                        if key == "k":
                            scroll = max(0, scroll - 4)
                else:
                    time.sleep(wait)
            try:
                current, host, warnings = collector.collect()
            except CollectionError as exc:
                if not args.watch:
                    raise
                print(str(exc), file=sys.stderr)
                current, host, warnings = [], collector.host or {}, [str(exc)]
            now = time.monotonic()
            data = report(with_rates(current, previous), host, warnings, now - last)
            data["mode"] = identity["mode"]
            if args.json:
                print(json.dumps(data, allow_nan=False), flush=True)
            else:
                width, height = shutil.get_terminal_size()
                text = render(data, sort=sort, expanded=expanded, width=width)
                if interactive:
                    lines = [
                        part
                        for line in text.splitlines()
                        for part in (
                            textwrap.wrap(
                                line, max(1, width - 1), replace_whitespace=False
                            )
                            or [""]
                        )
                    ]
                    page = max(1, height - 2)
                    scroll = min(scroll, max(0, len(lines) - page))
                    text = "\n".join(lines[scroll : scroll + page])
                    text += "\n[q] quit [c/m] sort [e] workers [j/k] scroll"
                    sys.stdout.write("\033[H\033[2J")
                print(colorize(text, color_mode(sys.stdout)), flush=True)
            if not args.watch:
                return 0
            previous, last = current, now


def entrypoint():
    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        return main()
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        return 0
    except CollectionError as exc:
        print(f"cb resources: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(entrypoint())
