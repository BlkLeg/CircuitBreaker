"""Backfill a re-discovered device instead of queueing it for review again.

The review queue is `scan_results` filtered to `merge_status='pending'`, and
`discovery_result_service` already decides — on both the server and the agent
path — whether a finding is `new`, `matched` or `conflict`. What was missing is
what happens next: a `matched` row sat in the queue looking exactly like a new
device, demanding the same manual Accept, while the data it carried never
reached the `Hardware` row it had already been matched to. On a real install
that meant fourteen devices with a NULL `mac_address` and the pending finding
holding that exact MAC sitting one table away.

This module closes that gap, under three rules that are the whole design:

* **It never creates.** There is no `else: create` branch. It runs only when the
  classifier has already pointed at an existing `Hardware` row.
* **It never overwrites.** Every field write is guarded on the current value
  being empty. A value an operator typed, or an earlier scan wrote, survives.
* **It never renames.** `Hardware.name` is not in the rule set at any tier, and
  `Hardware.hostname` is written only for a server-observed finding — an agent
  is an untrusted remote executor, and `discovery_service._auto_merge_known_devices`
  already established that its hostname is an observation and not a fact.

Those three are also the answer to `discovery_service.finalize_agent_job`'s rule
that an agent-authored row must not reach the inventory without review. That rule
names its own reason — `discovery_merge._auto_merge_result` *creates* a
`Hardware` row — and none of the three things it guards against happen here.
Every value this module writes is one an operator would have written by clicking
Accept on a row the queue was showing them; what is removed is the click, for the
strict subset of writes that fill a hole rather than change an answer.

No-commit by design: the caller owns the transaction. The agent path calls this
inside the SAVEPOINT that also guards its replay key, so an over-ceiling finding
rolls the enrichment back with the insert.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.db.models import Hardware, ScanResult
from app.services.discovery_network import _norm_mac
from app.services.inference_service import InferredAnnotation, annotate_result
from app.services.log_service import write_log

logger = logging.getLogger(__name__)

# The `merge_status` an enriched row lands in. Deliberately the value
# `discovery_service._auto_merge_known_devices` has always written rather than a
# new one: it already exists in production data and already means "the system
# updated a known device; no human needed". A second value for the same fact
# would split the review queue's "recently enriched" list across two
# vocabularies forever.
ENRICHED_MERGE_STATUS = "auto_updated"

# Sources this module does not touch. Proxmox rows carry synthetic addresses
# (`qemu:<node>:<vmid>`) that no scan can match and are merged by
# `discovery_proxmox_merge` against `proxmox_vmid`; Docker rows are containers,
# reconciled by `docker_discovery` against `docker_container_id`. Neither is a
# host the MAC/IP matcher can speak about.
_SKIPPED_SOURCE_TYPES = frozenset({"proxmox", "docker"})

AUDIT_ACTION = "result_auto_enriched"


@dataclass(frozen=True)
class EnrichmentOutcome:
    """What one `enrich_matched_result` call did.

    `enriched=False` means the row was not an enrichment candidate at all and
    nothing was touched. `enriched=True` with an empty `fields` means the device
    was already complete and only its liveness moved — which is the steady state
    on a network that has been scanned before, and is why the audit row below is
    written conditionally.
    """

    enriched: bool
    hardware_id: int | None = None
    hardware_name: str | None = None
    fields: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Ctx:
    """One enrichment in progress. Exists so the rule table's extractors can
    share a lazily-computed OUI/hostname/port inference across fields without
    paying for it on the common path where nothing is empty."""

    db: Session
    result: ScanResult
    hardware: Hardware
    _annotation: InferredAnnotation | None = None

    @property
    def annotation(self) -> InferredAnnotation:
        """Vendor/icon inferred from the finding's MAC OUI, hostname and ports.

        Computed at most once, and only when a rule actually reaches for it —
        `annotate_result` loads the device knowledge base, which is not worth
        doing for a finding whose device already has a vendor.
        """
        if self._annotation is None:
            self._annotation = annotate_result(self.result)
        return self._annotation


def _extract_mac(ctx: _Ctx) -> str | None:
    """The finding's MAC, canonicalised — unless another device already claims it.

    The guard matters because this rule can fire on a row matched by *IP*. Filling
    a MAC from an IP match writes the identity that every future MAC-tier lookup
    will follow, so a reporter that claims an address already belonging to another
    device must not be able to install that claim silently. When two devices
    disagree about a MAC, that is a review, and leaving the field empty keeps the
    row's next classification honest.
    """
    mac = _norm_mac(ctx.result.mac_address)
    if not mac:
        return None
    clash = ctx.db.execute(
        select(Hardware.id)
        .where(Hardware.mac_address == mac, Hardware.id != ctx.hardware.id)
        .limit(1)
    ).first()
    if clash is not None:
        logger.debug(
            "discovery_enrich: not filling MAC %s on hardware %s — hardware %s already holds it",
            mac,
            ctx.hardware.id,
            clash[0],
        )
        return None
    return mac


def _extract_hostname(ctx: _Ctx) -> str | None:
    """The finding's hostname — for a server-observed finding only.

    `discovery_service._auto_merge_known_devices` established the rule and the
    reasoning: an agent's hostname is an observation about what a remote executor
    saw, not a fact about the device, so it may not name a device the inventory
    left unnamed. Naming is what an operator does in the review queue.
    """
    if ctx.result.discovery_agent_id is not None:
        return None
    return ctx.result.hostname or ctx.result.snmp_sys_name


def _extract_vendor(ctx: _Ctx) -> str | None:
    """The reported vendor, else one inferred from the OUI of the MAC we just filled."""
    return ctx.result.os_vendor or ctx.annotation.vendor


# (Hardware attribute, extractor). Applied in order; each writes only when the
# current Hardware value is falsy. `name`, `role`, `model` and `notes` are
# absent on purpose: `name` and `role` are operator-meaningful answers the review
# queue asks for explicitly, and nothing in the discovery pipeline produces a
# model string at all.
_FIELD_RULES: tuple[tuple[str, Callable[[_Ctx], str | None]], ...] = (
    ("mac_address", _extract_mac),
    ("ip_address", lambda ctx: ctx.result.ip_address),
    ("hostname", _extract_hostname),
    ("vendor", _extract_vendor),
    ("vendor_icon_slug", lambda ctx: ctx.annotation.vendor_icon_slug),
    ("os_version", lambda ctx: ctx.result.os_family),
    ("discovered_at", lambda ctx: utcnow_iso()),
)


def _is_candidate(db: Session, result: ScanResult) -> Hardware | None:
    """The guard ladder. Returns the Hardware row to enrich, or None.

    Ordered cheapest-first, and every rejection is silent: an enrichment that
    does not apply is not an error, it is the normal outcome for the majority of
    rows the classifier produces.
    """
    # Never re-enrich. This is also what makes a replayed agent finding inert
    # even if it somehow reached this function twice.
    if result.merge_status != "pending":
        return None
    # `conflict` is the operator's decision and `new` is not this module's
    # business — creating is exactly what enrichment does not do.
    if result.state != "matched":
        return None
    if result.matched_entity_type != "hardware" or result.matched_entity_id is None:
        return None
    if result.source_type in _SKIPPED_SOURCE_TYPES:
        return None
    hardware = db.get(Hardware, result.matched_entity_id)
    if hardware is None:
        # The device was deleted between classification and here. `merge_scan_result`
        # raises 409 for this because a human is waiting on an answer; there is no
        # one waiting here, so the row simply stays pending and the next scan
        # reclassifies it.
        return None
    # Re-assert the tenant predicate `_match_hardware` applies to agent findings.
    # `matched_entity_id` may have been written by a build that predates that
    # predicate — including, on the very first run, by the backfill reading rows
    # an older version classified.
    if result.discovery_agent_id is not None and hardware.tenant_id != result.tenant_id:
        return None
    return hardware


def enrich_matched_result(db: Session, result: ScanResult) -> EnrichmentOutcome:
    """Backfill empty fields on the Hardware row a matched result already points at.

    No-commit — the caller owns the transaction and commits, or rolls its
    savepoint back. Never creates a `Hardware` row, never overwrites a value that
    is already set, and never writes `Hardware.name`.

    Callers that want the audit trail call `log_enrichment` *after* their commit:
    `write_log` opens and commits its own work, which must not happen inside
    someone else's savepoint.
    """
    hardware = _is_candidate(db, result)
    if hardware is None:
        return EnrichmentOutcome(enriched=False)

    ctx = _Ctx(db=db, result=result, hardware=hardware)
    filled: list[dict[str, str]] = []

    for attr, extract in _FIELD_RULES:
        if getattr(hardware, attr, None):
            continue  # already answered — backfill only, never overwrite
        value = extract(ctx)
        if not value:
            continue
        setattr(hardware, attr, value)
        filled.append({"field": attr, "value": value})

    # Provenance: which finding last taught us something about this device.
    # Outside the rule table because it is an id rather than a user-visible
    # value, and `merge_scan_result` sets it on accept for the same reason.
    hardware.source_scan_result_id = result.id

    # Liveness, always. Every other observer in the product — the ARP prober,
    # the listener, the monitor engine, `merge_scan_result` — already writes
    # these from any source, and they are not answers anyone typed.
    now = utcnow_iso()
    hardware.last_seen = now
    hardware.status = "online"

    result.merge_status = ENRICHED_MERGE_STATUS
    result.enriched_fields_json = filled
    result.enriched_at = now
    # `reviewed_by` / `reviewed_at` are deliberately left alone: they mean a
    # human reviewed this row, and no human did.

    return EnrichmentOutcome(
        enriched=True,
        hardware_id=hardware.id,
        hardware_name=hardware.name,
        fields=filled,
    )


def log_enrichment(db: Session, result: ScanResult, outcome: EnrichmentOutcome) -> None:
    """Audit an enrichment that actually filled something. Call after commit.

    Conditional on purpose. Every other discovery state transition writes an
    audit row, and an operator asking "who filled in my device's MAC?" has to be
    able to find the answer — but a six-hourly sweep of a stable /24 would
    otherwise write 254 rows a pass saying nothing changed. So a bare liveness
    refresh is silent, and the first pass that learns something is not.

    Field *names* go in `details`, not values: the names are what makes the
    entry answerable, and the values are already on the row.
    """
    if not outcome.enriched or not outcome.fields:
        return
    write_log(
        db,
        action=AUDIT_ACTION,
        entity_type="hardware",
        entity_id=outcome.hardware_id,
        entity_name=outcome.hardware_name or "",
        category="discovery",
        actor=(
            f"agent:{result.discovery_agent_id}"
            if result.discovery_agent_id is not None
            else "system"
        ),
        details=json.dumps(
            {
                "scan_result_id": result.id,
                "ip": result.ip_address,
                "fields": [f["field"] for f in outcome.fields],
                "discovery_agent_id": result.discovery_agent_id,
            }
        ),
    )


def backfill_pending_matched(db: Session, *, batch_limit: int = 1000) -> int:
    """Repair the existing queue at startup, including stale `new` findings.

    Preserve observations as history, consolidate pending duplicates, and
    re-match hosts that entered inventory after their original scan. Keyset
    pagination visits the whole queue even when unknown hosts remain pending.
    Returns the number enriched; owns commits and post-commit audit logging.
    """
    from app.services import discovery_result_service as results

    if batch_limit < 1:
        raise ValueError("batch_limit must be positive")
    last_id = 0
    enriched = 0
    while True:
        rows = list(
            db.scalars(
                select(ScanResult)
                .where(ScanResult.id > last_id, ScanResult.merge_status == "pending")
                .order_by(ScanResult.id)
                .limit(batch_limit)
            )
        )
        if not rows:
            return enriched
        last_id = rows[-1].id
        for tenant in sorted({row.tenant_id or 0 for row in rows}):
            results.lock_review_queue(db, tenant)
        outcomes: list[tuple[ScanResult, EnrichmentOutcome]] = []
        for row in rows:
            # An accept/ingest may have completed while the lock was awaited.
            db.refresh(row)
            if row.merge_status != "pending" or row.source_type in _SKIPPED_SOURCE_TYPES:
                continue
            row.ip_address = results.normalize_ip(row.ip_address) or row.ip_address
            row.mac_address = results.normalize_mac(row.mac_address)
            if row.state == "new":
                results.classify_result(db, row)
            results.deduplicate_pending_result(db, row)
            outcome = enrich_matched_result(db, row)
            if outcome.enriched:
                outcomes.append((row, outcome))
            db.flush()
        db.commit()
        for row, outcome in outcomes:
            log_enrichment(db, row, outcome)
        enriched += len(outcomes)
