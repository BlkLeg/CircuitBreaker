"""Resource attribution, counter semantics, CLI isolation and shipping contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import pty
import re
import select
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cb_resources", ROOT / "deploy/cli/cb_resources.py"
)
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)


def identity(**kwargs):
    return {
        "schema_version": 1,
        "mode": "native",
        "version": "test",
        "installed_at": "now",
        "data_dir": "/var/lib/circuitbreaker",
        **kwargs,
    }


def cgroup(root, name, *, cpu=2_000_000, memory=100, read=200, write=400):
    path = root / name.lstrip("/")
    path.mkdir(parents=True, exist_ok=True)
    for file, content in {
        "memory.current": str(memory),
        "memory.swap.current": "9",
        "memory.stat": "file 20\n",
        "pids.current": "3",
        "cpu.stat": f"usage_usec {cpu}\nnr_periods 20\nnr_throttled 4\n",
        "io.stat": f"8:0 rbytes={read} wbytes={write} rios=1 wios=2\n",
        "memory.events": "oom_kill 2\n",
        "memory.max": "1000",
        "memory.high": "900",
        "cpu.max": "50000 100000",
        "cpuset.cpus.effective": "0-3",
        "memory.pressure": "some avg10=0.00 avg60=0.00 avg300=0.00 total=5\n",
    }.items():
        (path / file).write_text(content)
    return path


def systemd_unit(name, group, *, shared=False, **kwargs):
    fragment = name.split("@", 1)[0] + "@.service" if "@" in name else name
    return {
        "Id": name,
        "LoadState": "loaded",
        "ActiveState": "active",
        "FragmentPath": f"/etc/systemd/system/{fragment}",
        "ControlGroup": group,
        "InvocationID": "first-start",
        "Slice": "circuitbreaker.slice",
        "ExecStart": "/usr/sbin/nginx"
        if shared
        else "/opt/circuitbreaker/bin/circuit-breaker",
        "EnvironmentFiles": "/etc/circuitbreaker/.env (ignore_errors=no)",
        **kwargs,
    }


def native(tmp_path, units, ident=None):
    def execute(args):
        assert args[:2] == ["systemctl", "show"]
        assert "system.slice" not in args
        return "\n\n".join(
            "\n".join(f"{k}={v}" for k, v in u.items()) for u in units
        ).encode()

    return resources.NativeCollector(
        ident or identity(), execute=execute, cgroups=resources.Cgroups(tmp_path)
    )


def test_native_counts_workers_postgres_helper_and_excludes_shared_and_unrelated(
    tmp_path,
):
    groups = {
        "circuitbreaker-backend.service": "/circuitbreaker.slice/api",
        "circuitbreaker-worker@telemetry.service": "/circuitbreaker.slice/telemetry",
        "circuitbreaker-postgres.service": "/system.slice/postgres",
        "cb-helperd.service": "/system.slice/helper",
        "nginx.service": "/system.slice/nginx",
    }
    units = []
    for name, group in groups.items():
        cgroup(tmp_path, group)
        unit = systemd_unit(name, group, shared=name == "nginx.service")
        if "postgres" in name:
            unit["ExecStart"] = "/usr/bin/postgres -D /var/lib/circuitbreaker/postgres"
        units.append(unit)
    cgroup(tmp_path, "/system.slice/unrelated", memory=900000000, cpu=900000000)
    collector = native(tmp_path, units)
    before, _, _ = collector.collect()
    after, host, warnings = collector.collect()
    for row in before:
        row["at"] -= 2
        row["counters"]["cpu_ns"]["value"] -= 1_000_000_000
    data = resources.report(resources.with_rates(after, before), host, warnings, 2)
    assert data["totals"]["memory_bytes"]["value"] == 400
    assert data["totals"]["cpu_cores"]["value"] == pytest.approx(2, abs=0.02)
    assert data["totals"]["rx_bytes_per_second"]["value"] is None
    shared = next(r for r in data["components"] if r["id"] == "nginx.service")
    assert not shared["included_in_totals"]
    assert any("shared" in w for w in warnings)
    assert all("unrelated" not in r["id"] for r in data["components"])


def test_nested_and_alias_boundaries_are_never_double_counted(tmp_path):
    parent = systemd_unit("circuitbreaker-backend.service", "/app")
    child = systemd_unit("cb-helperd.service", "/app/child")
    cgroup(tmp_path, "/app", memory=300)
    cgroup(tmp_path, "/app/child", memory=100)
    collector = native(tmp_path, [parent, parent, child])
    rows, host, warnings = collector.collect()
    result = resources.report(resources.with_rates(rows, []), host, warnings, 2)
    assert len(result["components"]) == 2
    assert result["totals"]["memory_bytes"]["value"] == 300


def test_missing_recorded_service_is_a_gap_not_zero(tmp_path):
    cgroup(tmp_path, "/api")
    units = [
        systemd_unit("circuitbreaker-backend.service", "/api"),
        {"Id": "cb-helperd.service", "LoadState": "not-found"},
    ]
    collector = native(tmp_path, units, identity(service_names=["cb-helperd"]))
    rows, host, warnings = collector.collect()
    result = resources.report(resources.with_rates(rows, []), host, warnings, 2)
    assert result["totals"]["memory_bytes"]["value"] == 100
    assert result["totals"]["memory_bytes"]["complete"] is False
    assert any("missing" in w for w in warnings)


def test_unit_name_alone_does_not_establish_ownership(tmp_path):
    unit = systemd_unit(
        "circuitbreaker-backend.service", "/app", ExecStart="/usr/bin/unrelated"
    )
    with pytest.raises(resources.CollectionError, match="verified"):
        native(tmp_path, [unit]).collect()


def test_cgroup_errors_keep_nulls_and_systemd_fallback(tmp_path):
    unit = systemd_unit(
        "circuitbreaker-backend.service",
        "/absent",
        CPUUsageNSec="12345",
        MemoryCurrent=str(2**64 - 1),
    )
    rows, _, _ = native(tmp_path, [unit]).collect()
    assert rows[0]["counters"]["cpu_ns"]["value"] == 12345
    assert rows[0]["metrics"]["memory_bytes"]["value"] is None
    assert resources.Cgroups(tmp_path).path("/../../etc") is None


@pytest.mark.parametrize("change", ["restart", "rollback", "missing", "cached"])
def test_invalid_deltas_are_not_spikes_or_zero(change):
    old = resources.observation("api", "active", "fixture", key="old")
    old["at"] = 10
    old["counters"]["cpu_ns"]["value"] = 1_000_000_000
    new = copy.deepcopy(old)
    new["at"] = 12
    new["counters"]["cpu_ns"]["value"] = 2_000_000_000
    if change == "restart":
        new["key"] = "new"
    elif change == "rollback":
        new["counters"]["cpu_ns"]["value"] = 5
    elif change == "missing":
        old["counters"]["cpu_ns"]["value"] = None
    else:
        new["at"] = 10
    assert (
        resources.with_rates([new], [old])[0]["metrics"]["cpu_cores"]["value"] is None
    )


def test_hierarchical_limits_keep_their_scope(tmp_path):
    cgroup(tmp_path, "/circuitbreaker.slice/api")
    (tmp_path / "circuitbreaker.slice/memory.max").write_text("3221225472")
    cgroup(tmp_path, "/system.slice/postgres")
    cg = resources.Cgroups(tmp_path)
    api = resources.observation("api", "active", "fixture")
    postgres = resources.observation("postgres", "active", "fixture")
    cg.fill(api, "/circuitbreaker.slice/api")
    cg.fill(postgres, "/system.slice/postgres")
    assert any(
        x.get("memory.max") == "3221225472" and x["shared_ancestor"]
        for x in api["limits"]
    )
    assert not any(x.get("memory.max") == "3221225472" for x in postgres["limits"])
    assert api["pressure"]["memory"].startswith("some ")


def test_container_namespace_root_has_its_own_limits(tmp_path):
    cgroup(tmp_path, "/")
    row = resources.observation("mono", "running", "cgroup-v2")
    resources.Cgroups(tmp_path).fill(row, "/")
    assert row["limits"][0]["memory.max"] == "1000"
    assert row["limits"][0]["shared_ancestor"] is False


def test_package_services_use_package_metadata(tmp_path):
    units = []
    for name, command in (
        ("circuit-breaker.service", "/usr/local/bin/circuit-breaker"),
        (
            "circuit-breaker-worker@telemetry.service",
            "/usr/local/bin/circuit-breaker --worker-type telemetry",
        ),
        (
            "circuit-breaker-nats.service",
            "/usr/local/bin/nats-server --store_dir /var/lib/circuit-breaker/nats",
        ),
    ):
        group = "/system.slice/" + name
        cgroup(tmp_path, group, memory=200)
        units.append(
            systemd_unit(
                name,
                group,
                ExecStart=command,
                EnvironmentFiles="/etc/circuit-breaker/circuit-breaker.env (ignore_errors=yes)",
            )
        )
    rows, host, warnings = native(tmp_path, units, identity(mode="package")).collect()
    result = resources.report(resources.with_rates(rows, []), host, warnings, 2)
    assert result["totals"]["memory_bytes"]["value"] == 600


class FakeDocker:
    def __init__(self, network="bridge"):
        self.network = network
        self.started = "first"
        self.running = True
        self.stats = {
            "read": "2026-09-27T00:00:00Z",
            "memory_stats": {"usage": 300, "stats": {"file": 100}},
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "throttling_data": {"periods": 10, "throttled_periods": 2},
            },
            "pids_stats": {"current": 4},
            "blkio_stats": {
                "io_service_bytes_recursive": [{"op": "Read", "value": 123}]
            },
            "networks": {"eth0": {"rx_bytes": 20, "tx_bytes": 40}},
        }

    def get(self, path):
        if path == "/info":
            return {"Name": "remote-daemon", "NCPU": 8, "MemTotal": 1000}
        if path.endswith("/json"):
            return {
                "Id": "abc",
                "State": {
                    "Status": "running" if self.running else "exited",
                    "Running": self.running,
                    "StartedAt": self.started,
                },
                "HostConfig": {"NetworkMode": self.network, "Memory": 500},
            }
        return copy.deepcopy(self.stats)


def test_docker_uses_raw_memory_and_daemon_capacity():
    api = FakeDocker()
    collector = resources.DockerCollector(
        identity(mode="mono", container_name="specific"), api=api
    )
    before, _, _ = collector.collect()
    api.stats["read"] = "2026-09-27T00:00:02Z"
    api.stats["cpu_stats"]["cpu_usage"]["total_usage"] = 3_000_000_000
    after, host, warnings = collector.collect()
    result = resources.report(resources.with_rates(after, before), host, warnings, 2)
    assert result["totals"]["memory_bytes"]["value"] == 300  # includes cache
    assert result["totals"]["cache_bytes"]["value"] == 100
    assert result["totals"]["cpu_cores"]["value"] == 1
    assert result["totals"]["visible_cpu_percent"]["value"] == 12.5
    assert result["totals"]["visible_memory_percent"]["value"] == 30
    assert result["measurement_host"]["name"] == "remote-daemon"


@pytest.mark.parametrize("network", ["host", "container:shared"])
def test_shared_docker_network_is_unavailable(network):
    collector = resources.DockerCollector(
        identity(mode="mono", container_name="specific"), api=FakeDocker(network)
    )
    rows, _, warnings = collector.collect()
    assert rows[0]["counters"]["rx_bytes"]["value"] is None
    assert any("namespace" in w for w in warnings)


def test_stopped_container_is_reported_without_fabricated_zeros():
    api = FakeDocker()
    api.running = False
    rows, _, _ = resources.DockerCollector(
        identity(mode="mono", container_name="specific"), api=api
    ).collect()
    assert rows[0]["state"] == "exited"
    assert rows[0]["metrics"]["memory_bytes"]["value"] is None


def test_docker_transport_decodes_chunked_http_and_uses_cli_context():
    def execute(args, *, input):
        assert args == ["docker", "system", "dial-stdio"]
        assert b"GET /info HTTP/1.1" in input
        assert b"Connection: close" in input
        return b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n7\r\n{"x":1}\r\n0\r\n\r\n'

    assert resources.DockerAPI(execute).get("/info") == {"x": 1}


def test_runtime_errors_do_not_echo_credentials():
    with pytest.raises(resources.CollectionError) as error:
        resources.run(
            ["sh", "-c", "echo 'https://user:secret@example.com' >&2; exit 1"]
        )
    assert "secret" not in str(error.value)


def test_http_transport_keeps_input_open_while_daemon_works():
    script = """
import os, select, sys
request = b''
while not request.endswith(b'\\r\\n\\r\\n'):
    request += os.read(0, 1)
# Seeing EOF here models the daemon's request cancellation on a half-close.
closed = bool(select.select([0], [], [], 0.02)[0])
sys.stdout.write('cancelled' if closed else 'complete')
sys.stdout.flush()
"""
    assert (
        resources.run(
            [sys.executable, "-c", script], input=b"GET /info HTTP/1.1\r\n\r\n"
        )
        == b"complete"
    )


def test_native_proxy_payload_is_included_or_explicitly_partial(tmp_path, monkeypatch):
    unit = systemd_unit(
        "circuitbreaker-docker-proxy.service",
        "/proxy",
        ExecStart="/usr/bin/docker run --env-file /etc/circuitbreaker/docker-proxy.env",
    )
    cgroup(tmp_path, "/proxy", memory=100)
    api = FakeDocker()
    get = api.get

    def proxy_get(path):
        result = get(path)
        if path.endswith("/json"):
            result.update(
                Name="/cb-docker-proxy",
                Config={"Image": "tecnativa/docker-socket-proxy:latest"},
                Mounts=[
                    {
                        "Source": "/var/run/docker.sock",
                        "Destination": "/var/run/docker.sock",
                    }
                ],
            )
        return result

    api.get = proxy_get
    monkeypatch.setattr(resources, "LocalDockerAPI", lambda: api)
    rows, host, warnings = native(tmp_path, [unit]).collect()
    result = resources.report(resources.with_rates(rows, []), host, warnings, 2)
    assert result["totals"]["memory_bytes"]["value"] == 400
    assert result["totals"]["memory_bytes"]["complete"]

    def failed(_path):
        raise resources.CollectionError("permission denied")

    api.get = failed
    rows, host, warnings = native(tmp_path, [unit]).collect()
    result = resources.report(resources.with_rates(rows, []), host, warnings, 2)
    assert result["totals"]["memory_bytes"]["value"] == 100
    assert not result["totals"]["memory_bytes"]["complete"]


def test_human_output_survives_collection_failure():
    data = resources.report([], {}, ["runtime failed"], 2)
    data["mode"] = "native"
    assert "runtime failed" in resources.render(data)
    assert "n/a" in resources.render(data)


def _sample_report(*, rx_measured=True):
    rows = []
    for name, cores, memory in (
        ("circuitbreaker-api.service", 0.4, 600 << 20),
        ("circuitbreaker-postgres.service", 0.1, 800 << 20),
    ):
        row = resources.observation(name, "active", "cgroup")
        row["boundary"] = f"/system.slice/{name}"
        for key, value in (
            ("memory_bytes", memory),
            ("cache_bytes", 0),
            ("swap_bytes", 0),
            ("cpu_cores", cores),
            ("read_bytes_per_second", 1024),
            ("write_bytes_per_second", 2048),
            ("rx_bytes_per_second", 4096 if rx_measured or "api" in name else None),
            ("tx_bytes_per_second", 4096),
        ):
            row["metrics"][key] = resources.metric(
                value, "bytes", "cgroup", "IP accounting disabled"
            )
        row["metrics"]["throttled_period_percent"] = resources.metric(
            None, "percent", "cgroup"
        )
        row["counters"]["oom_kills"] = resources.metric(0, "events", "cgroup")
        rows.append(row)
    host = {"name": "box", "scope": "systemd", "cpus": 4, "memory_bytes": 8 << 30}
    data = resources.report(rows, host, ["docker-proxy not running"], 2)
    data["mode"] = "native"
    return data


def test_human_output_names_a_partial_total_once_after_its_units():
    text = resources.render(_sample_report(rx_measured=False))
    network = next(
        line for line in text.splitlines() if line.strip().startswith("Network")
    )
    # It used to read "4.0 KiB (observed subtotal)/s": the note split the unit.
    assert "(observed subtotal)" not in text
    assert network.rstrip().endswith("(partial: 1 of 2 components measured)")
    assert "4.0 KiB/s" in network
    assert "api" in text and "circuitbreaker-api.service" not in text


def test_human_output_is_grouped_into_sections():
    text = resources.render(_sample_report(), width=100, fancy=False)
    for heading in ("USAGE", "COMPONENTS  (sorted by CPU)", "NOTICES", "NOT MEASURED"):
        assert heading in text.splitlines()
    assert "  - docker-proxy not running" in text
    assert all(line == line.rstrip() for line in text.splitlines())


def test_capacity_bars_fall_back_to_ascii():
    assert "█" not in resources.render(_sample_report(), fancy=False)
    assert "[#" in resources.render(_sample_report(), fancy=False)
    assert "█" in resources.render(_sample_report(), fancy=True)


class _Stream:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize(
    ("env", "tty", "expected"),
    [
        ({}, False, None),
        ({"NO_COLOR": "1", "COLORTERM": "truecolor"}, True, None),
        ({"TERM": "dumb"}, True, None),
        ({"COLORTERM": "truecolor"}, True, "truecolor"),
        ({"TERM": "xterm-256color"}, True, "256"),
    ],
)
def test_colour_only_for_a_terminal_that_wants_it(monkeypatch, env, tty, expected):
    for name in ("NO_COLOR", "COLORTERM", "TERM"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert resources.color_mode(_Stream(tty)) == expected


def test_theme_colours_without_changing_the_text():
    plain = resources.render(_sample_report(rx_measured=False), fancy=True)
    assert "\033[" not in plain
    for mode in ("truecolor", "256"):
        themed = resources.colorize(plain, mode)
        assert "\033[" in themed
        assert re.sub(r"\033\[[\d;]*m", "", themed) == plain
    # The app's primary colour (#fe8019) marks the section headings.
    assert "\033[1;38;2;254;128;25mUSAGE" in resources.colorize(plain, "truecolor")
    assert resources.colorize(plain, None) == plain


def test_zero_docker_memory_limit_means_unlimited():
    assert "unlimited" in resources.limit_summary({"Memory": 0, "NanoCpus": 0})
    assert "0.0 B" not in resources.limit_summary({"Memory": 0})
    assert "0.50 cores" in resources.limit_summary({"cpu.max": "50000 100000"})


@pytest.mark.parametrize(
    "args",
    [["--interval", "nan"], ["--interval", "0"], ["--interval", "inf"], ["--unknown"]],
)
def test_invalid_arguments_exit_two_without_identity(args, tmp_path):
    result = subprocess.run(
        [str(ROOT / "cb"), "resources", *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "CB_IDENTITY_PATH": str(tmp_path / "missing"),
        },
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_explicit_missing_identity_fails_closed_without_sourcing_legacy_config(
    tmp_path,
):
    config = tmp_path / ".circuit-breaker"
    config.mkdir()
    (config / "install-identity.json").write_text(json.dumps(identity()))
    (config / "install.conf").write_text("echo SECRETS_ON_STDOUT; exit 7\n")
    result = subprocess.run(
        [str(ROOT / "cb"), "resources", "--json"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "CB_IDENTITY_PATH": str(tmp_path / "missing"),
        },
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "missing" in result.stderr
    assert "SECRETS" not in result.stderr


def test_helper_ships_in_all_channels():
    assert "deploy/cli/cb_resources.py" in (ROOT / "nfpm.yaml").read_text()
    assert "COPY deploy/cli/cb_resources.py" in (ROOT / "Dockerfile.mono").read_text()
    assert "cb_resources.py" in (ROOT / "install.sh").read_text()
    assert "cb_resources.py" in (ROOT / "deploy/setup.sh").read_text()
    assert '"cli"' in (ROOT / "scripts/build_native_release.py").read_text()
    assert (ROOT / "cb").read_bytes() == (ROOT / "deploy/cli/cb").read_bytes()


def cli_fixture(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    props = systemd_unit(
        "circuitbreaker-backend.service", "", MemoryCurrent="104857600"
    )
    output = "\n".join(f"{k}={v}" for k, v in props.items()) + "\nCPUUsageNSec="
    systemctl.write_text(
        f"#!{sys.executable}\nimport time\n"
        f"print({output!r} + str(time.monotonic_ns()))\n"
    )
    systemctl.chmod(0o755)
    path = tmp_path / "install-identity.json"
    path.write_text(json.dumps(identity()))
    return {
        **os.environ,
        "CB_IDENTITY_PATH": str(path),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }


def test_cli_snapshot_json_without_backend(tmp_path):
    result = subprocess.run(
        [str(ROOT / "cb"), "resources", "--json", "--interval", "1"],
        env=cli_fixture(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["totals"]["memory_bytes"]["value"] == 104857600
    assert data["totals"]["cpu_cores"]["value"] == pytest.approx(1, abs=0.05)
    assert "key" not in data["components"][0]


def test_watch_json_lines_and_sigterm(tmp_path):
    process = subprocess.Popen(
        [str(ROOT / "cb"), "resources", "--watch", "--json", "--interval", "1"],
        env=cli_fixture(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import select

        lines = []
        for _ in range(2):
            assert select.select([process.stdout], [], [], 8)[0], (
                "watch did not emit a sample"
            )
            lines.append(json.loads(process.stdout.readline()))
        assert lines[1]["sampled_at"] > lines[0]["sampled_at"]
        assert lines[1]["totals"]["cpu_cores"]["value"] == pytest.approx(1, abs=0.05)
        process.terminate()
        assert process.wait(timeout=4) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=4)


def test_interactive_watch_restores_terminal_after_quit(tmp_path):
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    process = subprocess.Popen(
        [str(ROOT / "cb"), "resources", "--watch", "--interval", "1"],
        env=cli_fixture(tmp_path),
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    output = b""
    try:
        deadline = time.monotonic() + 8
        while b"[q] quit" not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 1)[0]:
                output += os.read(master, 65536)
        assert b"[q] quit" in output
        os.write(master, b"q")
        assert process.wait(timeout=4) == 0
        while select.select([master], [], [], 0.1)[0]:
            output += os.read(master, 65536)
        assert b"\x1b[?25h\x1b[?1049l" in output
        assert termios.tcgetattr(slave) == before
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=4)
        os.close(master)
        os.close(slave)
