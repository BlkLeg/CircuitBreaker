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
# cb::matrix_field (lib/common.sh) is the one definition; dispatch.sh reads the
# same file for a row's `mode`, and Phase 3's second row made the id matching
# load-bearing -- "fedora-rpm-amd64" is a prefix of "fedora-rpm-amd64-upgrade",
# which the substring test this replaced would have resolved to the wrong row.
ROW_ID="${1:-fedora-rpm-amd64}"
IMAGE_URL="$(cb::matrix_field "$ROW_ID" image_url "$MATRIX")"
SSH_USER="$(cb::matrix_field "$ROW_ID" ssh_user "$MATRIX")"
CLOUD_INIT="$(cb::matrix_field "$ROW_ID" cloud_init "$MATRIX")"

# Exactly one digest, and which one decides the checker. Fedora publishes
# sha256, Debian publishes sha512 and nothing else; demanding a single algorithm
# would have meant computing one distributor's digest locally and calling it a
# pin, which proves only that the file has not changed since it was fetched.
IMAGE_SHA256="$(cb::matrix_field "$ROW_ID" image_sha256 "$MATRIX")"
IMAGE_SHA512="$(cb::matrix_field "$ROW_ID" image_sha512 "$MATRIX")"
if [ -n "$IMAGE_SHA256" ] && [ -n "$IMAGE_SHA512" ]; then
    printf '::error::row %s declares both image_sha256 and image_sha512 — name the one the distributor publishes\n' "$ROW_ID" >&2
    exit 1
elif [ -n "$IMAGE_SHA256" ]; then
    IMAGE_SHA="$IMAGE_SHA256"; SHA_TOOL=sha256sum
elif [ -n "$IMAGE_SHA512" ]; then
    IMAGE_SHA="$IMAGE_SHA512"; SHA_TOOL=sha512sum
else
    IMAGE_SHA=""; SHA_TOOL=""
fi

if [ -z "$IMAGE_URL" ] || [ -z "$IMAGE_SHA" ] || [ -z "$SSH_USER" ] || [ -z "$CLOUD_INIT" ]; then
    printf '::error::row %s is incomplete in %s (need image_url, image_sha256|image_sha512, ssh_user, cloud_init)\n' \
        "$ROW_ID" "$MATRIX" >&2
    exit 1
fi
cb::require_tool "$SHA_TOOL"
cb::require_file "$FLEET_DIR/cloud-init/$CLOUD_INIT" "row $ROW_ID names a cloud-init fixture that does not exist"

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
if ! printf '%s  %s\n' "$IMAGE_SHA" "$GOLDEN" | "$SHA_TOOL" --check --status; then
    printf '::error::golden image checksum mismatch for %s\n' "$GOLDEN" >&2
    printf 'expected %s — delete the file and re-run to refetch\n' "$IMAGE_SHA" >&2
    exit 1
fi

# ── per-run scratch ─────────────────────────────────────────────────────────
VM_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cb-fleet-${ROW_ID}-XXXXXX")"

# Own the scratch until it is handed over. Everything from here on can fail --
# a bad qemu flag, an image that will not boot, a fixture that never completes --
# and each of those leaves a directory holding a disk overlay, plus possibly a
# running VM that nothing is tracking. dispatch.sh does trap and destroy, but
# only after it has READ the path below, so a failure before the handoff has no
# owner at all. Two such directories were found on disk after the -nographic and
# continuation-chain failures during Phase 2; "destroy always" has to include the
# paths that never got far enough to tell anyone.
#
# Cleared deliberately on the success path: from that point the caller owns it.
cb::fleet_scratch_cleanup() {
    [ -n "${VM_DIR:-}" ] || return 0
    if [ -f "$VM_DIR/qemu.pid" ]; then
        local pid
        pid="$(cat "$VM_DIR/qemu.pid")"
        # kill -0 first: signalling an already-dead pid is the normal case here,
        # not a failure. What is worth reporting is a VM that refuses to die,
        # because that is a leak on a host that will run this again.
        if kill -0 "$pid" 2>/dev/null && ! kill "$pid" 2>/dev/null; then
            printf '::error::could not terminate qemu pid %s — VM leaked\n' "$pid" >&2
        fi
    fi
    rm -rf "$VM_DIR"
}
trap cb::fleet_scratch_cleanup EXIT INT TERM
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
    "$FLEET_DIR/cloud-init/$CLOUD_INIT" > "$USER_DATA"
printf 'instance-id: cb-%s\nlocal-hostname: cb-fleet\n' "$ROW_ID" > "$VM_DIR/meta-data"
genisoimage -output "$SEED" -volid cidata -joliet -rock \
    "$USER_DATA" "$VM_DIR/meta-data" >/dev/null 2>&1

# ── boot ────────────────────────────────────────────────────────────────────
# User-mode networking with a forwarded port: no bridge, no tap device, no root.
# The guest is unreachable from the LAN, which is the correct blast radius for a
# machine running an unreviewed candidate package as root.
SSH_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

cb::section "Booting $ROW_ID (ssh on 127.0.0.1:$SSH_PORT)" >&2
# -display none rather than -nographic: -nographic wires both serial and the
# monitor to stdio, which qemu refuses to combine with -daemonize. Serial is
# redirected to console.log below, which is what the diagnostics need anyway.
qemu-system-x86_64 \
    -name "cb-fleet-$ROW_ID" \
    -machine q35,accel=kvm \
    -cpu host \
    -smp 2 \
    -m 4096 \
    -display none -serial "file:$VM_DIR/console.log" -monitor none \
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
until ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" true 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '::error::VM did not accept SSH within 300s — console log follows\n' >&2
        if ! tail -50 "$VM_DIR/console.log" >&2; then
            cb::skipped "console log" "could not be read from the failing VM"
        fi
        exit 1
    fi
    sleep 3
done

# Two waits, not one. SSH comes up well before cloud-init has finished running
# runcmd, and dispatching into a half-provisioned host produces failures that
# look like package bugs.
deadline=$(( SECONDS + 600 ))
until ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" \
        'test -f /var/lib/cloud/cb-fixture-ready' 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '::error::cloud-init fixture did not complete within 600s\n' >&2
        if ! ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" \
                'sudo tail -80 /var/log/cloud-init-output.log' >&2; then
            cb::skipped "cloud-init log" "could not be read from the failing VM"
        fi
        exit 1
    fi
    sleep 5
done

# Confirm the fixture from the host rather than taking the guest's word for it.
# cb-fixture-ready is the guest asserting something about itself, and everything
# downstream -- the install, the boot, every /readyz retry -- is built on this
# function returning success. The first version of the fixture wrote that marker
# with nothing installed, and provisioning reported a ready host; the fixture is
# fail-fast now, but that is one editable file standing between a broken machine
# and a package getting the blame for it. Cheap to check, so check.
#
# WHICH services to check comes from the guest, not from here. Slice 1 hardcoded
# `postgresql && valkey`, which are Fedora's names -- Debian's redis unit is
# redis-server, so the same literal would have failed the Debian row for a
# service that was running perfectly. Each fixture writes the units it started to
# cb-fixture-services and this verifies that list, which keeps every
# distro-specific name in the fixture where the design says it belongs.
# An explicit branch rather than `|| true`. The two outcomes are different
# failures and want different messages: an ssh that dies here means the guest
# went away between the readiness marker and this line, while an empty file
# means the fixture completed without declaring what it started. Collapsing them
# with `|| true` would report the second for both.
FIXTURE_UNITS=""
if ! FIXTURE_UNITS="$(ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" \
        'cat /var/lib/cloud/cb-fixture-services' 2>/dev/null)"; then
    printf '::error::could not read /var/lib/cloud/cb-fixture-services from the guest\n' >&2
    printf 'The readiness marker was present, so %s completed but its service list is unreadable.\n' "$CLOUD_INIT" >&2
    exit 1
fi
if [ -z "${FIXTURE_UNITS//[[:space:]]/}" ]; then
    printf '::error::%s wrote an empty cb-fixture-services list — provisioning cannot verify what it started\n' "$CLOUD_INIT" >&2
    exit 1
fi
if ! ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" \
        "systemctl is-active --quiet $FIXTURE_UNITS" 2>/dev/null; then
    printf '::error::fixture marker present but its services are not active — the guest reported ready and is not\n' >&2
    printf 'units the fixture claims to have started: %s\n' "$FIXTURE_UNITS" >&2
    if ! ssh "${SSH_OPTS[@]}" "$SSH_USER@127.0.0.1" \
            "systemctl is-active $FIXTURE_UNITS; sudo tail -40 /var/log/cloud-init-output.log" >&2; then
        cb::skipped "fixture diagnostics" "could not be read from the failing VM"
    fi
    exit 1
fi

# Handed over: the caller owns the VM from here, so stop cleaning it up.
trap - EXIT INT TERM
printf '%s %s %s\n' "$SSH_PORT" "$KEY" "$VM_DIR"
