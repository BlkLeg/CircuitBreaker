"""Discovery enrichment: changed-field record, canonical MACs, and the missing indexes.

Revision ID: 0109_discovery_enrichment
Revises: b3d7c1e05a44
Create Date: 2026-09-06

Supports `services/discovery_enrich.py`, which backfills empty fields on a device
a scan re-found instead of queueing it for review a second time. Three pieces:

1. `scan_results.enriched_fields_json` / `enriched_at` — what enrichment filled,
   so the review queue can show it without joining the audit log.

2. **Canonicalising `mac_address` before the index exists.** `discovery_enrich`
   and `discovery_result_service` both normalize their *lookup input* to the
   uppercase-colon form `_norm_mac` produces. That is only correct if the stored
   column is in the same form, and it is not: `discovery_merge._auto_merge_result`
   has always written the reporter's string through un-normalized, and both the
   Go agent's neighbour cache and OPNsense report lowercase. Uppercasing one side
   only would make the matcher newly *miss* those rows — turning known devices
   back into review-queue duplicates, which is the bug this whole change exists
   to fix. So the column is canonicalised here, in the same migration.

3. The indexes. `hardware.ip_address` and `hardware.mac_address` had none, so
   every classification was a sequential scan, and enrichment adds a third lookup
   per finding. `scan_results.merge_status` had none either, though `state` did —
   and `merge_status` is what the review badge, the queue fetch and the
   enrichment backfill's selector all filter on.

Every statement is existence-guarded: a self-hoster upgrades on their own
schedule and a half-updated deployment must still work (CLAUDE.md).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0109_discovery_enrichment"
down_revision: str | None = "b3d7c1e05a44"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the enrichment columns, canonicalise MACs, then index."""
    bind = op.get_bind()

    # ── 1. The changed-field record ──────────────────────────────────────────
    # VARCHAR rather than TIMESTAMPTZ for `enriched_at`, matching this table's
    # existing `created_at` / `reviewed_at`, which are ISO strings.
    bind.execute(
        sa.text("ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS enriched_fields_json JSONB")
    )
    bind.execute(sa.text("ALTER TABLE scan_results ADD COLUMN IF NOT EXISTS enriched_at VARCHAR"))

    # ── 2. Canonicalise stored MACs — must precede the index ─────────────────
    # Uppercase-colon wins by weight of data: `_norm_mac`, nmap and
    # `merge_scan_result` all produce it, and it is what the matcher now looks
    # up. `upper()` alone is enough here — re-punctuating a stored value would
    # be a data rewrite this migration has no business doing, and `_norm_mac`
    # leaves an already-colon-separated address's punctuation untouched anyway.
    bind.execute(
        sa.text(
            "UPDATE hardware SET mac_address = upper(mac_address) "
            "WHERE mac_address IS NOT NULL AND mac_address <> upper(mac_address)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE scan_results SET mac_address = upper(mac_address) "
            "WHERE mac_address IS NOT NULL AND mac_address <> upper(mac_address)"
        )
    )

    # ── 3. The three missing indexes ─────────────────────────────────────────
    # Plain btree, deliberately NOT unique. Duplicate MACs and IPs exist in the
    # wild — multi-NIC hosts, NAT, placeholder rows — and `hardware_service`
    # explicitly tolerates them ("Saving both (freeform-first)"), so a unique
    # index would fail the upgrade on a live install. Not CONCURRENTLY either:
    # Alembic runs inside a transaction, and these tables are homelab-sized.
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_hardware_mac_address ON hardware (mac_address)")
    )
    bind.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_hardware_ip_address ON hardware (ip_address)")
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_scan_results_merge_status ON scan_results (merge_status)"
        )
    )


def downgrade() -> None:
    """Drop the indexes and columns. The MAC canonicalisation is not reversed —
    there is no record of the prior casing, and uppercase is a valid MAC."""
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_scan_results_merge_status"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_hardware_ip_address"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_hardware_mac_address"))
    bind.execute(sa.text("ALTER TABLE scan_results DROP COLUMN IF EXISTS enriched_at"))
    bind.execute(sa.text("ALTER TABLE scan_results DROP COLUMN IF EXISTS enriched_fields_json"))
