# Verification Phase 3 — T3 Breadth — Implementation Plan

**ADR:** [0005 — Verification Tiers and Platform Support](../adr/0005-verification-tiers-and-platform-support.md)
**Design:** [2026-08-27-verification-strategy-design.md](./2026-08-27-verification-strategy-design.md)
**Date:** 2026-08-28
**Status:** Slices 1 and 2 implemented and first executed 2026-08-29 — see [First execution](#first-execution--2026-08-29), which found two release blockers; slices 3–4 not started

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

## First execution — 2026-08-29

The two slices above were written and never run. They have now been run. This
section records what that produced, and it is the reason the phase existed: two
of the three findings below are release blockers that no amount of reading the
code would have surfaced, because both failures are in what the *package* says
about the host rather than in the code the tests cover.

Prerequisites are no longer the obstacle. This host has qemu, qemu-img,
genisoimage and a writable `/dev/kvm`; nfpm 2.47.0 (the version pinned by
`install-build-deps.sh`) installs to `~/.local/bin` without sudo, and
`build_native_release.py` only requires it on `PATH`.

The N-1 artifact is the **published v0.3.4 release asset**, not a rebuild —
downloaded from the GitHub release and verified against its published
`SHA256SUMS`. That matters: a rebuilt N-1 would carry today's packaging
scripts, and both findings below are defects *in the shipped scriptlets of
versions already in users' hands*. A rebuild would have hidden F5 entirely.

### F4. A fresh install of the package cannot start — **release blocker**

`fedora-rpm-amd64` installed cleanly, reported the right version, and then
crash-looped 13 times inside the 120s boot window:

```
CRITI [app.main] STARTUP FAILED: CB_EGRESS_PROXY_URL is required in production
so public outbound HTTP clients cannot bypass controlled egress; set
CB_ALLOW_DIRECT_EGRESS=true to run without a proxy on hosts that have none
```

`validate_core_dependencies` (`startup_validation.py:91`) refuses to boot when
`CB_EGRESS_PROXY_URL` is empty and `CB_ALLOW_DIRECT_EGRESS` is unset.
`packaging/postinstall.sh` generated an env file containing neither. Every other
shipped path answers the gate — `deploy/setup.sh:246`, `docker-compose.yml:75`,
`docker/.env.example:67`, `deploy/.env.template` — and
`docs/installation/configuration.md:86` states as fact that the value is `true`
in "the installer-generated `/etc/circuitbreaker/.env`". The deb/rpm path was
the single exception, so the package's own closing text told the operator to run
`systemctl start circuit-breaker`, and that command could not succeed on any
host. This is the same shape as Phase 2's F1 (`CB_DATA_DIR`) and its follow-on
(`UPLOADS_DIR`): the code is right, and the packaged install never said what it
meant.

**Fixed** by writing `CB_EGRESS_PROXY_URL=` and `CB_ALLOW_DIRECT_EGRESS=true`
into the generated env and adding both to the existing backfill loop, so a host
whose env predates the gate does not stop starting when it upgrades onto a
version that has it. The backfill records the decision the host was already
making — it had no proxy and made direct egress anyway — and echoes each line it
adds. `tests/build/test_package_env_contract.py` gains three tests, one of which
closes the class: any gate that fails startup with "`CB_X` is required in
production" must be answered by the generated env or by the waiver its own error
message names.

### F5. Upgrading from any released version leaves the service disabled — **release blocker**

Slice 1's F3 fix made `preremove.sh` a no-op when the package is being replaced.
That fix cannot help any upgrade from a version that is already published,
because rpm runs the **old** package's `%preun`:

```
1. new %pre    2. unpack    3. new %post (enables)    4. OLD %preun (disables)
```

Verified against the artifact rather than the source tree: `rpm -qp --scripts`
on the published `circuit-breaker_0.3.4_amd64.rpm` shows a `%preun` that stops
and disables `circuit-breaker.service` with no `$1` guard. Every released tag
carries it, `v1.0.0-rc.4` included. So `dnf upgrade` from any shipped version
onto this one ends with the service stopped and disabled, and `postinstall.sh`'s
`try-restart` cannot prevent it — that runs at step 3, one step too early.

The fix has to run *after* the old scriptlet, which means `%posttrans`. nfpm
supports it as `rpm.scripts.posttrans`; `nfpm.yaml` currently declares none. deb
is expected to be unaffected, since dpkg runs the old `prerm` before unpack and
the new `postinst` last — `debian-deb-amd64-upgrade` is what settles that rather
than the expectation.

### F6. The tier probed the dev port — and what that means for Phase 2

With F4 fixed the service started cleanly: migrations ran through `0104`,
`Application startup complete`, `Uvicorn running on http://127.0.0.1:8080`. The
row still failed with `service never became live within 120s`, because
`tier3-artifact.sh` hardcoded `http://127.0.0.1:8000` — the **dev** port, what
`make dev` binds and what the Vite proxy forwards to. The packaged service takes
`start.py`'s default of 8080, which is also the port `postinstall.sh` tells the
operator to open.

This is a harness defect, not a product one, but it carries a correction that
belongs in the record:

**The row had never once reached a live service.** Phase 2's F1 (`CB_DATA_DIR`)
crashed the service before startup completed, so the probe never got as far as
connecting to the wrong port, and this defect sat latent behind a louder one.
"The row ran and found a bug" and "the row ran green" are different claims, and
only the second backs a tier. Phase 2's write-up should be read with that in
mind: its findings are real, its passing state was never demonstrated.

**Fixed** by probing 8080, with
`tests/build/test_tier3_probes_the_served_port.py` coupling the tier's port to
`start.py`'s resolved default and to the port the package prints — a literal in
two files is the shape of defect that file exists to prevent.

### F7. The deb row died at the push step, and the test that should have caught it

`chown: invalid user: 'fedora'`. `dispatch.sh:156` hardcoded the Fedora account
in a `chown`, on the line directly below a correctly parameterised
`"$SSH_USER"@127.0.0.1`. Slice 2's write-up claims this class was closed and a
test already existed for it — but the test looked for `fedora@`, the ssh
*destination* form, and this use is an ownership argument with no `@`. The test
matched the shape of the bug it was written from rather than the shape of the
invariant.

**Fixed** in `dispatch.sh`, and the test now matches the account as a bare word
in any non-comment line of either script. Run across the current tree it finds
exactly this one occurrence and no false positives.

### F8. A locally built package is not the artifact users get — **affects what today's green rows evidence**

With F7 fixed the deb installed on Debian 12 and then failed to execute:

```
Failed to load Python shared library libpython3.14.so.1.0:
/lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.38' not found
```

This is **not** a defect in the released deb. A PyInstaller bundle inherits the
glibc floor of its build host. `build.yml` builds releases on `ubuntu-22.04` with
Python 3.12 — a 2.35 floor, which Debian 12's 2.36 satisfies. This candidate was
built here, on Fedora 44 with glibc 2.43 and CPython 3.14, so it requires 2.38
and Debian 12 cannot run it. The published `v0.3.4` deb has no such problem.

Two things follow, and the second is the important one.

**The `build-from-source` path has an undocumented glibc floor.** `make build`
on a modern host produces packages that run only on hosts at or above that
host's glibc, with no diagnostic beyond a PyInstaller error naming a library the
operator never chose. That belongs in the build documentation.

**More seriously: the tier is currently making its claim about the wrong
artifact.** The Makefile is explicit that testing "whatever .rpm happened to be
lying in dist/" is #106's defect class, and it fixed that by requiring an
explicit `CB_CANDIDATE`. But an explicitly named *locally built* candidate is
still not the artifact a user installs. Today's green `fedora-rpm-amd64` proves
that an rpm built on this Fedora host installs and boots on Fedora 44; it does
not prove the released rpm does, and the two demonstrably differ in their glibc
floor — F8 is that difference making itself visible.

That is a gap in how this tier produces *evidence*, distinct from every other
finding here, which were defects in the product or the harness. Before any
ledger row moves on the strength of a Tier 3 run, the candidate has to be a
CI-built artifact — either downloaded from the release the row is evidencing, or
built in the same `ubuntu-22.04` image the release job uses. Recorded rather
than worked around, because choosing between those two is a change to what ADR
0005 means by "the candidate", not a bug fix.

**Consequence for this session:** the deb rows cannot be validly run from a
Fedora-built candidate and are left unrun. The rpm rows are unaffected on this
host — Fedora 44 satisfies the floor of both the local candidate and the
CI-built `v0.3.4` used as N-1.

### F9. The upgrade row held its fixture to the candidate's standard

The upgrade row's first execution never reached one of its own assertions. It
stopped on the N-1 install:

```
shipped=0.3.4 reported=unknown
::error::binary reports 'unknown' but the shipped VERSION says '0.3.4'
```

The published v0.3.4 binary answers `--version` with `unknown`. That was a real
defect and it is already fixed — 0.4.0 reports correctly. Failing the row on it
is still wrong: the row's claim is that upgrading from N-1 preserves data and
that the documented rollback works, and the old release's self-reporting is a
property of the old release. Nothing in the upgrade contract reads `--version`;
`VERSION_AT_START` comes from the shipped VERSION file. A hard gate on the
fixture means upgrades can only be tested from a *historically perfect* release,
which inverts the row's purpose.

**Fixed** by giving `t3::assert_version_matches` a severity: fatal where the
subject is the artifact under test (`candidate`, `upgraded`), recorded-with-a-
warning where it is the old release (`previous`, `rolledback`). The mismatch
still reaches the evidence directory either way.
`tests/build/test_tier3_version_parity_policy.py` enforces both halves, so the
waiver cannot drift onto the candidate.

### F10. No released version of Circuit Breaker can boot from its own package — **the finding that matters most**

With F9 fixed the row got as far as booting the N-1, and the published v0.3.4
package crash-looped 20 times:

```
circuit-breaker: error: unrecognized arguments: serve
```

v0.3.4's unit is `ExecStart=/usr/local/bin/circuit-breaker serve`, and the
binary's parser takes no `serve` subcommand — it exits 2 before any of the
application's own gates are reached. The current unit carries a comment
explaining exactly this, so it is a known and fixed defect; what nobody had done
is install a released package and start it.

It is not one defect, it is a sequence, and each released version sits behind a
different member of it:

| Version | First blocker | How established |
|---|---|---|
| v0.3.4 | `ExecStart … serve` — the unit passes an argument the binary rejects | **Observed**: 20 crash-loops in a VM |
| v1.0.0-rc.4 | `CB_DATA_DIR` absent — the `/data` read-only crash (Phase 2 F1) | **Observed**: 15 crash-loops in a VM |
| v1.0.0-rc.1 … rc.3 | same as rc.4 | Inferred from `git show <tag>:packaging/postinstall.sh` |
| this tree, before today | `CB_ALLOW_DIRECT_EGRESS` absent (F4) | **Observed**: 13 crash-loops in a VM |

Both headline rows are observations, not inferences. The published
`circuit-breaker_1.0.0-rc.4_amd64.rpm` was downloaded from its GitHub release,
checksum-verified, and run through the install row on Fedora 44:

```
shipped=1.0.0-rc.4 reported=1.0.0-rc.4
OSError: [Errno 30] Read-only file system: '/data'   (×15)
::error::[candidate] service never became live within 120s
```

**The current v1 release candidate cannot start from its own package.** It
installs, it reports the right version, and the service never comes up.

**The deb/rpm install path has never worked in any released version.** The
`install.sh` / `deploy/setup.sh` path is unaffected — it writes every one of
these keys and always has — so users on that path exist and are fine. Users who
followed the packaged-install documentation had a service that could not start.

Two consequences for the v1 push:

1. **The upgrade row cannot be evidenced against any real release, because no
   bootable N-1 exists.** Tier 1's second half — upgrade and rollback — can only
   be exercised from the first version that boots, so the earliest honest
   evidence is `0.4.0 → 0.5.0`. Running it from a synthetic N-1 built out of the
   current tree would exercise the *mechanism*, and should not be recorded as
   evidence of upgrading from a release.
2. **F5 is real but currently unreachable.** Upgrading from a released version
   would leave the service disabled — and it would also never have been running
   in the first place. F5 becomes live the moment a bootable version ships, so
   the `%posttrans` fix still has to land before 1.0.0, not after.

### F5 fixed, and demonstrated against a legacy scriptlet

`%posttrans` is the only scriptlet that runs after the old package's `%preun`,
so that is where the repair goes. `preinstall.sh` records the unit's enabled and
active state at step 1 — the last moment it is still readable — and
`packaging/posttrans.sh` restores exactly that at step 6. It restores what was
recorded rather than enabling unconditionally, for the same reason
`postinstall.sh` uses `try-restart`: an upgrade must not start a service the
operator deliberately stopped.

Wiring it took two attempts, and the first failure is worth recording because it
is the same class as F7. `posttrans` under `overrides.rpm.scripts` is silently
ignored — that key is the packager-agnostic script set, while `%posttrans` is
`RPMScripts` and lives under the **top-level** `rpm:` key. nfpm emitted a package
with no posttrans scriptlet, no error, and the test passed anyway because it was
a substring search over `nfpm.yaml`. The test now parses the YAML structure,
asserts it is *not* under `overrides`, and a companion test runs
`rpm -qp --scripts` against the built artifact. Intent and effect, separately.

**Demonstrated, not just unit-tested.** Because no released version boots (F10),
F5 cannot be exercised from a real N-1. It was exercised instead against a
synthetic one: a 0.3.9 built from this tree — so it boots — carrying
`v1.0.0-rc.4`'s verbatim `preremove.sh` — so it reproduces the regression. Both
of posttrans' messages appeared in the guest, which is the causal chain end to
end:

```
Circuit Breaker: re-enabled circuit-breaker.service — the previous package's
    uninstall scriptlet disabled it during the upgrade.
Circuit Breaker: restarted circuit-breaker.service — the previous package's
    uninstall scriptlet stopped it during the upgrade.
▸ Assert the upgrade left the service running and enabled     ← passed
```

The old scriptlet did stop and disable the unit, and posttrans did put it back.
This evidences the **mechanism**. It is not evidence of upgrading from a
release, and must not be recorded as such.

### F11. The documented rollback could not be run by anything that cannot type

Past the upgrade half, the row executed the documented rollback — through the
shipped `/usr/local/bin/circuit-breaker-rollback` wrapper, exactly as
`docs/installation/upgrading.md` tells an operator to — and stopped dead at the
confirmation banner. `deploy/scripts/restore.sh` ends its safety summary with an
unconditional `read -r -p "Continue? [y/N] "`. Over `ssh host '...'` there is no
TTY and no stdin, so the read took EOF and the restore correctly declined.

So a disaster-recovery tool could not be driven from a runbook, a cron job, or
any script — and the tier whose whole purpose is to evidence ADR 0005's rollback
guarantee could never evidence it, because it cannot type.

**Fixed** with `CB_ASSUME_YES`, consent given in advance, announced in the output
so a recovery log still records that someone agreed. The prompt is unchanged for
everyone else: an operator who hits EOF or closes the pipe still aborts, which is
the rule `test_uninstall_volume_prompt.py` pins — *no answer is not consent*. The
abort message now names the variable, since that is where an automated caller
lands and the only place it will learn the supported way through.

Deliberately **not** copied from `uninstall.sh`: that script answers "can this
process be asked anything at all?" before its first destructive step, because its
prompt came *after* the container had been removed. `restore.sh`'s prompt
precedes every destructive step, so that ordering hazard does not exist here and
a `[ -t 0 ]` gate would only break callers that legitimately pipe an answer.

**A structural note that outlives this fix.** The rollback is performed by the
*previous* package's tooling — the tier downgrades the package before restoring
the dump, deliberately, because restoring an old schema under the new binary
would let `alembic upgrade head` migrate it straight back forward. So a
`restore.sh` fix only reaches rollbacks *to* a version that already carries it,
which is F5's trap in a different file. Human operators are unaffected, since
they can answer the prompt; automation rolling back to any already-released
version still cannot.

### F12. The documented rollback could not authenticate

Past the prompt, the rollback reached the database and could not log in:

```
Password for user circuitbreaker:
psql: error: ... FATAL:  password authentication failed for user "circuitbreaker"
```

The asymmetry: `preinstall.sh` hands `pg_dump` the whole `CB_DB_URL`
(`"$PG_DUMP" "$DB_URL"`), and the URL carries the password, so the *backup*
authenticates. `rollback.sh` instead parses that URL into its parts and exports
`CB_DB_NAME`, `CB_DB_OWNER` and `CB_DB_SUPERUSER` — every identity except the
credential. `restore.sh` has always read `PGPASSWORD="${CB_DB_PASSWORD:-}"`, and
its own comment records why: pg_hba is md5 for 127.0.0.1 and it connects as the
owner. Nothing on the package path ever set it.

This failed on the **default** install rather than an exotic one: the URL
`postinstall.sh` generates is password-auth.

**Fixed** by exporting `CB_DB_PASSWORD`, percent-decoded. The decoding is not
decoration — a password containing `@` or `/` must be encoded in a URL, so those
are exactly the passwords that arrive encoded, and psql fails on the raw form
just as it fails on nothing. The username is decoded the same way, being the same
class of value.

That is the third distinct defect in a rollback path which, before this phase,
had never been executed once: it was not shipped (slice 1, F2), it could not be
driven without a human (F11), and it could not authenticate (F12).

### Status of the rows

| Row | Candidate | Result |
|---|---|---|
| `fedora-rpm-amd64` | 0.4.0, built here | **Passed.** Failed first on F4, then F6; green once both were fixed. `readyz {"db":"ok","redis":"ok"}`, migrations at head, API path exercised, rollback tooling present. |
| `fedora-rpm-amd64` | published `v1.0.0-rc.4` | **Failed** — `/data` crash loop (F10). The RC does not boot from its package. |
| `fedora-rpm-amd64-upgrade` | synthetic 0.3.9 → 0.4.0 | **Passed** — `Tier 3 complete (install, boot, upgrade, roll back)`. Reached only after F5, F9, F11 and F12 were fixed. See the limits below. |
| `fedora-rpm-amd64-upgrade` | published 0.3.4 → 0.4.0 | **Failed at the fixture**: the published 0.3.4 does not boot (F10), so the upgrade contract was never reached. No bootable N-1 exists. |
| `debian-deb-amd64` | 0.4.0, built here | **Blocked** by F8: a Fedora-built candidate cannot run on Debian 12, and testing it there proves nothing about the release. Needs a CI-built artifact. |
| `debian-deb-amd64-upgrade` | — | Not run; blocked by both F8 and F10. |

### What the green upgrade row does and does not evidence

It **does** establish, observed in a VM: the pre-upgrade backup is taken and is
non-empty; the upgrade survives a legacy `%preun` that stops and disables the
unit; the upgraded service becomes ready again on the new binary; the documented
rollback runs unattended through the shipped wrapper, authenticates, replays, and
brings the service back ready; and the marker row written before the upgrade
survives the rollback while the one written after it does not — which is the data
half of the guarantee, and the assertion the whole marker design exists for.

It does **not** establish:

- **Upgrading from a release.** The N-1 is synthetic. No released version boots
  (F10), so this evidences the mechanism, not the path a user takes.
- **Schema rollback.** `alembic_version` is `0104_bugbounty_20260826` before,
  after and rolled back, because both packages are built from the same tree.
  The migration dimension of the guarantee is untested and needs an N-1 whose
  schema genuinely differs.
- **Anything about the released artifact.** F8 still stands: this candidate was
  built here, not by CI.

So Tier 1 stays **not in force**, and no ledger row moves. What has changed is
that the lifecycle is now executable and green, and six product defects and three
harness defects were found by running it.


`fedora-rpm-amd64` against the locally built 0.4.0 is the first Tier 3 row in
this project's history to pass — Phase 2 found a defect with it but never
demonstrated a green run (see F6). Evidence is in
`artifacts/diagnostics/tier3-fedora-rpm-amd64/`, though F8 limits what that
green result evidences.

The same row against the published RC is the more important result, and it is
red.

No ledger row moves yet and Tier 1 stays **not in force**: Tier 1 claims
install, boot, upgrade *and* rollback, and the two upgrade rows have not run.
One green install row backs the install-and-boot half on one distro. What has
changed is that the assertions are no longer hypothetical — the harness
provisions, installs, asserts, collects evidence and passes, and the first thing
it did was find two defects that make the shipped package unusable.

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
