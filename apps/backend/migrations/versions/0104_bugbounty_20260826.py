"""Audit-chain checkpoint, listener dedup index, and the double-encoded properties repair.

Revision ID: 0104_bugbounty_20260826
Revises: 7d2e4a81c6f3
Create Date: 2026-08-26

One revision for three findings from the 2026-08-26 bug bounty, deliberately
not three. The agents that produced the fixes were forbidden from writing
Alembic revisions precisely so this would chain from one head rather than
opening three.

B14 — `app_settings.audit_chain_checkpoint_hash`.
    The audit-log retention purge deletes the chain genesis, after which
    verify-chain reports tampering on every install past the retention window.
    The purge now records the hash of the last row it removed, so verification
    can start from that checkpoint instead of from a row that no longer exists.
    This column is NOT optional in the way a nullable column usually is:
    `settings_service.get_or_create_settings` issues a full-entity
    `db.get(AppSettings, 1)` and has call sites throughout the request path,
    including `core/security.py` reading `jwt_secret`. A deployment running the
    new code against a schema without this column does not degrade — every one
    of those reads raises `UndefinedColumn` and the process is unusable. That
    is the reason this revision exists at all.

B13 — `ix_listener_events_dedup`.
    `listener_service._persist_event` probes for a recent duplicate on
    (ip_address, service_type, seen_at) once per multicast packet that clears
    the rate gate. `listener_events` is the one discovery table fed directly by
    unauthenticated LAN traffic, so without a composite index that probe is a
    scan of every retained row per advertisement. Created CONCURRENTLY is
    deliberately NOT used: this runs inside Alembic's transaction, and the
    table is small enough on any real install that a brief lock is cheaper than
    the operational complexity of a non-transactional migration.

B34 — the double-encoded `properties_json` repair.
    The listener wrote `json.dumps(properties)` into a JSONB column, so
    Postgres stored a JSON *scalar string* where an object belongs and every
    reader got a quoted blob back — `properties_json ->> 'nt'` was NULL for
    every captured advertisement. The writer is fixed; the rows already written
    are repaired here.

    The obvious repair is wrong and was caught in review:

        UPDATE listener_events
           SET properties_json = (properties_json #>> '{}')::jsonb
         WHERE jsonb_typeof(properties_json) = 'string';

    `#>> '{}'` extracts a jsonb scalar as *text*, and Postgres refuses to
    convert a JSON string containing an escaped NUL (`\\u0000`) to text:
    `ERROR: unsupported Unicode escape sequence ... cannot be converted to
    text`. Those rows are not hypothetical — they are exactly what the buggy
    writer produced from any SSDP header or mDNS TXT record carrying a NUL,
    because `json.dumps` escaped the NUL that the column itself cannot hold.
    A single failing row aborts the whole statement, and with it this whole
    revision, on precisely the installs that most need the repair.

    So the escape is stripped before the conversion, and the work is done
    row-at-a-time inside an exception handler: anything that still will not
    convert is counted and left exactly as it was rather than taking the
    upgrade down. A row left behind is a row that reads the way it did
    yesterday, which is a bad row but not a failed upgrade.

All three steps are idempotent, so a re-run after a partial failure is safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0104_bugbounty_20260826"
down_revision = "7d2e4a81c6f3"
branch_labels = None
depends_on = None

_SETTINGS_TABLE = "app_settings"
_CHECKPOINT_COLUMN = "audit_chain_checkpoint_hash"
_LISTENER_TABLE = "listener_events"
_DEDUP_INDEX = "ix_listener_events_dedup"


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa_inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(bind: sa.engine.Connection, table: str, index: str) -> bool:
    inspector = sa_inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa_inspect(bind).get_table_names()


# Row-at-a-time so one unconvertible value cannot abort the upgrade.
#
# `properties_json::text` renders the stored scalar as a JSON *string literal*,
# so every backslash the writer produced comes back doubled: a NUL that
# `json.dumps` wrote as `\u0000` renders here as `\\u0000`. That is why the
# doubled form is stripped first and the single form second — matching only the
# single form would eat the tail of the doubled one and leave a stray backslash
# behind, which then fails to parse and silently costs the row its repair.
# Verified against pg16 on all four shapes: a clean double-encoded object, a
# NUL-bearing one, an already-correct object, and a scalar that is not an object.
#
# Re-parsing the stripped rendering as jsonb gives the same scalar string minus
# the NUL; `#>> '{}'` then yields the text the writer originally serialised, and
# the final cast parses it into the object it always should have been.
#
# The guard on `LIKE '{%'` keeps the cast away from anything that is not an
# object literal. The writer only ever dumped a dict, but a hand-edited row or a
# future writer should be skipped rather than trusted.
_REPAIR_PROPERTIES = sa.text(
    """
DO $$
DECLARE
    r            RECORD;
    unescaped    text;
    repaired     integer := 0;
    skipped      integer := 0;
BEGIN
    FOR r IN
        SELECT id, properties_json
          FROM listener_events
         WHERE jsonb_typeof(properties_json) = 'string'
    LOOP
        BEGIN
            unescaped := (
                replace(
                    replace(r.properties_json::text, '\\\\u0000', ''),
                    '\\u0000', ''
                )::jsonb #>> '{}'
            );

            IF unescaped IS NULL OR left(ltrim(unescaped), 1) <> '{' THEN
                skipped := skipped + 1;
                CONTINUE;
            END IF;

            UPDATE listener_events
               SET properties_json = unescaped::jsonb
             WHERE id = r.id;

            repaired := repaired + 1;
        EXCEPTION WHEN others THEN
            -- Leave the row exactly as it was. It reads the way it did before
            -- this revision, which is wrong but not worse, and the upgrade
            -- continues.
            skipped := skipped + 1;
        END;
    END LOOP;

    RAISE NOTICE 'listener_events properties_json: % repaired, % left as-is',
                 repaired, skipped;
END
$$;
"""
)


def upgrade() -> None:
    bind = op.get_bind()

    # B14 — the checkpoint the retention purge writes and verify-chain reads.
    if not _has_column(bind, _SETTINGS_TABLE, _CHECKPOINT_COLUMN):
        op.add_column(
            _SETTINGS_TABLE,
            sa.Column(_CHECKPOINT_COLUMN, sa.String(), nullable=True),
        )

    # B13 — the dedup probe's index.
    if _has_table(bind, _LISTENER_TABLE) and not _has_index(bind, _LISTENER_TABLE, _DEDUP_INDEX):
        op.create_index(
            _DEDUP_INDEX,
            _LISTENER_TABLE,
            ["ip_address", "service_type", "seen_at"],
        )

    # B34 — repair what the double-encoding writer already stored.
    if _has_table(bind, _LISTENER_TABLE):
        bind.execute(_REPAIR_PROPERTIES)


def downgrade() -> None:
    bind = op.get_bind()

    # The B34 data repair is deliberately not reversed. Re-encoding a correct
    # JSON object back into a scalar string would be restoring a defect, and
    # the new reader handles both shapes on the way in, so a downgraded install
    # reads repaired rows correctly.
    if _has_table(bind, _LISTENER_TABLE) and _has_index(bind, _LISTENER_TABLE, _DEDUP_INDEX):
        op.drop_index(_DEDUP_INDEX, table_name=_LISTENER_TABLE)

    if _has_column(bind, _SETTINGS_TABLE, _CHECKPOINT_COLUMN):
        op.drop_column(_SETTINGS_TABLE, _CHECKPOINT_COLUMN)
