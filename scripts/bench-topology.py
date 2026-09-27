#!/usr/bin/env python3
"""Benchmark the topology graph builder at various dataset sizes.

Usage:
    CB_DB_URL=postgresql://breaker:pass@localhost:5432/circuitbreaker \
      python scripts/bench-topology.py [--sizes 100,1000,5000,10000] [--iterations 5]

Measures:
- build_topology_graph() wall-clock time
- Per-entity-type query counts (via SQLAlchemy event listeners)

Asserts each call completes in <50ms at homelab scale (<=10k nodes).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "backend", "src"))

os.environ.setdefault(
    "CB_DB_URL",
    "postgresql://breaker:breaker@127.0.0.1:5432/circuitbreaker",
)


def _parse_args():
    p = argparse.ArgumentParser(description="Topology graph benchmark")
    p.add_argument(
        "--sizes",
        default="100,1000,5000,10000",
        help="Comma-separated node counts to test (default: 100,1000,5000,10000)",
    )
    p.add_argument("--iterations", type=int, default=5, help="Iterations per size")
    p.add_argument(
        "--threshold-ms", type=float, default=50.0, help="Max allowed ms per call"
    )
    return p.parse_args()


@contextmanager
def _query_counter(engine):
    """Count SQL statements emitted during a block."""
    from sqlalchemy import event

    count = {"n": 0}

    def _before_execute(conn, clauseelement, multiparams, params, execution_options):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", _before_execute)
    try:
        yield count
    finally:
        event.remove(engine, "before_cursor_execute", _before_execute)


def _seed_hardware(db, n: int):
    """Insert n hardware rows (idempotent; skips if already present)."""
    from app.db.models import Hardware

    existing = db.query(Hardware).count()
    if existing >= n:
        return
    to_add = n - existing
    for i in range(to_add):
        db.add(
            Hardware(
                name=f"bench-hw-{existing + i + 1}",
                ip_address=f"10.{(existing + i) // 65536 % 256}.{(existing + i) // 256 % 256}.{(existing + i) % 256}",
                role="server",
                status="up",
                tenant_id=1,
            )
        )
    db.commit()
    print(f"  Seeded {to_add} hardware rows (total {n})")


def _cleanup_bench(db):
    """Remove benchmark-seeded rows."""
    from app.db.models import Hardware

    db.query(Hardware).filter(Hardware.name.like("bench-hw-%")).delete(
        synchronize_session="fetch"
    )
    db.commit()


def main():
    args = _parse_args()
    sizes = [int(s.strip()) for s in args.sizes.split(",")]

    from app.db.session import SessionLocal, engine

    results = []

    for size in sizes:
        db = SessionLocal()
        try:
            _seed_hardware(db, size)
            db.close()

            timings = []
            query_counts = []
            for _ in range(args.iterations):
                db = SessionLocal()
                with _query_counter(engine) as counter:
                    t0 = time.perf_counter()
                    from app.api.graph import build_topology_graph

                    build_topology_graph(db=db)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                timings.append(elapsed_ms)
                query_counts.append(counter["n"])
                db.close()

            avg_ms = sum(timings) / len(timings)
            avg_queries = sum(query_counts) / len(query_counts)
            p99 = sorted(timings)[int(len(timings) * 0.99)]
            results.append((size, avg_ms, p99, avg_queries))

            status = "PASS" if avg_ms < args.threshold_ms else "FAIL"
            print(
                f"  [{status}] {size:>6} nodes: avg={avg_ms:7.2f}ms  "
                f"p99={p99:7.2f}ms  queries={avg_queries:.0f}"
            )
        finally:
            db = SessionLocal()
            _cleanup_bench(db)
            db.close()

    print("\n--- Summary ---")
    print(f"{'Nodes':>8}  {'Avg(ms)':>10}  {'P99(ms)':>10}  {'Queries':>8}")
    for size, avg_ms, p99, avg_q in results:
        print(f"{size:>8}  {avg_ms:>10.2f}  {p99:>10.2f}  {avg_q:>8.0f}")

    failures = [r for r in results if r[1] >= args.threshold_ms]
    if failures:
        print(f"\nWARNING: {len(failures)} size(s) exceeded {args.threshold_ms}ms threshold")
        sys.exit(1)
    else:
        print(f"\nAll sizes under {args.threshold_ms}ms threshold")


if __name__ == "__main__":
    main()
