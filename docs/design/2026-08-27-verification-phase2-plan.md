# Verification Phase 2 — T3 First Slice: Boot-and-Exercise on One Fedora VM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that the rpm this repo builds installs on a clean Fedora host, that the service *starts*, and that it reaches `/readyz` — the first check in the project's history that would have caught #87 or #81.

**Architecture:** An ephemeral Fedora VM booted directly with `qemu-system-x86_64` — no libvirt daemon, no root. Each run gets a throwaway `qemu-img` overlay over a read-only golden image, so "clean host" is structural rather than procedural. `fleet/provision.sh` boots it and prints an SSH endpoint; `fleet/dispatch.sh` pushes the candidate artifact and the assertion script, runs it, collects evidence, and always destroys; `tier3-artifact.sh` runs *inside* the VM and knows nothing about how it got there. That last boundary is what lets Phase 3 add matrix rows and Phase 6 add a PVE backend without touching the assertions.

**Tech Stack:** bash (`set -euo pipefail`), qemu-system-x86_64 + KVM, cloud-init (`genisoimage` seed ISO), OpenSSH, Fedora Cloud qcow2, nfpm-built rpm, GNU make, pytest (repo-policy tests in `tests/build/`).

**Spec:** `docs/design/2026-08-27-verification-strategy-design.md` §7 (Tier 3 — the fleet), §5 (one definition per gate), §8 (support tiers). ADR: `docs/adr/0005-verification-tiers-and-platform-support.md`.

## Global Constraints

- **T3 budget: 20 minutes wall clock** (§4 tier table). Includes provision, install, boot, exercise, collect and destroy.
- **P1 — one definition per gate.** `tier3-artifact.sh` is identical across every matrix row. Anything that differs per distro belongs in the row's provisioning, never in the assertions. A gate body may not live in workflow YAML.
- **P2 / R4 — fail closed.** A missing tool is a failed gate (exit 127) via `cb::require_tool`. An informational step that did not run prints `SKIPPED (<reason>)` via `cb::skipped`. **No `|| true` on a gate line.**
- **P7 — evidence or it did not happen.** Collection runs *before* destroy, and the tier fails if the evidence directory is empty. This is the direct response to the composed-E2E diagnostics artifact that contained a `docker ps` header and nothing else.
- **Destroy always.** Even on failure, even on interrupt — but always *after* collection. A leaked VM or a leaked overlay file is a bug in this tier.
- **Evidence layout is flat:** `artifacts/diagnostics/tier3-<row>/`. Not `artifacts/tier3/<row>/`. §4 records why per-tier nesting was corrected before implementation.
- **No root, no daemon.** `/dev/kvm` on this host is mode 0666 and opens without group membership (verified 2026-08-27). Nothing in this phase may require `sudo` on the *host*. Inside the guest, root is fine — it is a throwaway VM.
- **Nothing cached inside the repo.** The golden image lives in `${XDG_CACHE_HOME:-$HOME/.cache}/circuit-breaker/fleet/`. It is large and re-downloadable; it must never be committed and must never be assumed present.
- Shell scripts live under `scripts/ci/`, are `chmod +x`, and start with `#!/usr/bin/env bash` + `set -euo pipefail`.
- **Out of scope for this phase, deliberately:** upgrade and rollback (Phase 3), any non-Fedora or non-rpm row (Phase 3), any CI wiring or release gating (decided 2026-08-27: script and `make verify-fleet` only), the multi-host agent and Proxmox slice (Phase 6).

## Two facts about the artifact this plan is built on

Both were verified against the tree on 2026-08-27 and both shape the tasks below.

1. **The rpm does not ship the `cb` CLI.** `nfpm.yaml`'s `contents:` installs `/usr/local/bin/circuit-breaker`, the frontend tree, the backend tree, `VERSION`, agent binaries, the config template and the systemd unit. `deploy/cli/cb` is not among them. So "exercise the CLI" in §11's Phase 2 sentence can only mean the binary the package actually ships. Task 4 asserts what is there and records the absence as a finding rather than silently testing something else.

2. **Dependencies are `recommends`, not `depends`.** `nfpm.yaml`'s rpm override recommends `postgresql-server`, `redis` and `nats-server`. Those are weak dependencies: `dnf install` pulls them by default, but nothing runs `initdb`, creates the `circuitbreaker` role, or starts the units. Meanwhile `packaging/postinstall.sh` generates `/etc/circuit-breaker/circuit-breaker.env` pointing at `postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker`. So the database the package *names* does not exist after installing the package. Provisioning that database is a test precondition — autopkgtest's `Depends:` split — and belongs in cloud-init, not in the assertions.

**Expected first finding.** `packaging/postinstall.sh` writes `/etc/circuit-breaker/circuit-breaker.env` (hyphenated) with DB user `circuitbreaker`, while `deploy/setup.sh` writes `/etc/circuitbreaker/.env` (unhyphenated) with DB user `breaker`. Two installers, two config paths, two credentials. This tier tests the *package*, so it follows the package's own generated env. If that turns out not to work, that is a real defect and the tier has done its job — do not "fix" it by pointing the test at setup.sh's paths.

---

### Task 1: The matrix, and the contract that keeps it honest

**Files:**
- Create: `scripts/ci/fleet/matrix.yaml`
- Create: `tests/build/test_fleet_matrix.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `matrix.yaml` with one row. Every consumer reads the fields `id`, `distro`, `format`, `arch`, `runner`, `tier`, `image_url`, `image_sha256`. `id` is the row's identity and appears in evidence paths as `artifacts/diagnostics/tier3-<id>/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_fleet_matrix.py
"""matrix.yaml is the single source of truth for what this project claims works.

Design §7.2: the matrix "feeds both the tier and the support-tier table in §8".
A row that names a tier the support table does not define, or an image without a
checksum, is a claim nobody can check. The image checksum matters most: the
golden image is fetched over the network into a cache outside the repo, and an
unverified image means the tier's "clean Fedora host" is whatever the mirror
served that day.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX = REPO_ROOT / "scripts" / "ci" / "fleet" / "matrix.yaml"

_REQUIRED = {"id", "distro", "format", "arch", "runner", "tier", "image_url", "image_sha256"}


def _rows() -> list[dict[str, str]]:
    """Parse the matrix without taking a PyYAML dependency on the build suite.

    The format is deliberately a flat list of `key: value` blocks separated by
    `- ` markers; if it ever needs nesting, add PyYAML to the dev extra and
    rewrite this. Keeping it parseable by twenty lines of stdlib is worth more
    than the generality right now.
    """
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in MATRIX.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            current = {}
            rows.append(current)
            line = line.lstrip()[2:]
            if not line.strip():
                continue
        if current is None:
            continue
        key, _, value = line.strip().partition(":")
        current[key.strip()] = value.strip().strip('"')
    return rows


def test_matrix_exists():
    assert MATRIX.is_file(), f"{MATRIX} is missing"


def test_every_row_declares_every_required_field():
    for row in _rows():
        missing = _REQUIRED - set(row)
        assert not missing, f"row {row.get('id', '?')} is missing {sorted(missing)}"


def test_every_image_is_pinned_by_checksum():
    """An unpinned image makes 'clean Fedora host' mean 'whatever the mirror
    served today', which is not a controlled input."""
    for row in _rows():
        digest = row["image_sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"row {row['id']}: image_sha256 must be a 64-character hex sha256, got {digest!r}"
        )


def test_row_ids_are_unique_and_path_safe():
    """The id becomes a directory name under artifacts/diagnostics/."""
    ids = [row["id"] for row in _rows()]
    assert len(ids) == len(set(ids)), f"duplicate row ids: {ids}"
    for row_id in ids:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]*", row_id), (
            f"row id {row_id!r} is not safe as a path component"
        )


def test_phase_2_ships_exactly_the_fedora_rpm_row():
    """Phase 2 is one row by design (§11). Phase 3 is what adds breadth; a row
    added here without its provisioning is a claim the tier cannot support."""
    rows = _rows()
    assert len(rows) == 1, f"Phase 2 defines one row, found {len(rows)}"
    row = rows[0]
    assert row["distro"].startswith("fedora")
    assert row["format"] == "rpm"
    assert row["arch"] == "amd64"
    assert row["runner"] == "local/qemu"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_fleet_matrix.py -v`
Expected: FAIL — `test_matrix_exists` asserts on a missing file; the rest error on the same missing path.

- [ ] **Step 3: Pin the golden image**

Fedora publishes a `CHECKSUM` file next to each cloud image, signed and served from the same tree. Resolve the current release's image and digest rather than transcribing one by hand:

```bash
FEDORA_RELEASE=42   # bump deliberately, never automatically: a new release is a new claim
BASE="https://download.fedoraproject.org/pub/fedora/linux/releases/${FEDORA_RELEASE}/Cloud/x86_64/images"
curl -fsSL "${BASE}/" | grep -oE 'Fedora-Cloud-Base-Generic[^"]*\.qcow2' | sort -u
```

Take the exact filename that command prints, then read its digest out of the published checksum file:

```bash
IMAGE="<the filename printed above>"
curl -fsSL "${BASE}/Fedora-Cloud-${FEDORA_RELEASE}-x86_64-CHECKSUM" \
  | grep -F "SHA256 (${IMAGE}) =" 
```

If the mirror redirect fails or the release directory has moved, fall back to `https://mirrors.kernel.org/fedora/releases/${FEDORA_RELEASE}/Cloud/x86_64/images/`. Do **not** proceed with an unpinned image — `test_every_image_is_pinned_by_checksum` exists to stop exactly that.

- [ ] **Step 4: Write the matrix**

Substitute the URL and digest resolved in Step 3.

```yaml
# scripts/ci/fleet/matrix.yaml
#
# The single source of truth for what this project claims works (design §7.2).
# It feeds both this tier and the support-tier table in §8, so a row here is a
# published promise, not a convenience.
#
# `runner` is the ONLY field that varies by execution site. tier3-artifact.sh is
# identical across every row (P1); anything distro-specific belongs in that row's
# provisioning. Phase 2 ships one row. Phase 3 adds the rest of §7.2's matrix.
#
# `tier` is the §8 support tier this row backs:
#   1 = guaranteed to install, boot, upgrade and roll back
#   2 = guaranteed to install and boot
#   3 = guaranteed to build; installation best-effort
# This row is the evidence behind the Tier 1 claim for rpm/amd64 — except upgrade
# and rollback, which Phase 3 adds. Until then the row backs the *boot* half only,
# and §8's table must not be updated to claim otherwise.

- id: fedora-rpm-amd64
  distro: fedora-42
  format: rpm
  arch: amd64
  runner: local/qemu
  tier: 1
  image_url: "PASTE_THE_URL_RESOLVED_IN_STEP_3"
  image_sha256: "PASTE_THE_DIGEST_RESOLVED_IN_STEP_3"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_fleet_matrix.py -v`
Expected: PASS, 5 tests. If `test_every_image_is_pinned_by_checksum` fails, the digest was not substituted — go back to Step 3 rather than relaxing the test.

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/fleet/matrix.yaml tests/build/test_fleet_matrix.py
git commit -m "feat(fleet): the T3 matrix, with its image pinned by checksum

ADR 0005 Phase 2. matrix.yaml is the single source of truth for what the project
claims works, and it feeds the support-tier table in the design's section 8 as
well as this tier. The image digest is required by test rather than by
convention: the golden image is fetched from a mirror into a cache outside the
repo, and an unverified image makes 'a clean Fedora host' mean 'whatever the
mirror served that day'."
```

---

### Task 2: Provision an ephemeral VM with no daemon and no root

**Files:**
- Create: `scripts/ci/fleet/provision.sh`
- Create: `scripts/ci/fleet/cloud-init/fedora.user-data`
- Test: `tests/build/test_fleet_provision_contract.py`

**Interfaces:**
- Consumes: `cb::require_tool`, `cb::section`, `cb::skipped`, `$CB_REPO_ROOT` from `scripts/ci/lib/common.sh` (Phase 1, Task 1). `matrix.yaml` from Task 1.
- Produces: `scripts/ci/fleet/provision.sh`, which on success prints exactly one line to stdout — `<ssh_port> <ssh_key_path> <vm_dir>` — and leaves a booted, SSH-reachable VM. `fleet::destroy <vm_dir>` tears one down and is idempotent. All diagnostics go to stderr so stdout stays parseable.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_fleet_provision_contract.py
"""Provisioning must be unprivileged, ephemeral, and honest about its tools.

Three properties, each of which has a way of quietly not holding:

* **Unprivileged.** The whole point of choosing raw QEMU over libvirt was that
  /dev/kvm is world-writable here, so no contributor needs a daemon, a group, or
  a password to run the release gate. A `sudo` creeping into this script takes
  that away silently -- it will still work on the machine that added it.
* **Ephemeral.** The guarantee that every run starts from a clean host is
  `qemu-img create -b`: a copy-on-write overlay over a read-only golden image.
  Booting the golden image directly would work exactly once and then quietly
  test a dirty host forever after.
* **Honest.** A gate that cannot find qemu must fail, not skip.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = REPO_ROOT / "scripts" / "ci" / "fleet"
PROVISION = FLEET / "provision.sh"
USER_DATA = FLEET / "cloud-init" / "fedora.user-data"


def test_provision_script_exists_and_is_executable():
    assert PROVISION.is_file(), f"{PROVISION} is missing"
    assert PROVISION.stat().st_mode & 0o111, f"{PROVISION} is not executable"


def test_provision_uses_strict_bash():
    text = PROVISION.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


def test_provision_never_escalates_privilege():
    """/dev/kvm is 0666 on the fleet host; needing sudo would mean the gate only
    runs for whoever configured the machine."""
    offenders = [
        f"{lineno}: {line.strip()}"
        for lineno, line in enumerate(
            PROVISION.read_text(encoding="utf-8").splitlines(), start=1
        )
        if re.search(r"(^|\s)(sudo|pkexec|doas)\s", line) and not line.strip().startswith("#")
    ]
    assert not offenders, (
        "provisioning must run unprivileged -- raw QEMU over libvirt was chosen "
        "precisely so it could:\n  " + "\n  ".join(offenders)
    )


def test_provision_boots_a_copy_on_write_overlay():
    """`-b golden.qcow2` is what makes 'clean host' structural. Without it the
    first run mutates the golden image and every later run tests residue."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "qemu-img create" in text, "no overlay is created"
    assert re.search(r"qemu-img create[^\n]*-b ", text), (
        "the overlay must be backed by the golden image (-b), not a fresh disk"
    )


def test_provision_fails_closed_on_missing_tools():
    text = PROVISION.read_text(encoding="utf-8")
    for tool in ("qemu-system-x86_64", "genisoimage", "ssh", "curl"):
        assert f"cb::require_tool {tool}" in text, (
            f"{tool} must be required with cb::require_tool so a missing tool "
            f"exits 127 rather than producing a confusing failure later"
        )


def test_provision_verifies_the_image_checksum():
    """An image fetched over the network and not verified is an uncontrolled
    input to every assertion downstream of it."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "sha256sum" in text or "sha256" in text
    assert "image_sha256" in text, "the digest must come from matrix.yaml, not be hardcoded"


def test_cloud_init_provisions_the_database_the_package_names():
    """packaging/postinstall.sh generates an env pointing at
    postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker, and the
    rpm only *recommends* postgresql-server -- nothing runs initdb or creates
    that role. Provisioning it is a test precondition (autopkgtest's Depends:
    split); asserting the package works against it is the test."""
    text = USER_DATA.read_text(encoding="utf-8")
    assert "initdb" in text or "postgresql-setup" in text
    assert "circuitbreaker" in text, "the role the package's own env names"
    for unit in ("postgresql", "redis", "nats"):
        assert unit in text, f"cloud-init must provision {unit}"


def test_cloud_init_does_not_install_the_candidate():
    """The artifact under test is pushed by dispatch.sh and installed by
    tier3-artifact.sh. A VM that arrives with it already installed is not
    testing an install."""
    text = USER_DATA.read_text(encoding="utf-8")
    assert ".rpm" not in text, "cloud-init must not install the candidate package"
    assert "circuit-breaker.service" not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_fleet_provision_contract.py -v`
Expected: FAIL — `test_provision_script_exists_and_is_executable` on the missing file, and the rest error reading it.

- [ ] **Step 3: Write the cloud-init user-data**

```yaml
# scripts/ci/fleet/cloud-init/fedora.user-data
#cloud-config
#
# The test FIXTURE, not the test. Everything here is a precondition the package
# declares but does not create -- autopkgtest's Depends: split. The candidate
# artifact is deliberately absent: dispatch.sh pushes it and tier3-artifact.sh
# installs it, because a VM that boots with the package already on it is not
# testing an install.
#
# Why these three services: nfpm.yaml's rpm override lists postgresql-server,
# redis and nats-server under `recommends`, which are weak dependencies -- dnf
# pulls them in but nothing runs initdb, creates a role, or starts a unit. And
# packaging/postinstall.sh writes an env file naming
# postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker. So the
# database the package names does not exist until something makes it. That is
# this file's job, and the credentials below are the package's own, on purpose:
# if they are wrong, the tier must fail rather than paper over it with different
# ones.

ssh_authorized_keys:
  - CB_SSH_PUBKEY_PLACEHOLDER

package_update: false
packages:
  - postgresql-server
  - postgresql
  - redis
  - nats-server

runcmd:
  - [ sh, -c, "postgresql-setup --initdb || /usr/bin/initdb -D /var/lib/pgsql/data" ]
  # Trust local connections: this VM is destroyed at the end of the run and is
  # never reachable off the host (user-mode networking, no bridge). The password
  # below still has to match the package's generated env, because that env is
  # what the service will actually use.
  - [ sh, -c, "sed -i 's/^host\\(.*\\)ident$/host\\1md5/' /var/lib/pgsql/data/pg_hba.conf || true" ]
  - [ systemctl, enable, --now, postgresql ]
  - [ systemctl, enable, --now, redis ]
  - [ systemctl, enable, --now, nats ]
  - [ sh, -c, "su - postgres -c \"psql -c \\\"CREATE ROLE circuitbreaker LOGIN PASSWORD 'changeme'\\\"\"" ]
  - [ sh, -c, "su - postgres -c \"createdb -O circuitbreaker circuitbreaker\"" ]
  # The marker dispatch.sh waits on. Written last, so its presence means every
  # precondition above completed. Without it, dispatch races cloud-init and the
  # first failure looks like a broken package rather than an unfinished fixture.
  - [ sh, -c, "touch /var/lib/cloud/cb-fixture-ready" ]

final_message: "cb fleet fixture ready after $UPTIME seconds"
```

- [ ] **Step 4: Write provision.sh**

```bash
#!/usr/bin/env bash
# Boot one ephemeral Fedora VM for a Tier 3 row, unprivileged.
#
# Raw qemu rather than libvirt, deliberately: /dev/kvm is 0666 on this host and
# opens without group membership, so the release gate needs no daemon, no group
# and no password. libvirt would have needed virt-install (absent), libvirtd
# (inactive) and a group the developer is not in -- three root operations to run
# a test.
#
# Ephemerality is a copy-on-write overlay over a read-only golden image, not a
# cleanup routine. Cleanup routines are skipped when a run is killed; a fresh
# overlay per run cannot be.
#
# Prints ONE line to stdout on success: "<ssh_port> <ssh_key> <vm_dir>".
# Everything else goes to stderr so callers can parse stdout without filtering.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

FLEET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MATRIX="$FLEET_DIR/matrix.yaml"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/circuit-breaker/fleet"

cb::require_tool qemu-system-x86_64 "install qemu-system-x86 (Fedora: sudo dnf install qemu-system-x86)"
cb::require_tool qemu-img "install qemu-img (Fedora: sudo dnf install qemu-img)"
cb::require_tool genisoimage "install genisoimage (Fedora: sudo dnf install genisoimage)"
cb::require_tool ssh
cb::require_tool ssh-keygen
cb::require_tool curl
cb::require_tool sha256sum

if [ ! -w /dev/kvm ]; then
    printf '::error::/dev/kvm is not writable by this user — KVM acceleration is required.\n' >&2
    printf 'On this fleet host /dev/kvm is mode 0666. If it is not on yours, add yourself to the kvm group.\n' >&2
    exit 127
fi

# ── matrix lookup ───────────────────────────────────────────────────────────
# One row in Phase 2, but read by id so Phase 3's rows do not require rewriting
# every caller.
fleet::matrix_field() {
    local row_id=$1 field=$2
    awk -v id="$row_id" -v key="$field" '
        /^[[:space:]]*-[[:space:]]+id:/ { in_row = ($0 ~ id) }
        in_row && $0 ~ "^[[:space:]]*" key ":" {
            sub("^[[:space:]]*" key ":[[:space:]]*", "")
            gsub(/^"|"$/, "")
            print; exit
        }
    ' "$MATRIX"
}

ROW_ID="${1:-fedora-rpm-amd64}"
IMAGE_URL="$(fleet::matrix_field "$ROW_ID" image_url)"
IMAGE_SHA="$(fleet::matrix_field "$ROW_ID" image_sha256)"
if [ -z "$IMAGE_URL" ] || [ -z "$IMAGE_SHA" ]; then
    printf '::error::row %s has no image_url/image_sha256 in %s\n' "$ROW_ID" "$MATRIX" >&2
    exit 1
fi

# ── golden image, fetched once and verified every time ──────────────────────
# Verified on every run, not only on download: a truncated fetch, a full disk or
# a tampered cache would otherwise silently become "the clean Fedora host".
mkdir -p "$CACHE_DIR"
GOLDEN="$CACHE_DIR/$(basename "$IMAGE_URL")"
if [ ! -f "$GOLDEN" ]; then
    cb::section "Fetching golden image for $ROW_ID (once; cached in $CACHE_DIR)" >&2
    curl -fSL --retry 3 -o "$GOLDEN.part" "$IMAGE_URL" >&2
    mv "$GOLDEN.part" "$GOLDEN"
fi
if ! printf '%s  %s\n' "$IMAGE_SHA" "$GOLDEN" | sha256sum --check --status; then
    printf '::error::golden image checksum mismatch for %s\n' "$GOLDEN" >&2
    printf 'expected %s — delete the file and re-run to refetch\n' "$IMAGE_SHA" >&2
    exit 1
fi

# ── per-run scratch ─────────────────────────────────────────────────────────
VM_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cb-fleet-${ROW_ID}-XXXXXX")"
OVERLAY="$VM_DIR/disk.qcow2"
SEED="$VM_DIR/seed.iso"
KEY="$VM_DIR/id_ed25519"

# The overlay IS the clean-host guarantee. -b makes writes land here and leaves
# the golden image untouched, so run N+1 cannot inherit run N's residue.
qemu-img create -f qcow2 -F qcow2 -b "$GOLDEN" "$OVERLAY" 20G >&2

# A key per run, thrown away with the VM. Nothing long-lived is trusted by a
# machine this disposable.
ssh-keygen -t ed25519 -N '' -f "$KEY" -q

USER_DATA="$VM_DIR/user-data"
sed "s|CB_SSH_PUBKEY_PLACEHOLDER|$(cat "$KEY.pub")|" \
    "$FLEET_DIR/cloud-init/fedora.user-data" > "$USER_DATA"
printf 'instance-id: cb-%s\nlocal-hostname: cb-fleet\n' "$ROW_ID" > "$VM_DIR/meta-data"
genisoimage -output "$SEED" -volid cidata -joliet -rock \
    "$USER_DATA" "$VM_DIR/meta-data" >/dev/null 2>&1

# ── boot ────────────────────────────────────────────────────────────────────
# User-mode networking with a forwarded port: no bridge, no tap device, no root.
# The guest is unreachable from the LAN, which is the correct blast radius for a
# machine running an unreviewed candidate package as root.
SSH_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

cb::section "Booting $ROW_ID (ssh on 127.0.0.1:$SSH_PORT)" >&2
qemu-system-x86_64 \
    -name "cb-fleet-$ROW_ID" \
    -machine q35,accel=kvm \
    -cpu host \
    -smp 2 \
    -m 4096 \
    -nographic -serial "file:$VM_DIR/console.log" -monitor none \
    -drive "file=$OVERLAY,if=virtio,format=qcow2" \
    -drive "file=$SEED,if=virtio,format=raw,readonly=on" \
    -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22" \
    -device virtio-net-pci,netdev=net0 \
    -pidfile "$VM_DIR/qemu.pid" \
    -daemonize >&2

# ── wait for SSH, then for the fixture ──────────────────────────────────────
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR -o ConnectTimeout=5 -i "$KEY" -p "$SSH_PORT")

deadline=$(( SECONDS + 300 ))
until ssh "${SSH_OPTS[@]}" fedora@127.0.0.1 true 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '::error::VM did not accept SSH within 300s — console log follows\n' >&2
        tail -50 "$VM_DIR/console.log" >&2 || true
        exit 1
    fi
    sleep 3
done

# Two waits, not one. SSH comes up well before cloud-init has finished running
# runcmd, and dispatching into a half-provisioned host produces failures that
# look like package bugs.
deadline=$(( SECONDS + 600 ))
until ssh "${SSH_OPTS[@]}" fedora@127.0.0.1 \
        'test -f /var/lib/cloud/cb-fixture-ready' 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '::error::cloud-init fixture did not complete within 600s\n' >&2
        ssh "${SSH_OPTS[@]}" fedora@127.0.0.1 \
            'sudo tail -80 /var/log/cloud-init-output.log' >&2 || true
        exit 1
    fi
    sleep 5
done

printf '%s %s %s\n' "$SSH_PORT" "$KEY" "$VM_DIR"
```

Then `chmod +x scripts/ci/fleet/provision.sh`.

- [ ] **Step 5: Run the contract test**

Run: `.venv/bin/pytest tests/build/test_fleet_provision_contract.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Prove it actually boots**

This is the step that separates a script that satisfies its own tests from one that works. Expect the first run to take several minutes — it downloads roughly 500 MB.

```bash
read -r PORT KEY VMDIR < <(scripts/ci/fleet/provision.sh fedora-rpm-amd64)
echo "port=$PORT key=$KEY dir=$VMDIR"
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$KEY" -p "$PORT" \
    fedora@127.0.0.1 'cat /etc/fedora-release; systemctl is-active postgresql redis nats'
```

Expected: the Fedora release string, then `active` three times. Then tear it down by hand for now:

```bash
kill "$(cat "$VMDIR/qemu.pid")" && rm -rf "$VMDIR"
```

If postgresql is not active, read `$VMDIR/console.log` and `/var/log/cloud-init-output.log` in the guest before changing anything — on Fedora the unit may be `postgresql.service` only after `postgresql-setup --initdb` has succeeded, and the failure mode is quiet.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/fleet/provision.sh scripts/ci/fleet/cloud-init/fedora.user-data \
        tests/build/test_fleet_provision_contract.py
git commit -m "feat(fleet): boot an ephemeral Fedora VM unprivileged, with no daemon

ADR 0005 Phase 2. Raw qemu rather than libvirt because /dev/kvm is 0666 here and
opens without group membership: the release gate needs no daemon, no group and
no password, where libvirt would have needed virt-install, libvirtd and a group
membership -- three root operations to run a test.

Clean-host is a copy-on-write overlay over a checksum-verified golden image
rather than a cleanup routine, because cleanup routines are skipped when a run is
killed and a fresh overlay cannot be. cloud-init provisions the database the
package's own postinstall names but does not create -- the rpm only *recommends*
postgresql-server, so nothing runs initdb -- and deliberately does not install
the candidate, which is what the tier is there to do."
```

---

### Task 3: The assertions, running inside the VM

**Files:**
- Create: `scripts/ci/tier3-artifact.sh`
- Modify: `tests/build/test_ci_script_contract.py` (extend `TIER_SCRIPTS`)

**Interfaces:**
- Consumes: nothing from `lib/common.sh` — this script runs *inside the guest*, where the repo does not exist. It is self-contained by necessity, and that constraint is what keeps it identical across rows (P1).
- Produces: `scripts/ci/tier3-artifact.sh`, invoked in the guest as `tier3-artifact.sh <package-path>`. Exit 0 on success. Writes evidence into `/tmp/cb-tier3-evidence/` for `dispatch.sh` to collect.

- [ ] **Step 1: Extend the tier contract test**

In `tests/build/test_ci_script_contract.py`, change:

```python
TIER_SCRIPTS = ["tier0-static.sh", "tier1-unit.sh"]
```

to:

```python
TIER_SCRIPTS = ["tier0-static.sh", "tier1-unit.sh", "tier3-artifact.sh"]
```

Then append this test to the same file:

```python
def test_tier3_is_self_contained_because_it_runs_in_a_guest():
    """tier0 and tier1 source lib/common.sh; tier3 cannot.

    It executes inside an ephemeral VM where this repository does not exist --
    only the script and the candidate package are copied in. Sourcing the shared
    library would fail at runtime, in the guest, several minutes into a slow
    tier. That constraint is also what keeps it identical across every matrix row
    (P1): a script with no repo to reach into cannot grow distro-specific
    branches by accident.
    """
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "lib/common.sh" not in text, (
        "tier3-artifact.sh runs in a guest without the repo; it must not source "
        "the shared library"
    )
    assert "cb::" not in text, "the cb:: helpers are not available in the guest"


def test_tier3_waits_for_readyz_not_just_livez():
    """The whole point of this tier (design section 11) is that the service
    *starts*. /livez only proves the process is alive; a package that installs,
    launches and can never reach its database passes a liveness check and fails
    every user."""
    text = (CI_DIR / "tier3-artifact.sh").read_text(encoding="utf-8")
    assert "/livez" in text
    assert "/readyz" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: FAIL — `test_tier_scripts_exist_and_are_executable` reports `tier3-artifact.sh is missing`, and both new tests error reading it.

- [ ] **Step 3: Write the script**

```bash
#!/usr/bin/env bash
# Tier 3 — install, boot and exercise a candidate package on a clean host.
#
# Runs INSIDE an ephemeral VM, as root, over SSH. Deliberately self-contained:
# the repository does not exist here, only this file and the candidate. That is
# also what keeps it identical across every matrix row (P1) -- a script with no
# repo to reach into cannot quietly grow distro-specific branches.
#
# The contract is autopkgtest's: test the installed package AS INSTALLED. Nothing
# below may reach into a source tree, and nothing may reconfigure the package to
# make an assertion pass. If the package's own generated config does not work,
# that is the finding.
set -euo pipefail

PACKAGE="${1:?usage: tier3-artifact.sh <path-to-candidate-package>}"
EVIDENCE=/tmp/cb-tier3-evidence
BASE_URL="http://127.0.0.1:8000/api/v1"
mkdir -p "$EVIDENCE"

section() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
fail()    { printf '::error::%s\n' "$1" >&2; exit 1; }

# ── install ─────────────────────────────────────────────────────────────────
section "Install $(basename "$PACKAGE")"
# `dnf install` on a local file resolves the package's own dependencies, which is
# what a user gets. The rpm lists postgresql-server/redis/nats-server under
# `recommends` (weak), so this pulls them but does not configure them -- the VM
# fixture already did that, because nothing in the package ever will.
dnf install -y "$PACKAGE" 2>&1 | tee "$EVIDENCE/install.log"

section "Assert the package installed what it claims"
for path in \
    /usr/local/bin/circuit-breaker \
    /usr/local/share/circuit-breaker/VERSION \
    /usr/local/share/circuit-breaker/frontend \
    /usr/local/share/circuit-breaker/backend \
    /lib/systemd/system/circuit-breaker.service \
    /etc/circuit-breaker/circuit-breaker.env; do
    [ -e "$path" ] || fail "package did not install $path"
done
# postinstall.sh generates this env with a fresh CB_VAULT_KEY and NATS token, so
# it must not be world-readable. Checked here rather than trusted: it is created
# by a shell script at install time, which is exactly where a mode gets missed.
mode="$(stat -c '%a' /etc/circuit-breaker/circuit-breaker.env)"
[ "$mode" = "600" ] || fail "env file mode is $mode, expected 600"
cp /etc/circuit-breaker/circuit-breaker.env "$EVIDENCE/installed.env.redacted"
sed -i 's/=.*/=<redacted>/' "$EVIDENCE/installed.env.redacted"

section "Assert the installed binary reports the shipped version"
SHIPPED="$(cat /usr/local/share/circuit-breaker/VERSION)"
REPORTED="$(/usr/local/bin/circuit-breaker --version)"
printf 'shipped=%s reported=%s\n' "$SHIPPED" "$REPORTED" | tee "$EVIDENCE/version.txt"
[ "$SHIPPED" = "$REPORTED" ] \
    || fail "binary reports '$REPORTED' but the shipped VERSION says '$SHIPPED'"

# The `cb` CLI is NOT shipped by nfpm.yaml -- contents: installs the
# circuit-breaker binary, the frontend and backend trees, VERSION, the agent
# binaries, the config template and the unit, and nothing else. Recorded rather
# than asserted: this tier reports what the package does, and "the operator CLI
# the docs reference is absent from the package" is a finding for the phase
# report, not something to quietly assert into existence.
if [ -x /usr/local/bin/cb ]; then
    /usr/local/bin/cb --help > "$EVIDENCE/cb-help.txt" 2>&1
else
    printf 'SKIPPED (not shipped by nfpm.yaml): the cb operator CLI\n' \
        | tee "$EVIDENCE/cb-cli.txt"
fi

# ── boot ────────────────────────────────────────────────────────────────────
section "Start the service"
systemctl daemon-reload
systemctl start circuit-breaker

# Liveness first: it is the weaker claim, and separating the two makes the
# failure legible. "Alive but never ready" is a database or migration problem;
# "never alive" is a packaging or unit problem. A single combined wait would
# report both as one timeout.
section "Wait for /livez"
deadline=$(( SECONDS + 120 ))
until curl -fsS "$BASE_URL/livez" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        journalctl -u circuit-breaker --no-pager -n 200 > "$EVIDENCE/journal.log" 2>&1 || true
        fail "service never became live within 120s"
    fi
    sleep 2
done
curl -fsS "$BASE_URL/livez" > "$EVIDENCE/livez.json"

section "Wait for /readyz"
# This is the assertion the tier exists for. A package that installs, launches
# and can never reach its database satisfies every check the pipeline had before
# this one.
deadline=$(( SECONDS + 180 ))
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/readyz")" = "200" ]; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        curl -s "$BASE_URL/readyz" > "$EVIDENCE/readyz.json" 2>&1 || true
        journalctl -u circuit-breaker --no-pager -n 200 > "$EVIDENCE/journal.log" 2>&1 || true
        fail "service never became ready within 180s — see readyz.json and journal.log"
    fi
    sleep 3
done
curl -fsS "$BASE_URL/readyz" | tee "$EVIDENCE/readyz.json"

section "Assert readiness means what it says"
python3 - "$EVIDENCE/readyz.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
assert body["ready"] is True, body
assert body["state"] == "ready", body
for dep, verdict in body["checks"].items():
    assert verdict == "ok", f"{dep} reported {verdict}: {body}"
print("readyz:", body["checks"])
PY

# ── exercise ────────────────────────────────────────────────────────────────
section "Assert migrations reached head"
# The schema is what /readyz's contract check probes, so this is partly implied
# above -- but implied is not reported. A named revision in the evidence is what
# makes an upgrade test possible in Phase 3.
sudo -u postgres psql -d circuitbreaker -tAc \
    'SELECT version_num FROM alembic_version' > "$EVIDENCE/alembic_version.txt"
[ -s "$EVIDENCE/alembic_version.txt" ] \
    || fail "alembic_version is empty — migrations did not run against the packaged database"

section "Exercise a real API path"
# Not another health endpoint: those share a code path with the probes above and
# would re-assert the same thing. A route that touches the ORM and serialises a
# model is what proves the packaged backend tree is complete -- issue #104's
# class, where a module is missing only in the packaged build.
code="$(curl -s -o "$EVIDENCE/api-probe.json" -w '%{http_code}' "$BASE_URL/health")"
printf 'GET /health -> %s\n' "$code" | tee -a "$EVIDENCE/api-probe.txt"
[ "$code" = "200" ] || fail "GET /api/v1/health returned $code"

section "Collect evidence"
journalctl -u circuit-breaker --no-pager -n 500 > "$EVIDENCE/journal.log" 2>&1 || true
systemctl show circuit-breaker -p ActiveState -p SubState -p ExecMainStatus \
    > "$EVIDENCE/unit-state.txt" 2>&1 || true
ls -la /var/lib/circuit-breaker > "$EVIDENCE/data-dir.txt" 2>&1 || true
rpm -ql circuit-breaker > "$EVIDENCE/package-contents.txt" 2>&1 || true

section "Tier 3 complete"
```

Then `chmod +x scripts/ci/tier3-artifact.sh`.

- [ ] **Step 4: Run the contract tests**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: PASS. The `test_tier_scripts_do_not_swallow_gate_failures` test from Phase 1 also now covers this script — if it fails, an `|| true` crept onto a gate line. The three `|| true` uses in "Collect evidence" are on diagnostics, not gates; if that test flags them, narrow the test rather than weakening the collection, and record why in the commit.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/tier3-artifact.sh tests/build/test_ci_script_contract.py
git commit -m "feat(ci): tier 3 assertions — install, boot, and actually reach readyz

ADR 0005 Phase 2. The contract is autopkgtest's: test the installed package as
installed, reaching into no source tree and reconfiguring nothing to make an
assertion pass.

/livez and /readyz are waited on separately because the distinction is the
finding: alive-but-never-ready is a database or migration fault, never-alive is a
packaging or unit fault, and one combined timeout reports both as the same thing.
Reaching readyz is the assertion this tier exists for -- a package that installs,
launches, and can never reach its database satisfied every check the pipeline had
before this one.

The script is self-contained because it runs in a guest where the repo does not
exist, and that constraint is what keeps it identical across matrix rows."
```

---

### Task 4: Dispatch — push, run, collect, always destroy

**Files:**
- Create: `scripts/ci/fleet/dispatch.sh`
- Test: `tests/build/test_fleet_dispatch_contract.py`

**Interfaces:**
- Consumes: `provision.sh`'s stdout contract (`<ssh_port> <ssh_key> <vm_dir>`), `tier3-artifact.sh`, `matrix.yaml`, and `cb::` helpers from `lib/common.sh` (this one runs on the host).
- Produces: `scripts/ci/fleet/dispatch.sh <row-id> <package-path>`. Evidence lands in `artifacts/diagnostics/tier3-<row-id>/`. Exit 0 only if the guest script succeeded *and* evidence was collected.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_fleet_dispatch_contract.py
"""Collect before destroy, destroy always, and fail on empty evidence.

P7 in the design is a direct response to a real artifact: the composed-E2E
diagnostics upload contained a `docker ps` header and nothing else, and nobody
noticed because an empty evidence directory is indistinguishable from a passing
run that had nothing to say. So the tier fails when its evidence is empty.

The destroy ordering is the other half. A trap that destroys the VM on failure is
the obvious way to guarantee cleanup and the fastest way to throw away every
diagnostic that would have explained the failure.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH = REPO_ROOT / "scripts" / "ci" / "fleet" / "dispatch.sh"


def test_dispatch_exists_and_is_executable():
    assert DISPATCH.is_file(), f"{DISPATCH} is missing"
    assert DISPATCH.stat().st_mode & 0o111


def test_dispatch_destroys_on_every_exit_path():
    text = DISPATCH.read_text(encoding="utf-8")
    assert "trap " in text, "destroy must run from a trap, not only on the happy path"
    assert "EXIT" in text


def test_dispatch_collects_before_it_destroys():
    """Ordering is the whole point: a trap that destroys first is a trap that
    guarantees you cannot debug the failure it just cleaned up after."""
    text = DISPATCH.read_text(encoding="utf-8")
    collect = text.index("fleet::collect")
    destroy = text.index("fleet::destroy")
    assert collect < destroy, (
        "fleet::collect must be defined and invoked before fleet::destroy in the "
        "cleanup path"
    )


def test_dispatch_fails_when_evidence_is_empty():
    text = DISPATCH.read_text(encoding="utf-8")
    assert "evidence" in text.lower()
    assert "empty" in text.lower(), (
        "P7: an empty evidence directory must fail the tier, not pass quietly"
    )


def test_dispatch_writes_evidence_to_the_flat_layout():
    """artifacts/diagnostics/tier3-<row>/, not artifacts/tier3/<row>/. Section 4
    records why the per-tier subtree was corrected before implementation."""
    text = DISPATCH.read_text(encoding="utf-8")
    assert "artifacts/diagnostics/tier3-" in text
    assert "artifacts/tier3/" not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_fleet_dispatch_contract.py -v`
Expected: FAIL, 5 tests, starting with the missing file.

- [ ] **Step 3: Write dispatch.sh**

```bash
#!/usr/bin/env bash
# Run one Tier 3 matrix row end to end: provision, push, execute, collect, destroy.
#
# The ordering in the cleanup path is load-bearing. Collection happens BEFORE
# destroy, on every exit path including failure and interrupt, because the run
# that fails is the run whose journal you need. A trap that destroys first is a
# trap that reliably deletes the evidence for the only outcome anyone will ask
# about.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

FLEET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROW_ID="${1:?usage: dispatch.sh <row-id> <package-path>}"
PACKAGE="${2:?usage: dispatch.sh <row-id> <package-path>}"

cb::require_file "$PACKAGE" "build it with 'make build' — dist/native/ holds the candidates"
cb::require_tool scp
cb::require_tool ssh

EVIDENCE_ROOT="$(cb::evidence_dir)"
ROW_EVIDENCE="$EVIDENCE_ROOT/diagnostics/tier3-$ROW_ID"
rm -rf "$ROW_EVIDENCE"
mkdir -p "$ROW_EVIDENCE"

VM_DIR=""; SSH_PORT=""; SSH_KEY=""

fleet::ssh() {
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR -i "$SSH_KEY" -p "$SSH_PORT" "$@"
}

fleet::collect() {
    [ -n "$VM_DIR" ] || return 0
    cb::section "Collect evidence → $ROW_EVIDENCE"
    # Best-effort by design: the VM may be wedged, and a failure to collect must
    # not mask the failure being collected. The emptiness check below is what
    # turns "collected nothing" into a failure, which is the guarantee P7 wants.
    if [ -n "$SSH_PORT" ]; then
        scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR -i "$SSH_KEY" -P "$SSH_PORT" -r \
            fedora@127.0.0.1:/tmp/cb-tier3-evidence/. "$ROW_EVIDENCE/" 2>/dev/null \
            || cb::skipped "guest evidence" "scp from the guest failed"
    fi
    [ -f "$VM_DIR/console.log" ] && cp "$VM_DIR/console.log" "$ROW_EVIDENCE/" || true
}

fleet::destroy() {
    [ -n "$VM_DIR" ] || return 0
    cb::section "Destroy $ROW_ID"
    if [ -f "$VM_DIR/qemu.pid" ]; then
        kill "$(cat "$VM_DIR/qemu.pid")" 2>/dev/null || true
        # SIGKILL after a grace period: this is a disposable VM with a disposable
        # overlay, so there is nothing to shut down cleanly and nothing to lose.
        sleep 2
        kill -9 "$(cat "$VM_DIR/qemu.pid")" 2>/dev/null || true
    fi
    rm -rf "$VM_DIR"
}

cleanup() {
    local rc=$?
    fleet::collect
    fleet::destroy
    return "$rc"
}
trap cleanup EXIT INT TERM

cb::section "Provision $ROW_ID"
read -r SSH_PORT SSH_KEY VM_DIR < <("$FLEET_DIR/provision.sh" "$ROW_ID")

cb::section "Push the candidate and the tier script"
fleet::ssh fedora@127.0.0.1 'sudo mkdir -p /opt/cb-tier3 && sudo chown fedora /opt/cb-tier3'
scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -i "$SSH_KEY" -P "$SSH_PORT" \
    "$PACKAGE" "$CB_REPO_ROOT/scripts/ci/tier3-artifact.sh" \
    fedora@127.0.0.1:/opt/cb-tier3/

cb::section "Execute tier3-artifact.sh in the guest"
fleet::ssh fedora@127.0.0.1 \
    "sudo bash /opt/cb-tier3/tier3-artifact.sh /opt/cb-tier3/$(basename "$PACKAGE")"

# Collect explicitly here as well as in the trap: on the success path we want the
# emptiness check below to run against real content, and the trap's copy is
# idempotent.
fleet::collect

if [ -z "$(ls -A "$ROW_EVIDENCE" 2>/dev/null)" ]; then
    printf '::error::evidence directory %s is empty — the tier cannot report a pass it did not observe (P7)\n' \
        "$ROW_EVIDENCE" >&2
    exit 1
fi

cb::section "Row $ROW_ID passed — evidence in $ROW_EVIDENCE"
ls -la "$ROW_EVIDENCE"
```

Then `chmod +x scripts/ci/fleet/dispatch.sh`.

- [ ] **Step 4: Run the contract test**

Run: `.venv/bin/pytest tests/build/test_fleet_dispatch_contract.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/fleet/dispatch.sh tests/build/test_fleet_dispatch_contract.py
git commit -m "feat(fleet): dispatch a row — collect before destroy, destroy always

ADR 0005 Phase 2, P7. Collection runs before destroy on every exit path,
including failure and interrupt, because the run that fails is the run whose
journal anyone will ask for -- a trap that destroys first reliably deletes the
evidence for the only outcome that matters. An empty evidence directory fails the
row rather than passing quietly, which is the direct response to the composed-E2E
diagnostics artifact that contained a docker ps header and nothing else."
```

---

### Task 5: `make verify-fleet`, and the docs that stop it being believed twice

**Files:**
- Modify: `Makefile` (add `verify-fleet` beside `verify`/`verify-full`)
- Modify: `docs/design/2026-08-27-verification-strategy-design.md` (§4 entry-point status, §7 substrate)
- Test: `tests/build/test_fleet_make_target.py`

**Interfaces:**
- Consumes: `dispatch.sh` from Task 4, `matrix.yaml` from Task 1.
- Produces: `make verify-fleet`, which builds nothing — it requires a candidate to already exist and says so.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_fleet_make_target.py
"""verify-fleet must not silently test a stale artifact.

The tier's whole claim is "this candidate installs and boots". A target that
falls back to whatever .rpm happens to be in dist/ makes that claim about a file
whose provenance nobody checked -- which is the same defect class as the security
gate reporting a missing scanner as a clean scan (#106): a result that reads like
a pass and was never an observation.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n|\n)*)", text, re.M)
    assert match, f"no {target} target in the Makefile"
    return match.group(1)


def test_verify_fleet_target_exists():
    _recipe("verify-fleet")


def test_verify_fleet_calls_dispatch_not_an_inlined_body():
    """P1: the gate body lives in scripts/ci, and make is a thin caller."""
    recipe = _recipe("verify-fleet")
    assert "fleet/dispatch.sh" in recipe
    assert "qemu-system" not in recipe, "the gate body belongs in dispatch.sh, not the Makefile"


def test_verify_fleet_requires_an_explicit_candidate():
    recipe = _recipe("verify-fleet")
    assert "CB_CANDIDATE" in recipe, (
        "verify-fleet must take the candidate package explicitly (CB_CANDIDATE=...) "
        "rather than globbing dist/ and testing whatever it finds"
    )


def test_verify_fleet_is_documented_in_help():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^verify-fleet:.*##", text, re.M), (
        "the target needs a ## description or it will not appear in `make help`"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_fleet_make_target.py -v`
Expected: FAIL, 4 tests — no such target.

- [ ] **Step 3: Add the target**

Insert immediately after `verify-full` in the Makefile:

```makefile
# T3. Not part of `verify` and deliberately not wired into any workflow yet:
# it boots a VM, downloads a 500MB image on first run, and takes minutes, which
# is not a pre-push gate. Phase 2 ships one row; Phase 3 adds the matrix.
#
# CB_CANDIDATE is required rather than defaulted to a dist/ glob. The claim this
# tier makes is "*this* candidate installs and boots"; a target that tests
# whatever .rpm happened to be lying in dist/ makes that claim about a file whose
# provenance nobody checked, which is #106's defect class wearing different
# clothes.
verify-fleet: ## Tier 3 — install+boot the candidate on an ephemeral Fedora VM (CB_CANDIDATE=path/to.rpm)
	@test -n "$(CB_CANDIDATE)" || { \
	  echo "ERROR: set CB_CANDIDATE to the package under test, e.g."; \
	  echo "  make build && make verify-fleet CB_CANDIDATE=dist/native/circuit-breaker_$(VERSION)_amd64.rpm"; \
	  exit 2; }
	scripts/ci/fleet/dispatch.sh fedora-rpm-amd64 "$(CB_CANDIDATE)"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_fleet_make_target.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Check the guard fires**

Run: `make verify-fleet`
Expected: exit 2 and the two-line hint. A target that boots a VM when invoked with no argument is a target that wastes ten minutes explaining itself.

- [ ] **Step 6: Correct the design document**

The design's §4 entry-point block lists `make verify-fleet  # T3  — pre-release` under a note saying T2/T3 callers are "the target shape, not yet wired". That is now half true, and a stale status line in the document everyone reads first is how the T1 two-definitions gap went unnoticed. Update it to state exactly what exists: `verify-fleet` runs one row, on a local QEMU VM, invoked only by `make`.

In §7.1, record the substrate decision — the design specifies PVE template clones, and Phase 2 implements the same lifecycle on local QEMU because no PVE fleet was reachable. Note that `runner: local/qemu` is the field that carries the difference, and that `tier3-artifact.sh` is unchanged by it, which is the property that makes the PVE backend a drop-in later.

Do not update §8's support-tier table. This row backs *install and boot*; the Tier 1 guarantee also claims upgrade and rollback, which Phase 3 adds. Claiming it now would make the table a promise the tier does not keep.

- [ ] **Step 7: Commit**

```bash
git add Makefile tests/build/test_fleet_make_target.py \
        docs/design/2026-08-27-verification-strategy-design.md
git commit -m "feat(fleet): make verify-fleet, and correct the design's entry-point status

ADR 0005 Phase 2. CB_CANDIDATE is required rather than defaulted to a dist/ glob:
this tier's claim is that *this* candidate installs and boots, and a target that
tests whatever rpm was lying in dist/ makes that claim about a file whose
provenance nobody checked.

The design's entry-point block described verify-fleet as unwired target shape.
Half of that is now false, and a stale status line in the document everyone reads
first is exactly how the T1 two-definitions gap survived. Section 8's support-tier
table is deliberately NOT updated: this row backs install and boot, and the Tier 1
guarantee also claims upgrade and rollback, which Phase 3 adds."
```

---

### Task 6: Run it against a real candidate and report what it found

**Files:**
- Modify: `docs/design/2026-08-27-verification-phase2-plan.md` (this file — the findings section)

**Interfaces:**
- Consumes: everything above.
- Produces: a measured wall-clock number and a list of findings. Both are deliverables, not notes.

- [ ] **Step 1: Build a candidate**

Run: `make build`
Expected: `dist/native/circuit-breaker_0.4.0_amd64.rpm` exists. `make build` runs `npm ci` and PyInstaller and takes several minutes. If nfpm is missing, `scripts/build_native_release.py` prints `nfpm not found — skipping deb/rpm generation` and *still exits 0* — check for the file, do not trust the exit code.

- [ ] **Step 2: Run the tier and time it**

```bash
/usr/bin/time -f '\nTIER3_WALL_CLOCK=%E' \
  make verify-fleet CB_CANDIDATE=dist/native/circuit-breaker_0.4.0_amd64.rpm
```

Expected: exit 0, and `artifacts/diagnostics/tier3-fedora-rpm-amd64/` containing at minimum `install.log`, `version.txt`, `livez.json`, `readyz.json`, `alembic_version.txt`, `journal.log`, `package-contents.txt`, `console.log`.

**Record the wall clock against the 20-minute budget.** If it exceeds it, do not relax the budget — the first thing to cut is the image download, which is a one-time cost that should not be counted after the first run; measure a warm run separately and report both.

- [ ] **Step 3: Read the evidence, do not just check the exit code**

```bash
cat artifacts/diagnostics/tier3-fedora-rpm-amd64/readyz.json
cat artifacts/diagnostics/tier3-fedora-rpm-amd64/version.txt
cat artifacts/diagnostics/tier3-fedora-rpm-amd64/alembic_version.txt
grep -iE 'error|fail|traceback' artifacts/diagnostics/tier3-fedora-rpm-amd64/journal.log | head -20
```

A green exit with a journal full of tracebacks is the outcome this tier exists to make visible. Read it.

- [ ] **Step 4: Write the findings into this plan**

Append a `## Findings` section to this file recording, for each: what was observed, the evidence path, and whether it is a package defect, a fixture gap, or a tier bug. Expected candidates, based on what was verified while planning:

- the `/etc/circuit-breaker/` vs `/etc/circuitbreaker/` config-path divergence between `packaging/postinstall.sh` and `deploy/setup.sh`, and the `circuitbreaker` vs `breaker` DB user that goes with it;
- the absent `cb` CLI (`nfpm.yaml` ships no `deploy/cli/cb`) — recorded by the tier as `SKIPPED (not shipped by nfpm.yaml)`;
- anything the journal shows that `/readyz` does not.

Do **not** fix these in this phase. Each is its own change with its own test, and a phase that both builds the detector and silently repairs what it detects leaves nobody able to tell which of the two was load-bearing.

- [ ] **Step 5: Full gate, then commit**

```bash
.venv/bin/pytest tests/build -q      # every repo-policy test, including the five new files
make verify                          # the pre-push gate must still pass
git add docs/design/2026-08-27-verification-phase2-plan.md
git commit -m "docs(fleet): Phase 2 findings and the measured Tier 3 wall clock"
```

---

## Self-Review

**Spec coverage.** §7.1's lifecycle is covered minus upgrade and rollback, which §11 assigns to Phase 3: provision (Task 2), install/boot/exercise (Task 3), collect and destroy (Task 4). §7.2's matrix is Task 1, one row, with the `runner` field carrying the only site-specific difference exactly as the spec requires. §7.3's evidence-before-destroy and empty-evidence failure are Task 4, tested. §5's file layout is followed exactly, so Phase 3 adds rows and Phase 6 adds a PVE backend without reshaping anything. §8's support-tier table is deliberately left alone, and Task 5 Step 6 says why.

**Deliberately not covered, and not gaps:** upgrade/rollback and the remaining matrix rows are Phase 3; CI wiring and release gating were scoped out by decision on 2026-08-27; the multi-host agent and Proxmox slice is Phase 6. The PVE substrate the design names is replaced by local QEMU for this phase, recorded in Task 5 Step 6 rather than left as an undocumented divergence.

**Placeholders.** Two, both deliberate and both bounded by a step that resolves them: `image_url` and `image_sha256` in Task 1 Step 4, which Task 1 Step 3 resolves with exact commands and Task 1 Step 5 fails on if left unsubstituted. Everything else carries its command or its code.

**Type consistency.** `provision.sh` prints `<ssh_port> <ssh_key> <vm_dir>`; `dispatch.sh` reads exactly those three in that order. `fleet::collect` and `fleet::destroy` are named identically in the dispatch script and in `test_dispatch_collects_before_it_destroys`. The row id `fedora-rpm-amd64` is used identically in `matrix.yaml`, the Makefile target, the dispatch invocation and the evidence path `artifacts/diagnostics/tier3-fedora-rpm-amd64/`. `TIER_SCRIPTS` is extended in Task 3 to the name `tier3-artifact.sh` created in the same task. `/tmp/cb-tier3-evidence` is written by `tier3-artifact.sh` and read by `fleet::collect`. `/var/lib/cloud/cb-fixture-ready` is written by the cloud-init `runcmd` and waited on by `provision.sh`.

---

## Findings

First real run: `make verify-fleet CB_CANDIDATE=dist/native/circuit-breaker_0.4.0_amd64.rpm`,
against `circuit-breaker_0.4.0_amd64.rpm` (115 MB, built by `make build` with nfpm 2.47.0).

**Exit 2, wall clock 2m59s** (re-run after the evidence fix: 3m04s). The 20-minute
budget in §4 holds with large margin; the golden-image download is a one-time
30s cost outside that, already cached.

### F1 — the packaged service crash-loops on a clean host (package defect)

```
OSError: [Errno 30] Read-only file system: '/data'
circuit-breaker.service: Failed with result 'exit-code'
```

Repeated until `/livez` timed out at 120s. Evidence:
`artifacts/diagnostics/tier3-fedora-rpm-amd64/journal.log`.

Mechanism:

* `packaging/postinstall.sh` generates `/etc/circuit-breaker/circuit-breaker.env`
  with `CB_DB_URL`, `CB_VAULT_KEY`, `CB_REDIS_URL`, `NATS_AUTH_TOKEN`,
  `STATIC_DIR`, `CB_ALEMBIC_INI` and `CB_AGENT_BINARIES_DIR` — and **no
  `CB_DATA_DIR`**. The collected `installed.env.redacted` shows exactly that key
  list, which is what makes this finding self-evidencing rather than inferred.
* Four modules fall back to `/data` when it is unset: `main.py:549`,
  `services/acme_service.py:60`, `services/agent_install.py:182`,
  `services/certificate_activation.py:44`. `/data` is the Docker path.
* `packaging/circuit-breaker.service` sets `ProtectSystem=strict` with
  `ReadWritePaths=/var/lib/circuit-breaker /var/log/circuit-breaker
  /etc/circuit-breaker`, so `/data` is both absent and unwritable.

The package already creates `/var/lib/circuit-breaker` and grants it write access
in the unit, so the intended directory is unambiguous — the generated env simply
never names it. This is the escaped-bug class ADR 0005 §11 predicted for this
phase: a defect that exists only in the *packaged native* build and is invisible
to every suite that runs from a source tree.

Not fixed here, deliberately. It is a one-line change to postinstall.sh plus a
test, and a phase that builds the detector and silently repairs what it detects
leaves nobody able to tell which half was load-bearing.

### F2 — the `cb` operator CLI is not shipped in the package (packaging gap)

Recorded by the tier as
`SKIPPED (not shipped by nfpm.yaml): the cb operator CLI`
(`artifacts/diagnostics/tier3-fedora-rpm-amd64/cb-cli.txt`).

`nfpm.yaml`'s `contents:` installs the binary, the frontend and backend trees,
`VERSION`, the agent binaries, the config template and the unit. `deploy/cli/cb`
is not among them, so `tests/build/test_cb_cli_contract.py` and
`test_cb_cli_parity.py` govern a CLI that a package install never provides. Whether
that is intended is a product question, not a tier question; the tier's job was to
say so out loud rather than assert something else in its place.

### F3 — /etc/circuit-breaker vs /etc/circuitbreaker (not reached)

Predicted before the run and **not** reached: the service never got far enough to
read a database, so the config-path and DB-user divergence between
`packaging/postinstall.sh` (`/etc/circuit-breaker/`, user `circuitbreaker`) and
`deploy/setup.sh` (`/etc/circuitbreaker/`, user `breaker`) is still unexercised.
It stays a prediction until F1 is fixed and the row reaches `/readyz`.

### What passed

* Install via `dnf install` of the local rpm, with its weak dependencies resolved.
* Every path in the package contents assertion, including the unit file and the
  generated env.
* Env file mode is `600`, checked rather than trusted — it is created by a shell
  script at install time, which is where a mode gets missed.
* Version parity: `shipped=0.4.0 reported=0.4.0`.

### Tier defects found by running it

Recorded because they were fixed *inside* this phase and each one is a way this
tier could have reported something it had not observed:

1. `-nographic` cannot combine with `-daemonize` (`59328c94`).
2. `redis` is not a Fedora 44 package; `valkey` replaced it. `packages:` is one
   dnf transaction, so that single wrong name also prevented `postgresql-server`
   from installing (`59328c94`).
3. The cloud-init readiness marker was written even when every step before it
   failed, so provisioning reported a ready host with nothing installed on it
   (`59328c94`), and the host did not verify it independently (`30b2c615`).
4. A failed provision leaked its scratch directory and any VM in it (`30b2c615`).
5. `|| true` on evidence collection discarded the fact that a collector had
   failed; replaced by `capture`, which records the command and its real exit
   status (`dc6e1ccd`).
6. Evidence written as root was copied at mode 0600, so scp returned non-zero and
   the whole collection read as failed while four of five files had transferred
   (`e947ba97`).

Every one of these was invisible to the contract tests, which passed throughout.
The step that caught them was running the thing.
