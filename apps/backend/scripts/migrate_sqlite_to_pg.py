#!/usr/bin/env python3
"""One-time SQLite → PostgreSQL data migration script.

Copies all rows from a SQLite database into a PostgreSQL database that has
already had Alembic migrations applied (i.e. the schema exists in PG).

Usage:
    python migrate_sqlite_to_pg.py \\
        --from sqlite:////app/data/app.db \\
        --to postgresql://breaker:breaker@localhost:5432/circuitbreaker

Requirements:
    pip install sqlalchemy psycopg2-binary

Notes:
  - Run AFTER `alembic upgrade head` on the PG target so all tables exist.
  - Foreign key enforcement is temporarily disabled during the copy so rows
    can be inserted in any order.
  - The `alembic_version` table is excluded — do not overwrite the PG stamp.
  - Source rows are read in LIMIT/OFFSET batches to cap memory use.
  - INSERT uses ON CONFLICT (primary key or first unique index) DO NOTHING;
    tables with no such constraint on PostgreSQL are skipped with a log line.
  - Re-running is safe when a PK/unique exists: duplicate rows are skipped.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.schema import MetaData, Table

BATCH_READ = 2_000
INSERT_CHUNK = 500
SKIP_TABLES = {"alembic_version"}


def _conflict_columns(dst_insp: Any, table: str) -> list[str] | None:
    pk = dst_insp.get_pk_constraint(table)
    cols = pk.get("constrained_columns") if pk else None
    if cols:
        return list(cols)
    for idx in dst_insp.get_indexes(table):
        if idx.get("unique") and idx.get("column_names"):
            return list(idx["column_names"])
    return None


def migrate(src_url: str, dst_url: str, dry_run: bool = False) -> None:
    print(f"Source: {src_url}")
    print(f"Target: {dst_url}")
    if dry_run:
        print("[DRY RUN] No data will be written.\n")

    src_engine = create_engine(src_url, connect_args={"check_same_thread": False})
    dst_engine = create_engine(dst_url, pool_pre_ping=True)
    dst_meta = MetaData()

    insp = inspect(src_engine)
    tables = [t for t in insp.get_table_names() if t not in SKIP_TABLES]
    print(f"Tables to migrate: {len(tables)}\n")

    totals: dict[str, tuple[int, int]] = {}
    dst_insp = inspect(dst_engine)
    dst_tables = set(dst_insp.get_table_names())

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        if not dry_run:
            dst_conn.execute(text("SET session_replication_role = replica"))

        for table in tables:
            if table not in dst_tables:
                print(f"  {table}: skipped — not present on PostgreSQL target")
                totals[table] = (0, 0)
                continue

            conflict_cols = _conflict_columns(dst_insp, table)
            if not conflict_cols:
                print(
                    f"  {table}: skipped — no PK or UNIQUE on target "
                    f"(required for ON CONFLICT DO NOTHING)"
                )
                totals[table] = (0, 0)
                continue

            try:
                pg_table = Table(table, dst_meta, autoload_with=dst_engine)
            except Exception as exc:
                print(f"  {table}: skipped — reflect failed ({exc})")
                totals[table] = (0, 0)
                continue

            copied = 0
            skipped = 0
            offset = 0
            while True:
                batch_rows = (
                    src_conn.execute(
                        text(f'SELECT * FROM "{table}" LIMIT :lim OFFSET :off'),
                        {"lim": BATCH_READ, "off": offset},
                    )
                    .mappings()
                    .all()
                )
                if not batch_rows:
                    break
                offset += len(batch_rows)

                valid_cols = {c.key for c in pg_table.columns}
                for i in range(0, len(batch_rows), INSERT_CHUNK):
                    chunk = [
                        {k: v for k, v in dict(r).items() if k in valid_cols}
                        for r in batch_rows[i : i + INSERT_CHUNK]
                    ]
                    if dry_run:
                        copied += len(chunk)
                        continue
                    stmt = pg_insert(pg_table).on_conflict_do_nothing(index_elements=conflict_cols)
                    result = dst_conn.execute(stmt, chunk)
                    ins = len(chunk)
                    rc = result.rowcount
                    if rc is not None and rc >= 0:
                        copied += rc
                        skipped += ins - rc
                    else:
                        copied += ins

            skip_note = f" ({skipped} skipped — already existed)" if skipped else ""
            label = "rows counted" if dry_run else "rows copied"
            print(f"  {table}: {copied} {label}{skip_note}")
            totals[table] = (copied, skipped)

        if not dry_run:
            dst_conn.execute(text("SET session_replication_role = DEFAULT"))
            dst_conn.execute(text("VACUUM ANALYZE"))
            dst_conn.commit()

    print("\nMigration complete.")
    total_rows = sum(c for c, _ in totals.values())
    total_skip = sum(s for _, s in totals.values())
    print(f"  Total rows copied : {total_rows}")
    print(f"  Total rows skipped: {total_skip}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate CircuitBreaker data from SQLite to PostgreSQL"
    )
    parser.add_argument(
        "--from", dest="src", required=True, help="SQLite URL (sqlite:////path/to/app.db)"
    )
    parser.add_argument("--to", dest="dst", required=True, help="PostgreSQL URL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count rows without writing anything"
    )
    args = parser.parse_args()

    if not args.src.startswith("sqlite"):
        print("ERROR: --from must be a sqlite:// URL", file=sys.stderr)
        sys.exit(1)
    if not args.dst.startswith("postgresql"):
        print("ERROR: --to must be a postgresql:// URL", file=sys.stderr)
        sys.exit(1)

    migrate(args.src, args.dst, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
