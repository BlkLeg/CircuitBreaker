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
  - Rows are copied in batches of 500 to avoid memory issues on large tables.
  - Re-running is safe: any unique-constraint conflicts on existing rows are
    skipped and reported.
"""

import argparse
import sys
from typing import Any

from sqlalchemy import create_engine, inspect, text

BATCH_SIZE = 500
SKIP_TABLES = {"alembic_version"}


def migrate(src_url: str, dst_url: str, dry_run: bool = False) -> None:
    print(f"Source: {src_url}")
    print(f"Target: {dst_url}")
    if dry_run:
        print("[DRY RUN] No data will be written.\n")

    src_engine = create_engine(src_url, connect_args={"check_same_thread": False})
    dst_engine = create_engine(dst_url, pool_pre_ping=True)

    insp = inspect(src_engine)
    tables = [t for t in insp.get_table_names() if t not in SKIP_TABLES]
    print(f"Tables to migrate: {len(tables)}\n")

    totals: dict[str, tuple[int, int]] = {}  # table -> (copied, skipped)

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        # Disable FK enforcement on PG for the duration of the copy
        if not dry_run:
            dst_conn.execute(text("SET session_replication_role = replica"))

        for table in tables:
            rows = src_conn.execute(text(f"SELECT * FROM {table}")).mappings().all()  # noqa: S608
            if not rows:
                print(f"  {table}: 0 rows (empty, skipping)")
                totals[table] = (0, 0)
                continue

            cols = list(rows[0].keys())
            copied = 0
            skipped = 0

            for i in range(0, len(rows), BATCH_SIZE):
                batch: list[dict[str, Any]] = [dict(r) for r in rows[i : i + BATCH_SIZE]]
                if dry_run:
                    copied += len(batch)
                    continue
                # Build a parameterised INSERT … ON CONFLICT DO NOTHING so re-runs are safe
                col_list = ", ".join(f'"{c}"' for c in cols)
                param_list = ", ".join(f":{c}" for c in cols)
                stmt = text(
                    f'INSERT INTO "{table}" ({col_list}) '
                    f"VALUES ({param_list}) ON CONFLICT DO NOTHING"  # noqa: S608
                )
                result = dst_conn.execute(stmt, batch)
                copied += result.rowcount
                skipped += len(batch) - result.rowcount

            totals[table] = (copied, skipped)
            skip_note = f" ({skipped} skipped — already existed)" if skipped else ""
            print(f"  {table}: {copied} rows copied{skip_note}")

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
