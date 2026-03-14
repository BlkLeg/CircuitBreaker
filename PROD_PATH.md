# Circuit Breaker — Production Scaling Path

**Target Scale:** 10,000+ devices per tenant, 100+ concurrent tenants, sub-second real-time updates  
**Current State:** Single-tenant homelab platform (500 devices tested, ~500MB RAM)  
**Timeline:** 18–24 months across 7 phases

---

## Executive Summary

Circuit Breaker's current architecture is optimized for single-tenant homelab environments with <1,000 devices. To scale to enterprise production with multi-tenancy and real-time updates for thousands of devices, four critical subsystems require complete reimplementation:

1. **Map Engine** — Replace ReactFlow with WebGL rendering, add graph virtualization
2. **Telemetry Engine** — Migrate to TimescaleDB, implement parallel polling, add streaming aggregation
3. **Auth & Tenant System** — Enforce multi-tenancy with database-level isolation, RBAC per tenant
4. **Database Layer** — Add read replicas, implement tenant partitioning, optimize for time-series workloads

This document outlines a phased approach that maintains backward compatibility while incrementally building enterprise-grade infrastructure.

---

## Current Limitations at Scale

### Map/Topology Engine

| Limitation | Impact at 10,000 Devices |
|------------|--------------------------|
| ReactFlow rendering | 5–10 second initial load, janky panning/zoom |
| No virtualization | All 10,000 nodes rendered simultaneously (DOM exhaustion) |
| `MapPage.jsx` 2,897 LOC | Large monolithic component, difficult to refactor safely |
| Edge routing on every drag | 500+ edges recalculate anchors on node move (UI freeze) |
| No clustering/grouping | Cannot collapse subnets, racks, or clusters visually |
| SQLAlchemy N+1 queries | Fetching 10,000 entities + relationships = 20,000+ queries |

**Bottleneck:** DOM-based rendering (ReactFlow) cannot handle 1,000+ nodes efficiently. Needs canvas/WebGL.

---

### Telemetry Engine

| Limitation | Impact at 10,000 Devices |
|------------|--------------------------|
| Sequential polling | 10,000 devices × 2-second timeout = 5.5 hours per cycle |
| PostgreSQL standard tables | Time-series queries (30-day history) scan millions of rows |
| No downsampling | Full-resolution metrics retained forever (disk bloat) |
| Redis cache not clustered | Single Redis instance bottleneck for 100+ tenants |
| No streaming aggregation | Real-time dashboards query DB on every refresh |

**Bottleneck:** Sequential polling and lack of time-series optimization. Needs parallel workers + TimescaleDB.

---

### Auth & Tenant System

| Limitation | Impact at 100+ Tenants |
|------------|------------------------|
| RLS policies not enforced | Tenants can see each other's data (security risk) |
| Single JWT secret | Compromised secret affects all tenants |
| No tenant-scoped rate limiting | One tenant can exhaust API for others |
| No resource quotas | Tenant with 50,000 devices degrades platform for all |
| Session store in PostgreSQL | Slow session lookups at 10,000+ concurrent users |

**Bottleneck:** No tenant isolation. Needs multi-tenant architecture with dedicated schemas and resource quotas.

---

### Database Layer

| Limitation | Impact at 10M+ Rows |
|------------|---------------------|
| Single PostgreSQL instance | No read scaling, write bottleneck |
| No query caching | Entity lists hit DB every time (10,000 entities = 500ms query) |
| No tenant partitioning | All tenants share same tables (slow queries, no data isolation) |
| pgbouncer transaction mode | Cannot use prepared statements (performance loss) |
| No time-series optimization | Telemetry queries scan full table (30-day history = 50M rows) |

**Bottleneck:** Single database instance with no read replicas or partitioning. Needs PostgreSQL clustering + TimescaleDB.

---

## Phase 1: Foundation & Observability (3 months)

**Goal:** Establish monitoring, profiling, and caching infrastructure to measure scaling improvements.

### 1.1 Distributed Tracing (OpenTelemetry)

**Why:** Identify slow queries, N+1 problems, and bottlenecks before scaling.

**Implementation:**
```python
# apps/backend/src/app/core/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

def init_tracing(app):
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4317"))
    )
    trace.set_tracer_provider(provider)
    
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine)
```

**New Services:**
- **Jaeger** (or Tempo) for trace storage and visualization
- **Grafana** dashboards for span analysis

**Metrics to Track:**
- API endpoint latency (p50, p95, p99)
- Database query duration
- Redis cache hit rate
- WebSocket message throughput

---

### 1.2 Query Optimization & Caching

**Why:** Eliminate N+1 queries and cache immutable entity data.

**Implementation:**

**Eager Loading (SQLAlchemy):**
```python
# apps/backend/src/app/services/graph_service.py
def get_full_topology(db: Session, tenant_id: int):
    # Before (N+1 queries)
    entities = db.query(Entity).filter_by(tenant_id=tenant_id).all()
    for entity in entities:
        _ = entity.relationships  # Lazy load (1 query per entity)
    
    # After (2 queries total)
    entities = (
        db.query(Entity)
        .filter_by(tenant_id=tenant_id)
        .options(
            selectinload(Entity.relationships),
            selectinload(Entity.telemetry_snapshots)
        )
        .all()
    )
```

**Redis Entity Cache:**
```python
# apps/backend/src/app/services/cache_service.py
import hashlib
import json
from typing import Any
from redis import Redis

class EntityCache:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.ttl = 300  # 5 minutes
    
    def get_topology(self, tenant_id: int) -> dict | None:
        key = f"topology:{tenant_id}"
        data = self.redis.get(key)
        return json.loads(data) if data else None
    
    def set_topology(self, tenant_id: int, data: dict):
        key = f"topology:{tenant_id}"
        self.redis.setex(key, self.ttl, json.dumps(data))
    
    def invalidate_topology(self, tenant_id: int):
        key = f"topology:{tenant_id}"
        self.redis.delete(key)
```

**Cache Invalidation via NATS Events:**
```python
# apps/backend/src/app/api/graph.py
@router.patch("/{entity_id}")
async def update_entity(entity_id: int, payload: EntityUpdate, db: Session, nats: NATSClient):
    entity = entity_service.update(db, entity_id, payload)
    
    # Invalidate cache for this tenant
    cache_service.invalidate_topology(entity.tenant_id)
    
    # Broadcast to all WebSocket clients
    await nats.publish(
        subject=f"topology.updated.{entity.tenant_id}",
        payload={"entity_id": entity_id, "action": "update"}
    )
```

**Expected Impact:**
- API response time: 500ms → 50ms (10x faster)
- Database load: -80% for read queries
- Cache hit rate: >90% for topology reads

---

### 1.3 PostgreSQL Read Replicas

**Why:** Offload read queries (topology, telemetry history) to replicas.

**Architecture:**
```
┌─────────────────┐
│   Application   │
│   (FastAPI)     │
└────┬───────┬────┘
     │       │
     │       └──────────────┐ Read Queries
     │                      │ (topology, telemetry)
     │ Write Queries        │
     │ (entity CRUD)        │
     ▼                      ▼
┌────────────┐      ┌──────────────┐
│ PostgreSQL │─────▶│  Replica 1   │
│  Primary   │      │  (read-only) │
│ (read/write)│─────▶│  Replica 2   │
└────────────┘      └──────────────┘
     │
     │ Streaming Replication
     │ (WAL logs)
```

**SQLAlchemy Multi-Database Setup:**
```python
# apps/backend/src/app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Primary (write) engine
engine_primary = create_engine(settings.CB_DB_URL_PRIMARY, pool_size=20)

# Replica (read) engines
engine_replica_1 = create_engine(settings.CB_DB_URL_REPLICA_1, pool_size=10)
engine_replica_2 = create_engine(settings.CB_DB_URL_REPLICA_2, pool_size=10)

# Round-robin replica selection
replica_engines = [engine_replica_1, engine_replica_2]
replica_index = 0

def get_read_engine():
    global replica_index
    engine = replica_engines[replica_index % len(replica_engines)]
    replica_index += 1
    return engine

def get_db_write():
    """For writes (entity CRUD, settings)."""
    session = sessionmaker(bind=engine_primary)()
    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

def get_db_read():
    """For reads (topology, telemetry history)."""
    session = sessionmaker(bind=get_read_engine())()
    try:
        yield session
    finally:
        session.close()
```

**Usage in Routes:**
```python
# apps/backend/src/app/api/graph.py
@router.get("/topology")
def get_topology(db: Session = Depends(get_db_read)):  # Read from replica
    return graph_service.get_full_topology(db, tenant_id)

@router.post("/entities")
def create_entity(payload: EntityCreate, db: Session = Depends(get_db_write)):  # Write to primary
    return entity_service.create(db, payload)
```

**Expected Impact:**
- Primary database load: -60% (reads offloaded to replicas)
- Read query latency: unchanged (replicas have same data within 1–2 seconds)
- Write availability: unchanged (primary still single point of failure until Phase 5)

---

### 1.4 Metrics & Dashboards

**Prometheus Metrics (Enhanced):**
```python
# apps/backend/src/app/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Existing metrics + new ones
db_query_duration = Histogram(
    "cb_db_query_duration_seconds",
    "Database query duration",
    ["operation", "table", "tenant_id"]
)

cache_operations = Counter(
    "cb_cache_operations_total",
    "Redis cache operations",
    ["operation", "result"]  # operation=get/set, result=hit/miss
)

websocket_connections = Gauge(
    "cb_websocket_connections",
    "Active WebSocket connections",
    ["tenant_id", "stream"]
)

tenant_entity_count = Gauge(
    "cb_tenant_entity_count",
    "Number of entities per tenant",
    ["tenant_id"]
)
```

**Grafana Dashboards:**
1. **API Performance** — Request rate, latency (p50/p95/p99), error rate
2. **Database Health** — Query duration, connection pool usage, replication lag
3. **Cache Efficiency** — Hit rate, eviction rate, memory usage
4. **Tenant Metrics** — Entity count, active users, API usage per tenant

**New Stack Components:**
- **Prometheus** — Metrics scraping and storage
- **Grafana** — Visualization and alerting
- **Loki** — Log aggregation (replaces file-based logs)

**Deployment (docker-compose):**
```yaml
services:
  prometheus:
    image: prom/prometheus:v2.45.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana:10.0.0
    volumes:
      - grafana-data:/var/lib/grafana
    ports:
      - "3000:3000"
  
  loki:
    image: grafana/loki:2.9.0
    volumes:
      - loki-data:/loki
    ports:
      - "3100:3100"
  
  jaeger:
    image: jaegertracing/all-in-one:1.50
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP gRPC
```

**Phase 1 Deliverables:**
- ✅ OpenTelemetry tracing for all API routes and database queries
- ✅ Redis caching for topology and entity lists (5-min TTL)
- ✅ PostgreSQL read replicas (2 replicas) with round-robin routing
- ✅ Prometheus + Grafana dashboards for API, DB, cache metrics
- ✅ Jaeger tracing UI for identifying N+1 queries

**Success Metrics:**
- API p95 latency: <100ms (from 500ms)
- Cache hit rate: >90%
- Database read load on primary: -60%
- Full topology render for 1,000 entities: <2 seconds (from 5 seconds)

---

## Phase 2: Telemetry Engine Overhaul (4 months)

**Goal:** Migrate to TimescaleDB for time-series data, implement parallel polling, add streaming aggregation.

### 2.1 TimescaleDB Migration

**Why:** PostgreSQL standard tables are inefficient for time-series queries (30-day history scans 50M+ rows).

**TimescaleDB Benefits:**
- **Automatic partitioning** — Data split into chunks (default: 7 days per chunk)
- **Compression** — 10x storage reduction for historical data
- **Continuous aggregates** — Pre-computed rollups (1-min → 1-hour → 1-day)
- **Retention policies** — Auto-delete old data (e.g., raw metrics after 90 days)

**Implementation:**

**Enable TimescaleDB Extension:**
```sql
-- Run on PostgreSQL 15+ with TimescaleDB installed
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
```

**Create Hypertable (replaces `telemetry_snapshot`):**
```sql
-- apps/backend/migrations/versions/0048_timescaledb_telemetry.py
def upgrade():
    # Create new table with optimized schema
    op.execute("""
        CREATE TABLE telemetry_metrics (
            time         TIMESTAMPTZ NOT NULL,
            tenant_id    INTEGER NOT NULL,
            entity_id    INTEGER NOT NULL,
            metric_name  VARCHAR(50) NOT NULL,
            value        DOUBLE PRECISION,
            unit         VARCHAR(20),
            tags         JSONB,
            PRIMARY KEY (time, tenant_id, entity_id, metric_name)
        );
    """)
    
    # Convert to hypertable (partitioned by time)
    op.execute("""
        SELECT create_hypertable(
            'telemetry_metrics',
            'time',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
    """)
    
    # Create indexes for common queries
    op.execute("""
        CREATE INDEX idx_telemetry_tenant_entity 
        ON telemetry_metrics (tenant_id, entity_id, time DESC);
        
        CREATE INDEX idx_telemetry_metric_name 
        ON telemetry_metrics (tenant_id, metric_name, time DESC);
    """)
    
    # Enable compression (compress chunks older than 7 days)
    op.execute("""
        ALTER TABLE telemetry_metrics SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'tenant_id, entity_id, metric_name',
            timescaledb.compress_orderby = 'time DESC'
        );
        
        SELECT add_compression_policy('telemetry_metrics', INTERVAL '7 days');
    """)
    
    # Retention policy (delete raw data after 90 days)
    op.execute("""
        SELECT add_retention_policy('telemetry_metrics', INTERVAL '90 days');
    """)
```

**Continuous Aggregates (Pre-Computed Rollups):**
```sql
-- 5-minute averages (for live dashboards)
CREATE MATERIALIZED VIEW telemetry_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    tenant_id,
    entity_id,
    metric_name,
    AVG(value) AS avg_value,
    MAX(value) AS max_value,
    MIN(value) AS min_value,
    COUNT(*) AS sample_count
FROM telemetry_metrics
GROUP BY bucket, tenant_id, entity_id, metric_name;

-- Refresh policy (update every 5 minutes)
SELECT add_continuous_aggregate_policy('telemetry_5min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

-- 1-hour rollups (for historical dashboards)
CREATE MATERIALIZED VIEW telemetry_1hour
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    tenant_id,
    entity_id,
    metric_name,
    AVG(value) AS avg_value,
    MAX(value) AS max_value,
    MIN(value) AS min_value
FROM telemetry_metrics
GROUP BY bucket, tenant_id, entity_id, metric_name;
```

**Query Performance Comparison:**
```python
# Before (standard PostgreSQL table)
SELECT entity_id, AVG(cpu_percent) 
FROM telemetry_snapshot 
WHERE tenant_id = 1 
  AND timestamp >= NOW() - INTERVAL '30 days'
GROUP BY entity_id;
-- Scans 50M rows, takes 8 seconds

# After (TimescaleDB with continuous aggregates)
SELECT entity_id, AVG(avg_value) 
FROM telemetry_1hour 
WHERE tenant_id = 1 
  AND bucket >= NOW() - INTERVAL '30 days'
GROUP BY entity_id;
-- Scans 720 pre-aggregated rows (30 days × 24 hours), takes 20ms (400x faster)
```

---

### 2.2 Parallel Telemetry Polling

**Why:** Current sequential polling takes 5.5 hours for 10,000 devices. Need concurrent workers.

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│           NATS JetStream (telemetry-jobs)               │
└───────────┬─────────────┬─────────────┬─────────────────┘
            │             │             │
            ▼             ▼             ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Worker 1 │  │ Worker 2 │  │ Worker N │
    │ (SNMP)   │  │ (IPMI)   │  │ (Promox) │
    └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │
         └─────────────┴─────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  TimescaleDB     │
              │ telemetry_metrics│
              └──────────────────┘
```

**Worker Pool Implementation:**
```python
# apps/backend/src/app/workers/telemetry_collector.py
import asyncio
from typing import List
from app.integrations.dispatcher import get_integration_client

class TelemetryCollectorWorker:
    def __init__(self, worker_id: int, concurrency: int = 50):
        self.worker_id = worker_id
        self.concurrency = concurrency  # Poll 50 devices concurrently
        self.semaphore = asyncio.Semaphore(concurrency)
    
    async def poll_device(self, entity: Entity) -> List[Metric]:
        """Poll a single device with timeout and retry."""
        async with self.semaphore:
            try:
                client = get_integration_client(entity.integration_type)
                metrics = await asyncio.wait_for(
                    client.poll_metrics(entity),
                    timeout=5.0  # 5-second timeout per device
                )
                return metrics
            except asyncio.TimeoutError:
                _logger.warning(f"Timeout polling {entity.id}")
                return []
            except Exception as exc:
                _logger.error(f"Error polling {entity.id}: {exc}")
                return []
    
    async def process_batch(self, entities: List[Entity], db: Session):
        """Poll a batch of devices in parallel."""
        tasks = [self.poll_device(entity) for entity in entities]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Bulk insert to TimescaleDB
        metrics = [m for result in results if result for m in result]
        if metrics:
            telemetry_service.bulk_insert_metrics(db, metrics)
    
    async def run(self):
        """Main worker loop: consume jobs from NATS."""
        async for msg in nats_client.subscribe("telemetry-jobs"):
            job = json.loads(msg.data)
            entities = db.query(Entity).filter(
                Entity.tenant_id == job["tenant_id"],
                Entity.telemetry_enabled == True
            ).all()
            
            # Split into batches of 50
            for i in range(0, len(entities), 50):
                batch = entities[i:i+50]
                await self.process_batch(batch, db)
            
            await msg.ack()
```

**Horizontal Scaling (Multiple Workers):**
```yaml
# docker-compose.yml
services:
  telemetry-worker:
    image: ghcr.io/blkleg/circuitbreaker:backend-latest
    command: python -m app.workers.telemetry_collector
    deploy:
      replicas: 10  # 10 workers × 50 concurrent polls = 500 devices in parallel
    environment:
      - WORKER_CONCURRENCY=50
```

**Expected Performance:**
- 10,000 devices with 10 workers (50 concurrent per worker):
  - Total concurrency: 500 devices
  - Time per cycle: 10,000 ÷ 500 × 5 seconds = 100 seconds (from 5.5 hours)
  - Throughput: 100 devices/second

---

### 2.3 Streaming Aggregation (Real-Time Dashboards)

**Why:** Dashboards query DB on every refresh (expensive for 10,000 devices).

**Architecture (Redis Streams):**
```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Telemetry   │─────▶│ Redis Stream │─────▶│  Aggregator  │
│   Worker     │      │ (raw metrics)│      │   Worker     │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │ Redis Hash      │
                                            │ (live_metrics)  │
                                            │ tenant:1:cpu    │
                                            │ → avg: 45.2%    │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │   WebSocket     │
                                            │   Broadcast     │
                                            └─────────────────┘
```

**Implementation:**
```python
# apps/backend/src/app/workers/aggregator.py
import redis.asyncio as redis
from collections import defaultdict

class StreamingAggregator:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.window = 60  # 60-second rolling window
    
    async def run(self):
        """Consume metrics from Redis Stream, compute aggregates."""
        while True:
            # Read from stream (blocking, 1-second timeout)
            messages = await self.redis.xread(
                {"telemetry:stream": "$"},
                count=100,
                block=1000
            )
            
            if not messages:
                continue
            
            # Group metrics by tenant + metric_name
            aggregates = defaultdict(lambda: {"sum": 0, "count": 0, "max": 0})
            
            for stream, msgs in messages:
                for msg_id, data in msgs:
                    tenant_id = int(data[b"tenant_id"])
                    metric_name = data[b"metric_name"].decode()
                    value = float(data[b"value"])
                    
                    key = f"{tenant_id}:{metric_name}"
                    aggregates[key]["sum"] += value
                    aggregates[key]["count"] += 1
                    aggregates[key]["max"] = max(aggregates[key]["max"], value)
            
            # Write aggregates to Redis Hash (TTL 60 seconds)
            for key, agg in aggregates.items():
                tenant_id, metric_name = key.split(":", 1)
                avg_value = agg["sum"] / agg["count"]
                
                await self.redis.hset(
                    f"live_metrics:{tenant_id}",
                    metric_name,
                    json.dumps({
                        "avg": avg_value,
                        "max": agg["max"],
                        "count": agg["count"],
                        "timestamp": time.time()
                    })
                )
                await self.redis.expire(f"live_metrics:{tenant_id}", 60)
                
                # Publish to WebSocket channel
                await redis_pubsub.publish(
                    f"telemetry:live:{tenant_id}",
                    json.dumps({
                        "metric": metric_name,
                        "avg": avg_value,
                        "max": agg["max"]
                    })
                )
```

**Dashboard Query (No DB Hit):**
```python
# apps/backend/src/app/api/telemetry.py
@router.get("/live/{tenant_id}")
async def get_live_metrics(tenant_id: int, redis: Redis = Depends(get_redis)):
    """Get pre-aggregated live metrics from Redis (no DB query)."""
    metrics = await redis.hgetall(f"live_metrics:{tenant_id}")
    return {
        metric.decode(): json.loads(value)
        for metric, value in metrics.items()
    }
```

**Expected Impact:**
- Dashboard refresh latency: 500ms → 5ms (100x faster)
- Database load: -90% (live dashboards no longer query DB)
- Real-time lag: <1 second (from metric poll to dashboard update)

---

### 2.4 Telemetry Data Retention & Downsampling

**TimescaleDB Retention Policies:**
```sql
-- Raw metrics: keep 90 days
SELECT add_retention_policy('telemetry_metrics', INTERVAL '90 days');

-- 5-minute aggregates: keep 1 year
SELECT add_retention_policy('telemetry_5min', INTERVAL '1 year');

-- 1-hour aggregates: keep 5 years
SELECT add_retention_policy('telemetry_1hour', INTERVAL '5 years');
```

**Storage Estimates:**
- 10,000 devices × 10 metrics/device × 1 sample/5min × 90 days = 259M rows (raw)
  - Compressed: ~25GB (with TimescaleDB compression)
- 10,000 devices × 10 metrics × 12 samples/hour × 365 days = 438M rows (5-min aggregates)
  - Compressed: ~40GB
- Total: ~65GB for 1 year of telemetry (vs. 500GB+ without compression)

**Phase 2 Deliverables:**
- ✅ TimescaleDB hypertable with automatic compression and retention
- ✅ Continuous aggregates (5-min, 1-hour, 1-day) for fast historical queries
- ✅ Parallel telemetry workers (10 workers × 50 concurrent polls = 500 devices/sec)
- ✅ Redis Streams for real-time aggregation (live dashboards, no DB hit)
- ✅ Retention policies (90-day raw, 1-year 5-min, 5-year 1-hour)

**Success Metrics:**
- Telemetry polling time for 10,000 devices: <3 minutes (from 5.5 hours)
- Historical query latency (30-day chart): <50ms (from 8 seconds)
- Live dashboard latency: <10ms (from 500ms)
- Storage efficiency: 10x compression for historical data

---

## Phase 3: Multi-Tenancy Foundation (4 months)

**Goal:** Enforce tenant isolation at database and application layers, implement resource quotas.

### 3.1 Database Schema-per-Tenant

**Why:** Row-Level Security (RLS) has performance overhead and doesn't provide full isolation.

**Architecture (Schema Isolation):**
```
┌──────────────────────────────────────────────────────┐
│             PostgreSQL Database                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Schema:     │  │ Schema:     │  │ Schema:     │ │
│  │ tenant_1    │  │ tenant_2    │  │ tenant_N    │ │
│  │             │  │             │  │             │ │
│  │ - entities  │  │ - entities  │  │ - entities  │ │
│  │ - relations │  │ - relations │  │ - relations │ │
│  │ - telemetry │  │ - telemetry │  │ - telemetry │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
│  ┌─────────────────────────────────────────────────┐ │
│  │ public schema (global tables)                   │ │
│  │ - tenants                                       │ │
│  │ - users (cross-tenant admin)                    │ │
│  │ - audit_log                                     │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

**Schema Provisioning (Alembic Multi-Tenant Migrations):**
```python
# apps/backend/src/app/services/tenant_service.py
from sqlalchemy import text

class TenantService:
    def create_tenant(self, db: Session, tenant_name: str) -> Tenant:
        # Create tenant record in public.tenants
        tenant = Tenant(
            name=tenant_name,
            slug=tenant_name.lower().replace(" ", "_"),
            created_at=utcnow(),
            status="active"
        )
        db.add(tenant)
        db.flush()
        
        # Create dedicated schema
        schema_name = f"tenant_{tenant.id}"
        db.execute(text(f"CREATE SCHEMA {schema_name}"))
        
        # Run migrations for tenant schema
        self._run_tenant_migrations(schema_name)
        
        # Create default admin user
        user = User(
            tenant_id=tenant.id,
            email=f"admin@{tenant.slug}.local",
            role="admin"
        )
        db.add(user)
        db.commit()
        
        return tenant
    
    def _run_tenant_migrations(self, schema_name: str):
        """Run Alembic migrations for tenant schema."""
        from alembic import command
        from alembic.config import Config
        
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", settings.CB_DB_URL_PRIMARY)
        config.set_main_option("script_location", "migrations_tenant")
        
        # Set search_path to tenant schema
        with engine_primary.connect() as conn:
            conn.execute(text(f"SET search_path TO {schema_name}"))
            command.upgrade(config, "head")
```

**Dynamic Schema Routing (Middleware):**
```python
# apps/backend/src/app/middleware/tenant_middleware.py
from sqlalchemy import text

class TenantMiddleware:
    async def __call__(self, request: Request, call_next):
        # Extract tenant from JWT token or subdomain
        token = request.cookies.get("cb_session")
        if token:
            payload = decode_jwt(token)
            tenant_id = payload.get("tenant_id")
            
            # Set PostgreSQL search_path to tenant schema
            async with get_db_write() as db:
                schema_name = f"tenant_{tenant_id}"
                await db.execute(text(f"SET search_path TO {schema_name}, public"))
                
                # Store tenant_id in request state
                request.state.tenant_id = tenant_id
                request.state.schema_name = schema_name
        
        response = await call_next(request)
        return response
```

**SQLAlchemy Session with Schema Context:**
```python
# apps/backend/src/app/db/session.py
from contextvars import ContextVar

current_tenant_schema = ContextVar("current_tenant_schema", default="public")

def get_tenant_db():
    """Get database session with tenant schema set."""
    session = sessionmaker(bind=engine_primary)()
    schema_name = current_tenant_schema.get()
    
    try:
        session.execute(text(f"SET search_path TO {schema_name}, public"))
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()
```

---

### 3.2 Tenant-Scoped Rate Limiting

**Why:** Prevent one tenant from exhausting API for others.

**Implementation (Redis-Backed Token Bucket):**
```python
# apps/backend/src/app/core/tenant_rate_limit.py
from redis import Redis
from fastapi import HTTPException, status

class TenantRateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis
    
    async def check_limit(
        self,
        tenant_id: int,
        endpoint: str,
        limit: int,
        window: int
    ) -> bool:
        """
        Token bucket rate limiting per tenant.
        
        Args:
            tenant_id: Tenant identifier
            endpoint: API endpoint (e.g., "POST /api/v1/entities")
            limit: Max requests per window (e.g., 1000)
            window: Time window in seconds (e.g., 60)
        
        Returns:
            True if request allowed, raises HTTPException if exceeded
        """
        key = f"rate_limit:{tenant_id}:{endpoint}"
        
        # Increment counter with expiry
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        current, _ = pipe.execute()
        
        if current > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} requests per {window} seconds"
            )
        
        return True

# Dependency for route protection
async def tenant_rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis)
):
    tenant_id = request.state.tenant_id
    endpoint = f"{request.method} {request.url.path}"
    limiter = TenantRateLimiter(redis)
    
    # Different limits for different endpoints
    if endpoint.startswith("POST /api/v1/discovery"):
        await limiter.check_limit(tenant_id, endpoint, limit=10, window=60)  # 10 scans/min
    elif endpoint.startswith("GET /api/v1/topology"):
        await limiter.check_limit(tenant_id, endpoint, limit=100, window=60)  # 100 reads/min
    else:
        await limiter.check_limit(tenant_id, endpoint, limit=1000, window=60)  # 1000 general/min
```

**Usage in Routes:**
```python
# apps/backend/src/app/api/discovery.py
@router.post("/scans", dependencies=[Depends(tenant_rate_limit)])
def create_scan(payload: ScanCreate, db: Session = Depends(get_tenant_db)):
    return discovery_service.create_scan(db, payload)
```

---

### 3.3 Resource Quotas & Enforcement

**Why:** Prevent one tenant with 50,000 entities from degrading platform performance.

**Quota Configuration (Database):**
```python
# apps/backend/src/app/db/models.py
class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    plan = Column(String, default="standard")  # starter, standard, enterprise
    
    # Resource quotas (enforced by application)
    quota_entities = Column(Integer, default=5000)
    quota_users = Column(Integer, default=50)
    quota_api_requests_per_hour = Column(Integer, default=100000)
    quota_telemetry_retention_days = Column(Integer, default=90)
    quota_storage_mb = Column(Integer, default=10000)
    
    # Current usage (updated by background worker)
    usage_entities = Column(Integer, default=0)
    usage_users = Column(Integer, default=0)
    usage_api_requests_last_hour = Column(Integer, default=0)
    usage_storage_mb = Column(Integer, default=0)
    
    # Billing & status
    status = Column(String, default="active")  # active, suspended, trial
    trial_ends_at = Column(DateTime, nullable=True)
```

**Quota Enforcement Middleware:**
```python
# apps/backend/src/app/middleware/quota_middleware.py
class QuotaMiddleware:
    async def __call__(self, request: Request, call_next):
        tenant_id = request.state.tenant_id
        tenant = db.query(Tenant).get(tenant_id)
        
        # Check tenant status
        if tenant.status == "suspended":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Account suspended. Please contact support."
            )
        
        # Check trial expiry
        if tenant.trial_ends_at and utcnow() > tenant.trial_ends_at:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Trial expired. Please upgrade to continue."
            )
        
        # Check entity quota (for POST /entities)
        if request.method == "POST" and "/entities" in request.url.path:
            if tenant.usage_entities >= tenant.quota_entities:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Entity quota exceeded: {tenant.quota_entities} limit"
                )
        
        response = await call_next(request)
        return response
```

**Usage Tracking (Background Worker):**
```python
# apps/backend/src/app/workers/quota_tracker.py
class QuotaTracker:
    async def run(self):
        """Update tenant usage metrics every 5 minutes."""
        while True:
            tenants = db.query(Tenant).filter_by(status="active").all()
            
            for tenant in tenants:
                schema_name = f"tenant_{tenant.id}"
                
                # Count entities
                entity_count = db.execute(text(f"""
                    SELECT COUNT(*) FROM {schema_name}.entities
                """)).scalar()
                
                # Count users
                user_count = db.query(User).filter_by(tenant_id=tenant.id).count()
                
                # Get API request count from Redis
                api_count = redis.get(f"api_requests:{tenant.id}:last_hour") or 0
                
                # Update tenant usage
                tenant.usage_entities = entity_count
                tenant.usage_users = user_count
                tenant.usage_api_requests_last_hour = int(api_count)
                
            db.commit()
            await asyncio.sleep(300)  # Run every 5 minutes
```

---

### 3.4 Tenant Subdomain Routing

**Why:** Isolate tenants with dedicated subdomains (e.g., `acme.circuitbreaker.io`).

**Architecture:**
```
                ┌─────────────────────────────┐
                │   Wildcard DNS              │
                │   *.circuitbreaker.io       │
                │   → Load Balancer           │
                └─────────────┬───────────────┘
                              │
                              ▼
                ┌─────────────────────────────┐
                │   nginx (TLS termination)   │
                │   - Extract subdomain       │
                │   - Proxy to backend        │
                └─────────────┬───────────────┘
                              │
                              ▼
                ┌─────────────────────────────┐
                │   FastAPI Backend           │
                │   TenantMiddleware          │
                │   - Resolve tenant by slug  │
                │   - Set search_path         │
                └─────────────────────────────┘
```

**nginx Configuration:**
```nginx
# docker/nginx.conf
server {
    listen 443 ssl http2;
    server_name ~^(?<subdomain>.+)\.circuitbreaker\.io$;
    
    ssl_certificate /etc/letsencrypt/live/circuitbreaker.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/circuitbreaker.io/privkey.pem;
    
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Tenant-Slug $subdomain;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Tenant Resolution (Backend Middleware):**
```python
# apps/backend/src/app/middleware/tenant_middleware.py
class TenantMiddleware:
    async def __call__(self, request: Request, call_next):
        # Extract tenant from subdomain (sent by nginx)
        tenant_slug = request.headers.get("X-Tenant-Slug")
        
        if tenant_slug:
            # Resolve tenant by slug (cached in Redis)
            tenant = await self._resolve_tenant(tenant_slug)
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant not found")
            
            # Set search_path to tenant schema
            request.state.tenant_id = tenant.id
            request.state.schema_name = f"tenant_{tenant.id}"
            
            async with get_db_write() as db:
                await db.execute(text(f"SET search_path TO {request.state.schema_name}, public"))
        
        response = await call_next(request)
        return response
    
    async def _resolve_tenant(self, slug: str) -> Tenant | None:
        # Try Redis cache first
        cached = await redis.get(f"tenant:slug:{slug}")
        if cached:
            return Tenant(**json.loads(cached))
        
        # Fallback to database
        tenant = db.query(Tenant).filter_by(slug=slug).first()
        if tenant:
            await redis.setex(
                f"tenant:slug:{slug}",
                3600,  # 1-hour TTL
                json.dumps(tenant.to_dict())
            )
        return tenant
```

**Phase 3 Deliverables:**
- ✅ Database schema-per-tenant with automatic provisioning
- ✅ Tenant middleware with dynamic search_path routing
- ✅ Tenant-scoped rate limiting (Redis token bucket)
- ✅ Resource quotas (entities, users, API requests, storage)
- ✅ Quota enforcement middleware and background tracker
- ✅ Subdomain routing (`acme.circuitbreaker.io` → tenant_123 schema)

**Success Metrics:**
- Tenant isolation: 100% (zero cross-tenant data leaks in audit)
- Rate limiting accuracy: 99.9% (within 1% of quota)
- Quota enforcement: Real-time (new entity rejected immediately if over quota)
- Tenant provisioning: <5 seconds (create schema, run migrations, create admin user)

---

## Phase 4: Map Engine Overhaul (5 months)

**Goal:** Replace ReactFlow with WebGL rendering, add graph virtualization, support 10,000+ nodes.

### 4.1 Technology Evaluation & Selection

**Current Problem:**
- ReactFlow renders all nodes to DOM (10,000 nodes = 10,000 DOM elements = browser crash)
- No virtualization (off-screen nodes still rendered)
- Slow panning/zooming (layout recalculation on every frame)
- MapPage.jsx is 2,897 LOC (large monolithic component, difficult to maintain)

**Candidate Technologies:**

| Technology | Pros | Cons | Verdict |
|------------|------|------|---------|
| **Sigma.js** | WebGL rendering, 100k+ nodes, force-atlas layout | Limited React integration | ✅ **Recommended** |
| **Cytoscape.js** | Feature-rich, extensive layouts | Canvas-based (slower than WebGL) | ❌ |
| **vis.js** | Easy to use, good docs | No WebGL, limited to 1,000 nodes | ❌ |
| **yFiles** | Enterprise-grade, automatic layouts | Commercial license ($$$) | ❌ |
| **3D Force Graph** | Three.js/WebGL, 3D visualization | Overkill for 2D topology | ❌ |

**Decision: Sigma.js + Custom React Wrapper**

---

### 4.2 Sigma.js Integration (WebGL Renderer)

**Architecture:**
```
┌──────────────────────────────────────────────────────┐
│            MapPage (Refactored)                       │
│  ┌───────────────────────────────────────────────┐  │
│  │  SigmaMapCanvas (WebGL Container)             │  │
│  │  - Sigma.js instance                          │  │
│  │  - Event handlers (click, hover, drag)       │  │
│  │  - Layout worker (off-main-thread)           │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  MapControlPanel (React UI Overlay)           │  │
│  │  - Layout selector                            │  │
│  │  - Filters (entity type, tags)               │  │
│  │  - Search box                                 │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  EntityDetailSidebar (Selected Node)          │  │
│  │  - Telemetry badges                           │  │
│  │  - Actions (edit, delete, docs)              │  │
│  └───────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

**Implementation:**
```tsx
// apps/frontend/src/components/map/SigmaMapCanvas.tsx
import Sigma from 'sigma';
import Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import { useEffect, useRef, useState } from 'react';

interface SigmaMapCanvasProps {
  nodes: Node[];
  edges: Edge[];
  onNodeClick: (nodeId: string) => void;
  onNodeHover: (nodeId: string | null) => void;
}

export function SigmaMapCanvas({ nodes, edges, onNodeClick, onNodeHover }: SigmaMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [sigma, setSigma] = useState<Sigma | null>(null);
  
  useEffect(() => {
    if (!containerRef.current) return;
    
    // Create graph
    const graph = new Graph();
    
    // Add nodes (efficient bulk add)
    nodes.forEach(node => {
      graph.addNode(node.id, {
        x: node.x || Math.random() * 1000,
        y: node.y || Math.random() * 1000,
        size: node.entity_type === 'hardware' ? 15 : 10,
        label: node.name,
        color: node.health === 'healthy' ? '#10b981' : '#ef4444',
        type: 'circle',  // Custom renderer for health rings
      });
    });
    
    // Add edges
    edges.forEach(edge => {
      graph.addEdge(edge.source, edge.target, {
        size: 2,
        color: '#64748b',
        type: 'line',
      });
    });
    
    // Initialize Sigma with WebGL renderer
    const sigmaInstance = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultNodeType: 'circle',
      defaultEdgeType: 'line',
      enableEdgeClickEvents: true,
      enableEdgeHoverEvents: true,
    });
    
    // Apply force-atlas layout (Web Worker)
    const layout = forceAtlas2(graph, {
      iterations: 100,
      settings: {
        gravity: 1,
        scalingRatio: 10,
        strongGravityMode: false,
      },
    });
    
    // Event handlers
    sigmaInstance.on('clickNode', (event) => {
      onNodeClick(event.node);
    });
    
    sigmaInstance.on('enterNode', (event) => {
      onNodeHover(event.node);
    });
    
    sigmaInstance.on('leaveNode', () => {
      onNodeHover(null);
    });
    
    setSigma(sigmaInstance);
    
    return () => {
      sigmaInstance.kill();
    };
  }, [nodes, edges]);
  
  return (
    <div ref={containerRef} style={{ width: '100%', height: '100vh' }} />
  );
}
```

**Custom Node Renderer (Health Rings):**
```typescript
// apps/frontend/src/components/map/renderers/HealthRingRenderer.ts
import { NodeDisplayData } from 'sigma/types';

export function drawHealthRing(
  context: CanvasRenderingContext2D,
  data: NodeDisplayData,
  settings: any
) {
  const { x, y, size, color, borderColor, label } = data;
  
  // Draw outer ring (health status)
  context.beginPath();
  context.arc(x, y, size + 3, 0, Math.PI * 2);
  context.strokeStyle = borderColor || color;
  context.lineWidth = 2;
  context.stroke();
  
  // Draw inner circle (entity)
  context.beginPath();
  context.arc(x, y, size, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
  
  // Draw label (if zoomed in)
  if (settings.zoomLevel > 0.5) {
    context.fillStyle = '#000';
    context.font = '12px sans-serif';
    context.fillText(label, x + size + 5, y + 4);
  }
}

// Register custom renderer
Sigma.registerNodeProgram('health-ring', drawHealthRing);
```

---

### 4.3 Graph Virtualization (Viewport Culling)

**Why:** Even WebGL struggles with 100,000+ edges. Only render visible nodes.

**Implementation (Quadtree Spatial Index):**
```typescript
// apps/frontend/src/components/map/utils/ViewportCuller.ts
import Quadtree from 'quadtree-lib';

export class ViewportCuller {
  private quadtree: Quadtree;
  
  constructor(nodes: Node[]) {
    // Build spatial index
    this.quadtree = new Quadtree({
      width: 10000,
      height: 10000,
      maxObjects: 100,
    });
    
    nodes.forEach(node => {
      this.quadtree.insert({
        x: node.x,
        y: node.y,
        width: node.size,
        height: node.size,
        data: node,
      });
    });
  }
  
  getVisibleNodes(viewport: Viewport): Node[] {
    // Query quadtree for nodes in viewport
    const results = this.quadtree.retrieve({
      x: viewport.x,
      y: viewport.y,
      width: viewport.width,
      height: viewport.height,
    });
    
    return results.map(r => r.data);
  }
}

// Usage in Sigma
sigma.on('afterRender', () => {
  const camera = sigma.getCamera();
  const viewport = {
    x: camera.x - window.innerWidth / 2,
    y: camera.y - window.innerHeight / 2,
    width: window.innerWidth,
    height: window.innerHeight,
  };
  
  const visibleNodes = culler.getVisibleNodes(viewport);
  
  // Hide off-screen nodes (set alpha=0)
  graph.forEachNode((nodeId, attrs) => {
    const visible = visibleNodes.some(n => n.id === nodeId);
    graph.setNodeAttribute(nodeId, 'hidden', !visible);
  });
});
```

**Expected Performance:**
- 10,000 nodes, viewport showing 200 nodes:
  - Rendered nodes: 200 (from 10,000)
  - Frame rate: 60 FPS (from 5 FPS with ReactFlow)
  - Initial load: <2 seconds (from 10 seconds)

---

### 4.4 Map Clustering (Collapse Subnets/Racks)

**Why:** Collapse groups of nodes (e.g., subnet with 500 hosts) into a single cluster node.

**Implementation (Graph Aggregation):**
```typescript
// apps/frontend/src/components/map/utils/GraphClusterer.ts
export class GraphClusterer {
  cluster(graph: Graph, clusterKey: string): Graph {
    const clustered = new Graph();
    const clusters = new Map<string, Node[]>();
    
    // Group nodes by cluster key (e.g., "subnet_id" or "rack_id")
    graph.forEachNode((nodeId, attrs) => {
      const key = attrs[clusterKey];
      if (!clusters.has(key)) {
        clusters.set(key, []);
      }
      clusters.get(key)!.push({ id: nodeId, ...attrs });
    });
    
    // Create cluster nodes
    clusters.forEach((nodes, key) => {
      if (nodes.length === 1) {
        // Single node, don't cluster
        clustered.addNode(nodes[0].id, nodes[0]);
      } else {
        // Create cluster node
        const clusterId = `cluster_${key}`;
        clustered.addNode(clusterId, {
          x: nodes.reduce((sum, n) => sum + n.x, 0) / nodes.length,
          y: nodes.reduce((sum, n) => sum + n.y, 0) / nodes.length,
          size: Math.sqrt(nodes.length) * 10,
          label: `${key} (${nodes.length} nodes)`,
          color: '#3b82f6',
          type: 'cluster',
          childNodes: nodes,
        });
      }
    });
    
    // Add edges between clusters
    graph.forEachEdge((edgeId, attrs, source, target) => {
      const sourceCluster = this.getClusterId(clustered, source);
      const targetCluster = this.getClusterId(clustered, target);
      
      if (sourceCluster !== targetCluster) {
        clustered.addEdge(sourceCluster, targetCluster, attrs);
      }
    });
    
    return clustered;
  }
  
  expand(graph: Graph, clusterId: string): Node[] {
    const clusterNode = graph.getNodeAttributes(clusterId);
    return clusterNode.childNodes || [];
  }
}

// Usage
const clusterer = new GraphClusterer();
const clusteredGraph = clusterer.cluster(originalGraph, 'subnet_id');

// On cluster click, expand
sigma.on('clickNode', (event) => {
  const node = graph.getNodeAttributes(event.node);
  if (node.type === 'cluster') {
    const expanded = clusterer.expand(graph, event.node);
    // Replace cluster node with child nodes
    graph.dropNode(event.node);
    expanded.forEach(child => graph.addNode(child.id, child));
  }
});
```

**Expected Impact:**
- 10,000-node graph with 20 subnets (500 hosts each):
  - Clustered view: 20 nodes (one per subnet)
  - Load time: <500ms (from 10 seconds)
  - User can drill down into subnet (expand cluster)

---

### 4.5 Refactor MapPage.jsx (2,897 LOC → Modular)

**Current Problem:** Large monolithic component that's difficult to test, maintain, and extend.

**Refactored Structure:**
```
apps/frontend/src/pages/MapPage/
├── MapPage.tsx                  (100 LOC, orchestrator)
├── components/
│   ├── SigmaMapCanvas.tsx       (WebGL renderer, 200 LOC)
│   ├── MapControlPanel.tsx      (Filters, layout selector, 150 LOC)
│   ├── EntityDetailSidebar.tsx  (Selected node details, 200 LOC)
│   ├── MapToolbar.tsx           (Actions, zoom controls, 100 LOC)
│   └── MapLegend.tsx            (Entity types, health status, 80 LOC)
├── hooks/
│   ├── useTopologyData.ts       (Fetch topology from API, 100 LOC)
│   ├── useMapLayout.ts          (Layout algorithms, 150 LOC)
│   ├── useMapSelection.ts       (Node selection state, 80 LOC)
│   └── useMapWebSocket.ts       (Live updates, 120 LOC)
├── utils/
│   ├── ViewportCuller.ts        (Quadtree culling, 150 LOC)
│   ├── GraphClusterer.ts        (Subnet/rack clustering, 200 LOC)
│   ├── LayoutWorker.ts          (Off-thread layout, 100 LOC)
│   └── MapHelpers.ts            (Utilities, 100 LOC)
└── renderers/
    ├── HealthRingRenderer.ts    (Custom node renderer, 80 LOC)
    └── CableEdgeRenderer.ts     (Custom edge renderer, 80 LOC)
```

**Total:** ~1,790 LOC (from 2,897 LOC) — 38% smaller, fully modular and testable.

---

### 4.6 Layout Computation in Web Worker

**Why:** Layout algorithms block main thread (UI freeze during force-atlas computation).

**Implementation:**
```typescript
// apps/frontend/src/pages/MapPage/utils/LayoutWorker.ts
import { expose } from 'comlink';
import Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';

const LayoutWorker = {
  computeForceAtlas(graphData: any, iterations: number) {
    const graph = new Graph();
    
    // Reconstruct graph from serialized data
    graphData.nodes.forEach((n: any) => graph.addNode(n.id, n));
    graphData.edges.forEach((e: any) => graph.addEdge(e.source, e.target, e));
    
    // Run layout algorithm
    forceAtlas2.assign(graph, { iterations });
    
    // Serialize positions
    const positions: Record<string, { x: number; y: number }> = {};
    graph.forEachNode((nodeId, attrs) => {
      positions[nodeId] = { x: attrs.x, y: attrs.y };
    });
    
    return positions;
  },
};

expose(LayoutWorker);

// Usage in MapPage
import { wrap } from 'comlink';

const worker = new Worker(new URL('./LayoutWorker.ts', import.meta.url));
const layoutWorker = wrap<typeof LayoutWorker>(worker);

const positions = await layoutWorker.computeForceAtlas(graphData, 100);
// Update Sigma with new positions (UI never froze)
```

**Phase 4 Deliverables:**
- ✅ Sigma.js WebGL renderer replacing ReactFlow
- ✅ Viewport culling (Quadtree spatial index) for 10,000+ nodes
- ✅ Graph clustering (collapse subnets/racks into single nodes)
- ✅ MapPage.jsx refactored from 2,897 LOC to ~1,790 LOC (modular components)
- ✅ Layout computation in Web Worker (non-blocking)
- ✅ Custom node renderers (health rings, telemetry badges)

**Success Metrics:**
- 10,000-node topology initial load: <2 seconds (from 10+ seconds)
- Frame rate: 60 FPS stable (from 5 FPS)
- Memory usage: <500 MB (from 2GB+)
- UI responsiveness: No jank during pan/zoom/drag

---

## Phase 5: Horizontal Scaling & High Availability (4 months)

**Goal:** Eliminate single points of failure, enable horizontal scaling for all services.

### 5.1 PostgreSQL High Availability (Patroni)

**Why:** Single PostgreSQL instance is SPOF (downtime during maintenance/failures).

**Architecture (Patroni + HAProxy):**
```
┌──────────────────────────────────────────────────────┐
│                   HAProxy                             │
│  - Port 5432 (write) → Primary                       │
│  - Port 5433 (read)  → Any replica                   │
└────────────┬────────────────────────────────────────┘
             │
             ├──────────────────┬───────────────────┐
             ▼                  ▼                   ▼
    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
    │   Primary   │───▶│ Replica 1   │    │ Replica 2   │
    │  (read/write│    │ (read-only) │    │ (read-only) │
    └──────┬──────┘    └─────────────┘    └─────────────┘
           │
           │ Streaming Replication (WAL logs)
           │
    ┌──────▼──────────────────────────────────────────┐
    │         Patroni + etcd (Cluster Manager)        │
    │  - Automatic failover (replica → primary)       │
    │  - Split-brain prevention                       │
    │  - Health checks every 10 seconds               │
    └─────────────────────────────────────────────────┘
```

**Deployment (docker-compose):**
```yaml
# docker-compose-ha.yml
services:
  etcd:
    image: quay.io/coreos/etcd:v3.5.9
    command:
      - etcd
      - --listen-client-urls=http://0.0.0.0:2379
      - --advertise-client-urls=http://etcd:2379
  
  postgres-primary:
    image: ghcr.io/zalando/spilo-15:3.0-p1
    environment:
      - PGVERSION=15
      - SCOPE=circuitbreaker
      - PATRONI_NAME=postgres-primary
      - PATRONI_RESTAPI_CONNECT_ADDRESS=postgres-primary:8008
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=postgres-primary:5432
      - PATRONI_ETCD3_HOSTS=etcd:2379
      - PATRONI_POSTGRESQL_DATA_DIR=/data/postgres
  
  postgres-replica-1:
    image: ghcr.io/zalando/spilo-15:3.0-p1
    environment:
      - SCOPE=circuitbreaker
      - PATRONI_NAME=postgres-replica-1
      - PATRONI_RESTAPI_CONNECT_ADDRESS=postgres-replica-1:8008
      - PATRONI_POSTGRESQL_CONNECT_ADDRESS=postgres-replica-1:5432
      - PATRONI_ETCD3_HOSTS=etcd:2379
  
  haproxy:
    image: haproxy:2.8
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg
    ports:
      - "5432:5432"  # Write port (primary)
      - "5433:5433"  # Read port (any replica)
```

**Expected Impact:**
- **RPO (Recovery Point Objective):** 0 seconds (synchronous replication)
- **RTO (Recovery Time Objective):** <30 seconds (automatic failover)
- **Availability:** 99.95% (from 99.5% with single instance)

---

### 5.2 NATS JetStream Clustering

**Why:** Single NATS instance is bottleneck for job distribution.

**Cluster Configuration:**
```yaml
# docker-compose-ha.yml
services:
  nats-1:
    image: nats:2.10-alpine
    command:
      - "--cluster_name=circuitbreaker"
      - "--cluster=nats://0.0.0.0:6222"
      - "--routes=nats://nats-2:6222,nats://nats-3:6222"
      - "--jetstream"
      - "--store_dir=/data/nats"
    ports:
      - "4222:4222"
  
  nats-2:
    image: nats:2.10-alpine
    command:
      - "--cluster_name=circuitbreaker"
      - "--cluster=nats://0.0.0.0:6222"
      - "--routes=nats://nats-1:6222,nats://nats-3:6222"
      - "--jetstream"
      - "--store_dir=/data/nats"
  
  nats-3:
    image: nats:2.10-alpine
    command:
      - "--cluster_name=circuitbreaker"
      - "--cluster=nats://0.0.0.0:6222"
      - "--routes=nats://nats-1:6222,nats://nats-2:6222"
      - "--jetstream"
      - "--store_dir=/data/nats"
```

**Expected Impact:**
- Job distribution throughput: 10,000 jobs/sec (from 1,000/sec)
- No SPOF (any node can fail, cluster continues)

---

### 5.3 Redis Cluster (Distributed Cache)

**Why:** Single Redis instance bottleneck for 100+ tenants.

**Cluster Configuration (6 nodes):**
```yaml
# docker-compose-ha.yml
services:
  redis-1:
    image: redis:7.2-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "6379:6379"
  
  redis-2:
    image: redis:7.2-alpine
    command: redis-server --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "6380:6379"
  
  # ... redis-3 through redis-6
  
  redis-cluster-init:
    image: redis:7.2-alpine
    depends_on: [redis-1, redis-2, redis-3, redis-4, redis-5, redis-6]
    command: >
      redis-cli --cluster create
        redis-1:6379 redis-2:6379 redis-3:6379
        redis-4:6379 redis-5:6379 redis-6:6379
        --cluster-replicas 1 --cluster-yes
```

**Expected Impact:**
- Cache throughput: 500,000 ops/sec (from 50,000/sec)
- Automatic sharding (data split across nodes by key hash)
- HA: 3 primaries + 3 replicas (can lose 3 nodes without downtime)

---

### 5.4 Backend API Horizontal Scaling (Load Balancer)

**Why:** Single FastAPI instance bottleneck for 10,000+ concurrent users.

**Architecture:**
```
                ┌─────────────────────────────┐
                │   Load Balancer (HAProxy)   │
                │   Round-robin / Least-conn  │
                └─────────────┬───────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ Backend 1   │      │ Backend 2   │      │ Backend N   │
│ FastAPI     │      │ FastAPI     │      │ FastAPI     │
│ Uvicorn 2W  │      │ Uvicorn 2W  │      │ Uvicorn 2W  │
└─────────────┘      └─────────────┘      └─────────────┘
```

**Deployment:**
```yaml
# docker-compose-ha.yml
services:
  backend:
    image: ghcr.io/blkleg/circuitbreaker:backend-latest
    deploy:
      replicas: 5  # 5 instances × 2 Uvicorn workers = 10 workers total
    environment:
      - UVICORN_WORKERS=2
      - CB_DB_URL=postgresql://breaker:pass@haproxy:5432/circuitbreaker
      - CB_REDIS_URL=redis://redis-1:6379,redis-2:6379,redis-3:6379/0
  
  backend-lb:
    image: haproxy:2.8
    ports:
      - "8000:8000"
    volumes:
      - ./haproxy-backend.cfg:/usr/local/etc/haproxy/haproxy.cfg
```

**Expected Impact:**
- API throughput: 50,000 req/sec (from 5,000/sec)
- Latency: p95 <50ms (from 100ms)

---

### 5.5 Session Store Migration (Redis → PostgreSQL + Redis)

**Why:** Sessions in PostgreSQL slow for 10,000+ concurrent users.

**Hybrid Session Store:**
```python
# apps/backend/src/app/core/session_store.py
from redis import Redis
from sqlalchemy.orm import Session

class HybridSessionStore:
    """
    Session data split:
    - Redis: Short-lived session cache (15-min TTL)
    - PostgreSQL: Persistent session log (audit trail)
    """
    def __init__(self, redis: Redis, db: Session):
        self.redis = redis
        self.db = db
    
    async def create(self, user_id: int, tenant_id: int, jwt_token: str):
        session_id = uuid.uuid4().hex
        
        # Write to Redis (fast, TTL 15 minutes)
        await self.redis.setex(
            f"session:{session_id}",
            900,  # 15 minutes
            json.dumps({
                "user_id": user_id,
                "tenant_id": tenant_id,
                "created_at": utcnow().isoformat()
            })
        )
        
        # Write to PostgreSQL (slow, persistent audit log)
        session = Session(
            id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=15)
        )
        self.db.add(session)
        self.db.commit()
        
        return session_id
    
    async def get(self, session_id: str):
        # Try Redis first (fast path)
        data = await self.redis.get(f"session:{session_id}")
        if data:
            return json.loads(data)
        
        # Fallback to PostgreSQL (slow path, session expired in Redis)
        session = self.db.query(Session).get(session_id)
        if session and session.expires_at > utcnow():
            # Repopulate Redis cache
            await self.redis.setex(
                f"session:{session_id}",
                900,
                json.dumps(session.to_dict())
            )
            return session.to_dict()
        
        return None
```

**Phase 5 Deliverables:**
- ✅ PostgreSQL HA with Patroni + HAProxy (automatic failover, <30s RTO)
- ✅ NATS JetStream 3-node cluster (10,000 jobs/sec throughput)
- ✅ Redis 6-node cluster (500,000 ops/sec, automatic sharding)
- ✅ Backend API horizontal scaling (5 replicas × 2 workers = 10 workers)
- ✅ Hybrid session store (Redis for speed, PostgreSQL for audit)

**Success Metrics:**
- System availability: 99.95% (from 99.5%)
- Automatic failover: <30 seconds (PostgreSQL, NATS, Redis)
- API throughput: 50,000 req/sec (from 5,000/sec)
- Zero manual intervention during node failures

---

## Phase 6: Real-Time at Scale (3 months)

**Goal:** Support 10,000+ concurrent WebSocket connections, sub-second updates for all tenants.

### 6.1 WebSocket Connection Pooling

**Why:** Single backend instance limited to ~10,000 WebSocket connections (file descriptor limit).

**Architecture (Dedicated WebSocket Gateway):**
```
┌─────────────────────────────────────────────────────┐
│         WebSocket Gateway (Node.js + uWS)            │
│  - 100,000+ concurrent connections                  │
│  - Sticky sessions (tenant-aware routing)           │
│  - Message filtering (per-tenant subscriptions)     │
└────────────┬────────────────────────────────────────┘
             │
             ▼
    ┌─────────────────┐
    │  Redis Pub/Sub  │ ← Backend publishes events here
    │  (Cluster Mode) │
    └─────────────────┘
```

**Implementation (Node.js + uWebSockets.js):**
```typescript
// apps/ws-gateway/src/index.ts
import { App } from 'uWebSockets.js';
import Redis from 'ioredis';

const redis = new Redis.Cluster([
  { host: 'redis-1', port: 6379 },
  { host: 'redis-2', port: 6379 },
  { host: 'redis-3', port: 6379 },
]);

const connections = new Map<string, Set<WebSocket>>();

App()
  .ws('/ws/topology/:tenant_id', {
    open: (ws) => {
      const tenantId = ws.getParameter(0);
      
      // Add to tenant connection pool
      if (!connections.has(tenantId)) {
        connections.set(tenantId, new Set());
      }
      connections.get(tenantId)!.add(ws);
      
      ws.subscribe(`topology.${tenantId}`);
    },
    
    message: (ws, message, isBinary) => {
      // Client-to-server messages (rare)
      const data = JSON.parse(Buffer.from(message).toString());
      // Forward to backend via NATS or HTTP
    },
    
    close: (ws) => {
      const tenantId = ws.getParameter(0);
      connections.get(tenantId)?.delete(ws);
    },
  })
  .listen(9001, (token) => {
    if (token) {
      console.log('WebSocket gateway listening on port 9001');
    }
  });

// Subscribe to Redis Pub/Sub
redis.psubscribe('topology.*', (err, count) => {
  if (err) console.error(err);
});

redis.on('pmessage', (pattern, channel, message) => {
  const tenantId = channel.split('.')[1];
  const sockets = connections.get(tenantId);
  
  if (sockets) {
    const data = JSON.stringify(message);
    sockets.forEach(ws => {
      ws.send(data, false);  // false = text frame
    });
  }
});
```

**Expected Performance:**
- Concurrent WebSocket connections: 100,000+ (from 10,000)
- Message latency (backend → client): <50ms (from 200ms)
- Memory per connection: 4KB (from 50KB with FastAPI)

---

### 6.2 Event Streaming (NATS → Kafka)

**Why:** NATS JetStream optimized for job queues, not event streaming at scale.

**Migration to Kafka:**
```
┌──────────────────────────────────────────────────────┐
│              Backend API (FastAPI)                    │
│  Entity CRUD → Publish to Kafka topic                │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
    ┌─────────────────┐
    │  Kafka Cluster  │
    │  3 brokers      │
    │  - topology-events (10 partitions)                │
    │  - telemetry-events (20 partitions)               │
    └────────┬────────┘
             │
             ├───────────────────────┬──────────────────┐
             ▼                       ▼                  ▼
    ┌──────────────┐       ┌──────────────┐  ┌──────────────┐
    │ Consumer 1   │       │ Consumer 2   │  │ Consumer N   │
    │ (WebSocket   │       │ (Analytics)  │  │ (Audit Log)  │
    │  broadcast)  │       │              │  │              │
    └──────────────┘       └──────────────┘  └──────────────┘
```

**Kafka Topic Schema:**
```python
# apps/backend/src/app/core/events.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TopologyEvent:
    tenant_id: int
    event_type: str  # "entity.created", "entity.updated", "entity.deleted"
    entity_id: int
    entity_type: str
    timestamp: datetime
    actor_user_id: int
    changes: dict  # For updates, diff of old → new
```

**Producer (Backend API):**
```python
# apps/backend/src/app/api/graph.py
from aiokafka import AIOKafkaProducer

producer = AIOKafkaProducer(bootstrap_servers='kafka:9092')

@router.patch("/entities/{entity_id}")
async def update_entity(entity_id: int, payload: EntityUpdate, db: Session):
    entity = entity_service.update(db, entity_id, payload)
    
    # Publish event to Kafka
    event = TopologyEvent(
        tenant_id=entity.tenant_id,
        event_type="entity.updated",
        entity_id=entity.id,
        entity_type=entity.type,
        timestamp=utcnow(),
        actor_user_id=request.state.user_id,
        changes=payload.dict(exclude_unset=True)
    )
    
    await producer.send(
        topic="topology-events",
        key=str(entity.tenant_id).encode(),  # Partition by tenant
        value=event.to_json().encode()
    )
    
    return entity
```

**Consumer (WebSocket Broadcast):**
```python
# apps/ws-gateway/src/kafka-consumer.py
from aiokafka import AIOKafkaConsumer

consumer = AIOKafkaConsumer(
    'topology-events',
    bootstrap_servers='kafka:9092',
    group_id='ws-broadcast',
    auto_offset_reset='latest'
)

async def consume_events():
    async for msg in consumer:
        event = json.loads(msg.value)
        tenant_id = event['tenant_id']
        
        # Broadcast to WebSocket clients via Redis Pub/Sub
        await redis.publish(
            f"topology.{tenant_id}",
            json.dumps(event)
        )
```

**Expected Impact:**
- Event throughput: 1M events/sec (from 10k/sec with NATS)
- Event retention: 7 days (replay events for analytics)
- Consumer lag: <100ms (real-time dashboards updated instantly)

---

### 6.3 Change Data Capture (PostgreSQL → Kafka)

**Why:** Capture database changes directly (no application code changes).

**Implementation (Debezium):**
```yaml
# docker-compose-ha.yml
services:
  kafka-connect:
    image: debezium/connect:2.4
    environment:
      - BOOTSTRAP_SERVERS=kafka:9092
      - GROUP_ID=circuitbreaker-cdc
      - CONFIG_STORAGE_TOPIC=connect-configs
      - OFFSET_STORAGE_TOPIC=connect-offsets
      - STATUS_STORAGE_TOPIC=connect-status
    ports:
      - "8083:8083"
```

**Debezium Connector Config:**
```json
{
  "name": "circuitbreaker-postgres-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres-primary",
    "database.port": "5432",
    "database.user": "breaker",
    "database.password": "password",
    "database.dbname": "circuitbreaker",
    "table.include.list": "tenant_1.entities,tenant_1.relationships",
    "topic.prefix": "circuitbreaker",
    "plugin.name": "pgoutput",
    "publication.autocreate.mode": "filtered"
  }
}
```

**Expected Impact:**
- Zero application code changes (CDC handles event streaming)
- Guaranteed consistency (database is source of truth)
- Event latency: <10ms (from transaction commit to Kafka)

---

### 6.4 GraphQL Subscriptions (Real-Time Queries)

**Why:** REST + WebSocket is cumbersome. GraphQL subscriptions unify real-time and queries.

**Implementation (Strawberry GraphQL):**
```python
# apps/backend/src/app/graphql/schema.py
import strawberry
from typing import AsyncGenerator

@strawberry.type
class Query:
    @strawberry.field
    async def topology(self, tenant_id: int) -> List[Entity]:
        return await entity_service.get_all(tenant_id)

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def topology_updates(self, tenant_id: int) -> AsyncGenerator[Entity, None]:
        """Subscribe to real-time topology changes."""
        async for event in kafka_consumer.subscribe(f"topology-events-{tenant_id}"):
            entity = await entity_service.get(event.entity_id)
            yield entity

# GraphQL endpoint
from strawberry.fastapi import GraphQLRouter

graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")
```

**Frontend Usage (Apollo Client):**
```typescript
// apps/frontend/src/hooks/useTopologySubscription.ts
import { useSubscription, gql } from '@apollo/client';

const TOPOLOGY_SUBSCRIPTION = gql`
  subscription TopologyUpdates($tenantId: Int!) {
    topologyUpdates(tenantId: $tenantId) {
      id
      name
      type
      health
      x
      y
    }
  }
`;

export function useTopologySubscription(tenantId: number) {
  const { data, loading } = useSubscription(TOPOLOGY_SUBSCRIPTION, {
    variables: { tenantId },
  });
  
  return { entities: data?.topologyUpdates || [], loading };
}
```

**Phase 6 Deliverables:**
- ✅ WebSocket Gateway (Node.js + uWS) for 100,000+ concurrent connections
- ✅ Kafka cluster (3 brokers, 10 partitions) for event streaming (1M events/sec)
- ✅ Debezium CDC (PostgreSQL → Kafka) for zero-code event streaming
- ✅ GraphQL subscriptions (Strawberry) for unified real-time queries

**Success Metrics:**
- Concurrent WebSocket connections: 100,000+ (from 10,000)
- Event throughput: 1M events/sec (from 10k/sec)
- Real-time latency (DB commit → client): <100ms (from 1–2 seconds)
- GraphQL subscription latency: <50ms

---

## Phase 7: Production Hardening (3 months)

**Goal:** Add monitoring, disaster recovery, SLAs, and enterprise compliance.

### 7.1 Observability Stack (Metrics, Logs, Traces)

**Full Stack:**
- **Prometheus** — Metrics scraping (10-second interval)
- **Grafana** — Dashboards, alerting
- **Loki** — Log aggregation (replaces file logs)
- **Tempo** — Distributed tracing (OpenTelemetry)
- **AlertManager** — Alert routing (PagerDuty, Slack, email)

**Critical Dashboards:**
1. **Service Health** — API uptime, error rate, latency (p50/p95/p99)
2. **Database** — Query duration, connection pool, replication lag, disk I/O
3. **Cache** — Redis hit rate, evictions, memory usage, cluster status
4. **Message Bus** — Kafka lag, throughput, partition distribution
5. **Tenant Metrics** — Entity count, API usage, quota consumption per tenant
6. **Real-Time** — WebSocket connections, message latency, event throughput

---

### 7.2 Disaster Recovery (Backup & Restore)

**Automated Backups:**
```bash
# PostgreSQL: Daily full backup + continuous WAL archiving
0 2 * * * pg_dump -U breaker circuitbreaker | gzip > /backups/cb_$(date +\%Y\%m\%d).sql.gz
0 * * * * pg_receivewal -D /backups/wal -S cb_slot -h postgres-primary -U replicator

# Redis: RDB snapshot every 6 hours
save 21600 1

# Kafka: Topic backups to S3 (MirrorMaker2)
bin/kafka-mirror-maker.sh --consumer.config source.properties --producer.config target.properties
```

**Restore Procedure (RPO 1 hour, RTO 15 minutes):**
1. Restore PostgreSQL from latest backup + WAL replay (5 min)
2. Recreate Redis cluster (data repopulated from PostgreSQL, 5 min)
3. Restart Kafka consumers (replay from last checkpoint, 2 min)
4. Bring backend API online (3 min)

---

### 7.3 SLA Definitions

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Uptime** | 99.95% | Monthly (21.6 min downtime/month) |
| **API Latency (p95)** | <100ms | Per-endpoint, per-tenant |
| **Real-Time Latency** | <500ms | DB commit → WebSocket client |
| **Data Loss (RPO)** | 1 hour | PostgreSQL WAL archival frequency |
| **Recovery Time (RTO)** | 15 minutes | Automated failover + manual restore |

---

### 7.4 Compliance & Security Hardening

**SOC 2 Type II Readiness:**
- ✅ Audit logs with tamper-evident hash chain (already implemented)
- ✅ Encryption at rest (PostgreSQL TDE, Redis disk encryption)
- ✅ Encryption in transit (TLS 1.3 for all services)
- ✅ Role-based access control (RBAC with granular scopes)
- ✅ Tenant isolation (database schema-per-tenant)
- ✅ Incident response playbook (documented procedures)

**GDPR Compliance:**
- ✅ Data portability (export tenant data as JSON)
- ✅ Right to erasure (tenant deletion cascades all data)
- ✅ Data processing agreements (DPA templates)
- ✅ Audit log IP redaction (configurable per tenant)

---

## Phase 7 Deliverables

- ✅ Full observability stack (Prometheus, Grafana, Loki, Tempo, AlertManager)
- ✅ Automated backups (PostgreSQL, Redis, Kafka) with 1-hour RPO
- ✅ Disaster recovery runbook (15-minute RTO)
- ✅ SLA definitions and monitoring (99.95% uptime, <100ms p95 latency)
- ✅ SOC 2 Type II readiness (audit logs, encryption, RBAC)
- ✅ GDPR compliance (data portability, erasure, DPA)

**Success Metrics:**
- System availability: 99.95% (21.6 min downtime/month)
- Automated failover: Zero manual intervention for node failures
- Disaster recovery: RTO <15 minutes, RPO <1 hour
- Compliance: Pass SOC 2 Type II audit, GDPR compliant

---

## Timeline & Resource Estimates

| Phase | Duration | Team Size | Key Deliverables |
|-------|----------|-----------|------------------|
| **Phase 1: Foundation** | 3 months | 2 backend, 1 DevOps | Tracing, caching, read replicas, metrics |
| **Phase 2: Telemetry Engine** | 4 months | 2 backend, 1 data eng | TimescaleDB, parallel polling, streaming aggregation |
| **Phase 3: Multi-Tenancy** | 4 months | 3 backend, 1 DBA | Schema-per-tenant, rate limiting, quotas, subdomain routing |
| **Phase 4: Map Engine** | 5 months | 2 frontend, 1 backend | Sigma.js, WebGL, virtualization, refactor MapPage |
| **Phase 5: High Availability** | 4 months | 2 DevOps, 1 backend | Patroni, NATS cluster, Redis cluster, load balancing |
| **Phase 6: Real-Time at Scale** | 3 months | 2 backend, 1 frontend | WebSocket gateway, Kafka, CDC, GraphQL subscriptions |
| **Phase 7: Production Hardening** | 3 months | 1 DevOps, 1 backend | Observability, DR, SLAs, compliance |

**Total:** 24 months (2 years), 5–6 engineers

---

## Success Metrics (End State)

| Metric | Current (v0.2.2) | Target (Production) | Improvement |
|--------|------------------|---------------------|-------------|
| **Entities per Tenant** | 500 tested | 10,000+ | 20x |
| **Concurrent Tenants** | 1 (single-tenant) | 100+ | N/A |
| **API Throughput** | 5,000 req/sec | 50,000 req/sec | 10x |
| **Topology Load Time (10k nodes)** | 10+ seconds | <2 seconds | 5x |
| **Telemetry Polling (10k devices)** | 5.5 hours | <3 minutes | 110x |
| **WebSocket Connections** | 10,000 | 100,000+ | 10x |
| **Real-Time Latency** | 1–2 seconds | <100ms | 20x |
| **System Availability** | 99.5% | 99.95% | 4.3x fewer outages |
| **Memory Usage (idle)** | 500 MB | 2 GB | Acceptable for scale |
| **Database Size (1 year)** | 5 GB | 500 GB | Acceptable for 100 tenants |

---

## Conclusion

This production scaling path transforms Circuit Breaker from a homelab tool into an enterprise-grade multi-tenant platform capable of managing 10,000+ devices per tenant with sub-second real-time updates.

**Critical Path Dependencies:**
- **Phase 1 → Phase 2** — Caching and read replicas required before telemetry overhaul
- **Phase 3 → Phase 5** — Tenant isolation must be in place before HA (each tenant needs isolated failover)
- **Phase 4 → Phase 6** — Map refactor required before real-time at scale (old map can't handle 100k WebSocket updates)

**Risk Mitigation:**
- Run phases in parallel where possible (e.g., Phase 2 + Phase 3 can overlap after Phase 1)
- Maintain backward compatibility (v0.2.x single-tenant mode still works during migration)
- Feature flags for gradual rollout (e.g., `CB_ENABLE_SCHEMA_ISOLATION=true`)
- Comprehensive load testing at end of each phase (simulate 100 tenants, 10k devices each)

**Investment Required:**
- **Team:** 5–6 engineers (2 backend, 2 frontend, 2 DevOps/data eng)
- **Timeline:** 18–24 months (phases can overlap)
- **Infrastructure:** 20–30 VMs (PostgreSQL cluster, Kafka cluster, Redis cluster, load balancers)
- **Budget:** ~$100k–150k/year in cloud costs (AWS/GCP) for development + staging + production

**ROI:** Enterprise customers pay $50–500/month per tenant. 100 tenants = $5k–50k MRR. Break-even in 12–18 months.
