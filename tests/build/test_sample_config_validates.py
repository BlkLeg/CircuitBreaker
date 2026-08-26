"""SRV-05: the configuration we ship must pass the validator we ship.

`packaging/config.toml.default` is the file an operator finds at
`/etc/circuit-breaker/config.toml` after a native install, and
`cb config validate` is the command the docs tell them to run when something is
wrong. Nothing checked that the first satisfies the second. SRV-05's acceptance
is "contract tests cover every source and conflict; sample configs validate in
CI", and the ledger recorded the second half as unmet: *"no CI job validates a
sample config — packaging/config.toml.default is never run through the
validator."* This is that job.

The failure it prevents is one an operator hits before they can report it: ship
a default config that the product's own validator rejects, and the first thing
a new install does is contradict itself.

## Why the environment below, and not a bare run

Egress policy has no TOML key. `CB_EGRESS_PROXY_URL` and `CB_ALLOW_DIRECT_EGRESS`
are environment-tier settings — `app/core/config_toml.py` maps no egress key at
all — so `config.toml.default` *cannot* satisfy the production egress gate on its
own, and asserting that it does would be asserting something false. What a real
install actually produces is the pair: `deploy/setup.sh:229` writes
`CB_ALLOW_DIRECT_EGRESS=${CB_ALLOW_DIRECT_EGRESS:-true}` into
`/etc/circuitbreaker/.env` alongside the config file. This test reproduces that
pair, so it validates the configuration a host really runs rather than half of it.

If that installer default ever changes, this test fails and should be updated to
match the installer — not the other way round.

## Why the environment is scrubbed

`env -i`-style isolation, and a throwaway `CB_DATA_DIR`. Without it the run picks
up the developer's own `apps/backend/data/.env` — which supplies a real
`CB_VAULT_KEY` — and the test would pass on a maintainer's laptop for a reason
that does not exist on a clean runner or in CI. The two warnings the run emits
(no `CB_JWT_SECRET`, no `CB_VAULT_KEY`) are correct for a pre-OOBE host and are
warnings, not errors, by design: OOBE generates both.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CONFIG = ROOT / "packaging" / "config.toml.default"
INSTALLER = ROOT / "deploy" / "setup.sh"


def _validate(
    config_path: Path, *, allow_direct_egress: bool = True
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": data_dir,
            "PYTHONPATH": str(ROOT / "apps" / "backend" / "src"),
            "CB_DATA_DIR": data_dir,
        }
        if allow_direct_egress:
            # The installer default; see the module docstring.
            env["CB_ALLOW_DIRECT_EGRESS"] = "true"
        return subprocess.run(
            [sys.executable, "-m", "app.cli", "config", "validate", "--config", str(config_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )


def test_shipped_sample_config_validates():
    """The packaged default config passes `cb config validate`."""
    assert SAMPLE_CONFIG.exists(), f"missing shipped sample config: {SAMPLE_CONFIG}"

    result = _validate(SAMPLE_CONFIG)

    assert result.returncode == 0, (
        f"packaging/config.toml.default does not pass `cb config validate` "
        f"(exit {result.returncode}). An operator's first install would ship a config "
        f"the product rejects.\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "configuration valid" in result.stdout, (
        f"validator exited 0 without reporting success; the contract is the printed "
        f"verdict, not just the exit code.\n\n--- stdout ---\n{result.stdout}"
    )


def test_installer_still_supplies_the_egress_default_this_test_assumes():
    """Pin the assumption the test above is built on.

    The sample config is only valid in combination with the installer's
    environment. If `deploy/setup.sh` stops defaulting `CB_ALLOW_DIRECT_EGRESS`
    to true, the pair stops being valid on a real host while the test above
    keeps passing against an environment nothing produces any more. Asserting
    the installer line here is what keeps the two honest together.
    """
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "CB_ALLOW_DIRECT_EGRESS=${CB_ALLOW_DIRECT_EGRESS:-true}" in installer, (
        "deploy/setup.sh no longer defaults CB_ALLOW_DIRECT_EGRESS to true. "
        "test_shipped_sample_config_validates reproduces that default to validate the "
        "configuration a real host runs; update both together, or the sample config is "
        "being validated against an environment no install produces."
    )


def test_validator_actually_rejects_an_invalid_combination():
    """A gate that cannot fail proves nothing.

    Without this, a validator that returned 0 unconditionally — or a `--config`
    path silently ignored — would make the test above green for the wrong reason.

    The failure used here is the same config with the installer's egress default
    withheld, which is the exact pair the module docstring describes: production
    requires either `CB_EGRESS_PROXY_URL` or an explicit `CB_ALLOW_DIRECT_EGRESS`,
    and `packaging/config.toml.default` supplies neither, because egress has no
    TOML key. So this asserts two things at once — the gate can fail, and the
    installer's environment is load-bearing rather than incidental.

    Note the boundary this does *not* claim. `cb config validate` runs
    `app.core.startup_validation`, which checks required settings and invalid
    combinations; it does not type-check individual values. A `config.toml`
    with `port = "not-a-port"` is reported valid, because `server.port` is only
    copied into `CB_PORT` and never parsed. That is a real limit of the command
    and is recorded in the SRV-05 ledger row rather than papered over with an
    assertion this test would have to lie about.
    """
    result = _validate(SAMPLE_CONFIG, allow_direct_egress=False)

    assert result.returncode != 0, (
        "`cb config validate` accepted the sample config with no egress policy at all. "
        "The sample-config test above is therefore not discriminating, whatever it "
        f"reports.\n\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "CB_EGRESS_PROXY_URL" in result.stderr, (
        "the validator failed for some reason other than the missing egress policy; "
        f"this test is no longer pinning what it claims.\n\n--- stderr ---\n{result.stderr}"
    )
