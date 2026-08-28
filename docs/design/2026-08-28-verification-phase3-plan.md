# Verification Phase 3 — T3 Breadth — Implementation Plan

**ADR:** [0005 — Verification Tiers and Platform Support](../adr/0005-verification-tiers-and-platform-support.md)
**Design:** [2026-08-27-verification-strategy-design.md](./2026-08-27-verification-strategy-design.md)
**Date:** 2026-08-28
**Status:** Slices 1 and 2 implemented, neither executed; slices 3–4 not started

## What this phase is for

Design §11 defines Phase 3 as "T3 breadth. The remaining matrix rows: formats, distros, upgrade
and rollback. Closes #103's class."

It is also the phase that decides whether the Tier 1 guarantee can be made at all. ADR 0005 §8
declares Tier 1 as "guaranteed to install, boot, upgrade and roll back" for deb/rpm on amd64.
Phase 2 built the first half. Everything about the second half — that an upgrade preserves data,
that the documented rollback works — was unexercised, and it turned out to be unexercised in the
strong sense: the mechanisms it depends on did not exist.

## Slices

Four, ordered so that each is independently shippable and no slice adds two new axes at once.

| # | Slice | Adds | Status |
|---|---|---|---|
| 1 | Upgrade and rollback on the Fedora row | The lifecycle, on the platform Phase 2 already proved | **Implemented 2026-08-28** |
| 2 | Debian/deb amd64 | A second package manager, and the format-agnostic `tier3-artifact.sh` that P1 claims | **Implemented 2026-08-28** |
| 3 | Tier 3 formats | apk, AppImage, tarball, `pkg.tar.zst` | Not started |
| 4 | arm64 | §8.2's L2 job on `ubuntu-22.04-arm`, and the local qemu-arm64 row | Not started |

Slice 1 first because ADR 0005's in-force clause names it as what moves Tier 1, and because
adding distros before the lifecycle would have meant writing the upgrade contract four times.

---

## Slice 1 — what it found

The plan for this slice was "add an upgrade row". Reading the path it would exercise turned up
three defects first, each of which would have made the row fail for a reason that is not a test
problem.

### F1. The package path took no pre-upgrade backup

`docs/release/1.0.0-compatibility-policy.md` defines rollback as "restoring the complete
pre-upgrade backup". `docs/installation/upgrading.md` told the operator the upgrade takes that
backup itself. Both were true only of the `install.sh` path, where `deploy/setup.sh`'s
`run_upgrade` does it — and it does it carefully, with a gate that fails the upgrade rather than
warning, because it once printed "Backup saved" over a `pg_dump` that had exited non-zero.

`nfpm.yaml` declared `postinstall` and `preremove` and no `preinstall`. `dnf upgrade
circuit-breaker` and `apt upgrade circuit-breaker` migrated the schema and wrote nothing. The
documented recovery named an artifact the package path never created.

**Fixed** by `packaging/preinstall.sh`, which takes the dump on upgrade transactions only and
carries `run_upgrade`'s gate: a reachable database that cannot be dumped fails the transaction; a
database that is absent or unreachable is skipped with a reason, because that is an install with
no data at risk rather than a failed backup.

### F2. The documented rollback tool was not shipped

`deploy/scripts/restore.sh` appeared in no `contents:` entry, so a deb/rpm host did not have it.
The docs printed `/opt/circuitbreaker/deploy/scripts/restore.sh`, which is the `install.sh`
layout — a path that does not exist on a packaged install.

The script itself was already correct: its header records that the two native layouts share no
paths and that every unit, role and file it needs is an overridable variable, "so the
distro-package layout can be restored with the same tool instead of a second copy of it". What
was missing was a caller that set them, and the shipping.

**Fixed** by adding `restore.sh` to `nfpm.yaml` and shipping `packaging/rollback.sh` as
`/usr/local/bin/circuit-breaker-rollback`, which derives the role and database from the installed
`CB_DB_URL` and supplies the rest. With no argument it lists what it can restore.

### F3. Every upgrade left the service stopped and disabled

The worst of the three, and invisible without doing exactly what this phase does.

`preremove.sh` stopped and disabled `circuit-breaker.service` unconditionally. rpm runs the **old**
package's `%preun` *after* the **new** package's `%post`:

```
1. new %pre     (preinstall,  $1=2)
2. new files unpacked
3. new %post    (postinstall, $1=2 — enables the unit)
4. old %preun   (preremove,   $1=1 — stopped and disabled it)
5. old files removed
```

So step 4 undid step 3 on every upgrade. The host finished with the service down and disabled, and
no reboot brought it back. Nothing in the pipeline had ever upgraded a packaged service.

**Fixed** by making `preremove.sh` a no-op when the package is being replaced rather than removed,
across all three packagers' conventions, and by giving `postinstall.sh` a `try-restart` on upgrade —
`try-restart` rather than `restart`, so an upgrade cannot start a service the operator had
deliberately stopped. Without that restart the upgrade would leave the **old** binary serving:
rpm replaces files underneath a live process and tells systemd nothing.

## Slice 1 — what it built

**Packaging.** `packaging/preinstall.sh` (new), `packaging/rollback.sh` (new), corrected
`preremove.sh` and `postinstall.sh`, and the `nfpm.yaml` wiring for all of it. The PostgreSQL
client package is now recommended on deb and rpm: the backup gate needs `pg_dump` and
`pg_isready`, and a host pointing `CB_DB_URL` at another machine installs no server at all.

**The tier.** `tier3-artifact.sh` takes an optional second package. Given one it runs the whole
lifecycle: install N-1, boot, seed a marker row, upgrade to N, then assert the backup was taken,
the unit is still enabled and running, the service becomes ready again, the schema advanced and the
marker survived — then execute the documented rollback and assert the pre-upgrade revision and data
are back and the post-upgrade data is gone. Given no second package it runs Phase 2's contract,
unchanged.

**The matrix.** Rows gained `mode`, because `tier: 1` alone could not distinguish a row that
proves install-and-boot from one that proves the whole guarantee. `fedora-rpm-amd64-upgrade` is the
first `mode: upgrade` row. `cb::matrix_field` moved into `lib/common.sh` so the dispatcher and the
provisioner read the matrix through one definition (P1) — and the move fixed a latent bug on the
way: the old reader matched row ids by substring, and `fedora-rpm-amd64` is a prefix of
`fedora-rpm-amd64-upgrade`.

**The entry point.** `make verify-fleet-upgrade CB_CANDIDATE=… CB_CANDIDATE_PREVIOUS=…`. Both are
explicit for the same reason `CB_CANDIDATE` always was, and one more: `dnf` treats an upgrade to an
identical NEVRA as a no-op and exits zero, so a defaulted path would produce a passing run that
upgraded nothing.

### Why the marker row rather than application data

The claim under test is not "the model survived" — that would couple the tier to whichever schema
two versions happen to share. It is "the database this host had before the upgrade is the database
it has after the rollback". A table outside Alembic's control answers exactly that. Two rows are
written, one before the upgrade and one after, so the rollback has something it must *remove*:
without the second, the assertion would pass over a restore that did nothing at all.

### Why the rollback downgrades the package first

The pre-upgrade dump carries the old schema, and `main.py` runs `alembic upgrade head` at startup.
Restoring it under the new binary migrates the schema straight back forward and the rollback
silently undoes itself. Downgrading first is load-bearing, not tidiness, and
`docs/installation/upgrading.md` now says so where an operator will read it.

## What slice 1 does **not** establish

**The row has never been executed.** It was implemented on a host with no `qemu-system-x86_64`, no
`genisoimage` and no built artifacts, so every assertion above is written and none is observed.
Tier 1 stays **not in force** in ADR 0005's table, and the ledger records no evidence. Running it
needs a host with the fleet prerequisites and two builds at different `VERSION` values.

**apk gets no pre-upgrade backup.** Alpine calls a separate `.pre-upgrade` script that nfpm does not
emit. Recorded rather than worked around: apk is a Tier 3 build-only format, and inventing a hook
nfpm will not install would be worse than naming the gap. Documented in `upgrading.md`.

**The `cb` operator CLI is still absent from the package.** Unchanged from Phase 2, still recorded
by the tier rather than asserted.

---

## Slice 2 — the deb family, and what "identical across every row" costs

Phase 2 satisfied P1 — `tier3-artifact.sh` is "identical across all of them" — by having exactly
one row. Every install, query and downgrade was a bare `dnf`/`rpm` call, and the script was
identical across rows the way a sentence is grammatical in a language with one sentence in it.
Slice 2 is the first time the claim costs anything.

### What moved

**The package layer.** Three functions — `pkg::install_dir`, `pkg::downgrade_to`,
`pkg::list_contents` — and nothing outside them names a package manager. The format comes from the
candidate's extension rather than from a caller-set variable: a row that hands the script a `.deb`
*is* a deb row, so a mismatch between the row and the artifact fails here with a named reason
instead of surfacing as a plausible dependency error inside the guest. An upgrade across formats is
rejected outright. `tests/build/test_fleet_multi_distro.py` parses the script and fails on any
package-manager call at command position outside that layer — substring matching was not good
enough and produced a false positive on `*.rpm) PKG_FORMAT=rpm ;;` the first time.

**Two apt details that would each have looked like a packaging bug.** `apt-get install` needs
`--allow-downgrades` or it reports the newer installed version as satisfying the request and exits
zero, leaving the new binary in place for the rollback assertion to trip over somewhere far from
the cause. And `--install-recommends` is passed explicitly rather than relied on, because a host
with `APT::Install-Recommends "false"` would silently drop the companion broker and produce an
install no user has.

**Provisioning stopped being Fedora-shaped.** `ssh_user` and `cloud_init` are row fields now, since
cloud images use different default accounts and a hardcoded one fails every other image with
`Permission denied (publickey)` — which reads like a broken key rather than a wrong username. The
fixture-verification step used to check `postgresql && valkey` from the host; Debian's redis unit
is `redis-server`, so that literal would have failed a perfectly healthy Debian guest. Each fixture
now writes the units it started to `/var/lib/cloud/cb-fixture-services` and provisioning verifies
that list, which keeps every distro-specific name in the fixture where the design says it belongs.

**Both entry points can reach every row.** `CB_ROW` selects the matrix row, defaulting to the
Fedora rows so the common case stays a one-variable command. A matrix grows rows nobody runs when
the only entry point hardcodes one id.

### Image digests: why the schema now takes either algorithm

Fedora publishes `CHECKSUM` with sha256. Debian publishes `SHA512SUMS` and nothing else. Insisting
on sha256 for both would have meant downloading Debian's image, hashing it locally, and calling the
result a pin — which proves only that the file has not changed since it was fetched, and would pin
a tampered image exactly as faithfully as a good one. The matrix takes `image_sha256` **or**
`image_sha512`, exactly one, and the row's choice selects the checker.

Both URLs now point at dated, immutable paths rather than `latest`. A gate whose input can change
without a commit is not a controlled input, and the eventual failure looks like a corrupt download
rather than a new upstream release.

### `nats-server` on Debian — checked, not assumed

The deb declares a **hard** `depends` on `nats-server`, which would make the whole row fail at
install if Debian did not package it. It does, in bookworm and trixie. So the Debian fixture
deliberately does *not* pre-install it: apt pulls it during the install the tier performs, and
pre-installing it would hide a broken dependency declaration, which is one of the things this row
exists to catch. The rpm side cannot do this — Fedora packages no broker at all, which is why the
rpm ships a separate `circuit-breaker-nats` package that `dispatch.sh` pushes alongside.

### Still not executed

Same as slice 1, and worth repeating because it is the thing that matters: **neither row has ever
run.** The host these were written on has no `qemu-system-x86_64`, no `genisoimage`, no `nfpm` and
no built artifacts, and no passwordless sudo to install any of them. Every assertion in both slices
is written and none is observed. Tier 1 stays **not in force** and no ledger row moves.

## Next

**Slice 3 — Tier 3 formats.** apk, AppImage, tarball and `pkg.tar.zst`. These are "guaranteed to
build" rather than "guaranteed to install", so the tier's contract for them is narrower and the
`pkg::` layer needs arms that reflect that rather than pretending an AppImage installs.

**Slice 4 — arm64.** §8.2's L2 job, extending `artifact-smoke.yml`'s existing native
`ubuntu-22.04-arm` run from "prints a version" to the full boot-and-exercise contract. This is the
slice that moves Tier 2 into force, and it needs no hardware purchase — the runners are already in
use and already free for this public repository.

**Before either: run what exists.** Two implemented slices with zero executions is the largest
single gap in this phase. It needs a host with qemu, genisoimage and nfpm, and two builds at
different `VERSION` values.
