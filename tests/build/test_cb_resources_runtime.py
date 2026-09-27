"""Opt-in, read-only Docker checks: CB_RESOURCES_LIVE=1 pytest this file.

Uses an already-running container; never creates, stops or modifies a workload.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cb_resources", ROOT / "deploy/cli/cb_resources.py"
)
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)

pytestmark = pytest.mark.skipif(
    os.environ.get("CB_RESOURCES_LIVE") != "1", reason="opt-in Docker runtime check"
)


def test_real_docker_raw_transport_and_sampling():
    daemon = resources.DockerAPI().get("/info")
    assert daemon["NCPU"] > 0
    ids = resources.run(["docker", "ps", "--format", "{{.ID}}"]).decode().splitlines()
    if not ids:
        pytest.skip("No running container; daemon transport verified")
    collector = resources.DockerCollector({"container_name": ids[0]})
    before, _, _ = collector.collect()
    time.sleep(1.1)
    after, host, warnings = collector.collect()
    result = resources.report(resources.with_rates(after, before), host, warnings, 1.1)
    assert result["totals"]["memory_bytes"]["value"] > 0
    assert result["totals"]["cpu_cores"]["value"] is not None
    assert result["measurement_host"]["cpus"] == daemon["NCPU"]
    assert json.loads(json.dumps(result))["schema_version"] == 1
