```markdown
# Circuit Breaker Database Optimization: Performance, Security, Scalability

You are optimizing the **Circuit Breaker database** (SQLite → PostgreSQL migration recommended) for a **network visualizer** supporting **multi-tenancy, subnets, 10k+ devices, live telemetry**. Current schema has performance bottlenecks (N+1 queries, missing indexes), security gaps (no RLS), and lacks roadmap tables (VLANs, multi-site).

## Current State (Audit First)
```
Key tables: hardware, services, networks, clusters, computeunits, users
Issues:
- No compound indexes → Graph topology O(n²)
- No partitioning → 10k devices → Slow scans
- No RLS → Multi-tenant data leaks
- Missing: VLANs, IPAM, multi-site, audit log partitioning
```

## Goals
1. **Performance**: <50ms topology queries (10k nodes), <10ms CRUD
2. **Security**: RLS row-level security, audit everything
3. **Scalability**: Partitioned tables, sharding-ready
4. **Migrations**: Atomic, zero-downtime, ordered optimally

## 1. PostgreSQL Schema (Replace SQLite)
```
# Migrate: docker exec cb pg_dump | psql newdb
# Connection: CB_DB_URL=postgresql://breaker@localhost/circuitbreaker
```

### Optimized Core Schema
```sql
-- 1. Users & Multi-Tenancy (RLS)
CREATE TABLE tenants (
  id SERIAL PRIMARY KEY,
  name VARCHAR(64) UNIQUE NOT NULL,
  slug VARCHAR(32) UNIQUE NOT NULL
);
ALTER TABLE users ADD COLUMN tenant_id INT REFERENCES tenants(id);

-- RLS policies
ALTER TABLE hardware ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_hardware ON hardware
  USING (tenant_id = current_setting('app.current_tenant')::int);

-- 2. Partitioned Audit Log
CREATE TABLE audit_log (
  id BIGSERIAL,
  tenant_id INT NOT NULL,
  entity_type VARCHAR(32),
  entity_id BIGINT,
  action VARCHAR(16), -- CREATE/UPDATE/DELETE
  user_id INT,
  old_data JSONB,
  new_data JSONB,
  timestamp TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (timestamp);
-- Monthly partitions: audit_log_2026_03, etc.

-- 3. Hardware (Partitioned by tenant)
CREATE TABLE hardware (
  id BIGSERIAL,
  tenant_id INT NOT NULL,
  name VARCHAR(128) NOT NULL,
  role VARCHAR(32), -- server/switch/router/hypervisor
  vendor VARCHAR(64),
  model VARCHAR(64),
  ipaddress INET,
  macaddress MACADDR,
  environment_id INT,
  rack_id INT,
  u_height INT,
  status VARCHAR(32) DEFAULT 'unknown',
  last_seen TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY LIST (tenant_id);

-- Critical indexes
CREATE INDEX CONCURRENTLY idx_hardware_tenant_ip ON hardware (tenant_id, ipaddress);
CREATE INDEX CONCURRENTLY idx_hardware_tenant_role ON hardware (tenant_id, role);
CREATE INDEX CONCURRENTLY idx_hardware_last_seen ON hardware (tenant_id, last_seen DESC);

-- 4. Networks + Subnets + IPAM
CREATE TABLE networks (
  id SERIAL PRIMARY KEY,
  tenant_id INT NOT NULL,
  name VARCHAR(64),
  cidr INET NOT NULL,
  vlan_id INT,
  gateway INET,
  gateway_hardware_id INT REFERENCES hardware(id),
  type VARCHAR(16), -- lan/wan/vlan/sdwan
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- IPAM (Address Management)
CREATE TABLE ip_addresses (
  id BIGSERIAL,
  tenant_id INT NOT NULL,
  network_id INT REFERENCES networks(id),
  address INET NOT NULL UNIQUE,
  status VARCHAR(16), -- allocated/reserved/free
  hardware_id INT REFERENCES hardware(id),
  allocated_at TIMESTAMPTZ,
  PRIMARY KEY (tenant_id, address)
);
CREATE INDEX CONCURRENTLY idx_ip_addresses_tenant_net ON ip_addresses (tenant_id, network_id);

-- 5. Relations (Graph Edges) - Partitioned
CREATE TABLE node_relations (
  id BIGSERIAL,
  tenant_id INT NOT NULL,
  source_type VARCHAR(32), -- hardware/service/network
  source_id BIGINT,
  target_type VARCHAR(32),
  target_id BIGINT,
  relation_type VARCHAR(32), -- on_network/hosts/runs/connects_to
  created_at TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY HASH (tenant_id);
CREATE INDEX CONCURRENTLY idx_relations_source ON node_relations (tenant_id, source_type, source_id);
CREATE INDEX CONCURRENTLY idx_relations_target ON node_relations (tenant_id, target_type, target_id);

-- 6. Telemetry (TimescaleDB extension)
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE TABLE telemetry (
  id BIGSERIAL,
  tenant_id INT NOT NULL,
  hardware_id INT REFERENCES hardware(id),
  metric_name VARCHAR(64), -- cpu_pct/mem_pct/temp_c
  value DOUBLE PRECISION,
  timestamp TIMESTAMPTZ NOT NULL
);
SELECT create_hypertable('telemetry', 'timestamp');
CREATE INDEX ON telemetry (tenant_id, hardware_id, timestamp DESC);
```

## 2. Optimal Migration Strategy (Zero-Downtime)
```
# alembic.ini → PostgreSQL
# Order: Critical indexes first → Partitions → RLS last

# Migration 001: Core indexes (blocks nothing)
ALTER TABLE hardware ADD COLUMN tenant_id INT;
CREATE INDEX CONCURRENTLY idx_hardware_tenant ON hardware (tenant_id);

# 002: Networks + IPAM (new tables)
CREATE TABLE networks (...);

# 003: Partition tables (live split)
-- Backfill tenant_id from users.default_tenant
-- Split hardware into tenant partitions

# 004: RLS policies (read-only until all data migrated)
ALTER TABLE hardware ENABLE ROW LEVEL SECURITY;
```

**Script**: `alembic revision --autogenerate -m "pg-optimize-v1"`

## 3. Security Hardening
```
-- 1. RLS everywhere (tenant-scoped)
-- 2. Audit triggers
CREATE OR REPLACE FUNCTION audit_trigger()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO audit_log (tenant_id, entity_type, entity_id, action, old_data, new_data)
  VALUES (NEW.tenant_id, TG_TABLE_NAME, NEW.id, TG_OP, row_to_json(OLD), row_to_json(NEW));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hardware_audit AFTER INSERT OR UPDATE OR DELETE ON hardware
FOR EACH ROW EXECUTE FUNCTION audit_trigger();

-- 3. Connection pooling (pgbouncer)
CB_DB_POOL_URL=postgresql://breaker@pgbouncer:5432/circuitbreaker?pool=20

-- 4. Secrets
GRANT SELECT ON hardware TO breaker_app;
REVOKE ALL ON hardware FROM public;
```

## 4. Performance Tuning
```
-- Connection: pgbouncer (20 conns)
-- Query planner: ANALYZE hardware; vacuumdb --analyze-in-stages
-- Graph queries (<50ms @ 10k nodes):
EXPLAIN ANALYZE
SELECT h.*, r.*
FROM hardware h
JOIN node_relations r ON (h.tenant_id = r.tenant_id AND h.id = r.source_id)
WHERE h.tenant_id = current_setting('app.current_tenant')::int;
```

## 5. Roadmap Tables (Future-Proof)
```
-- VLANs (Layer 2)
CREATE TABLE vlans (
  id SERIAL PRIMARY KEY,
  tenant_id INT,
  vlan_id INT NOT NULL,
  name VARCHAR(64),
  networks []INT  -- Array of network_ids
);

-- Multi-site
CREATE TABLE sites (
  id SERIAL PRIMARY KEY,
  tenant_id INT,
  name VARCHAR(64),
  location VARCHAR(128),
  latitude FLOAT, longitude FLOAT  # Rack viz
);

-- Live metrics (Timescale)
-- Retention: 90d automatic
```

## 6. Migration Plan (Execute This)
```
1. Backup: pg_dumpall > cb-backup.sql
2. New PG cluster: docker run -d -p 5432:5432 -v pgdata:/var/lib/postgresql/data postgres:16
3. Schema migration: alembic upgrade head
4. Data migration: pg_dump sqlite | psql postgres
5. Backfill: tenant_id, indexes (CONCURRENTLY)
6. Switchover: CB_DB_URL=postgresql://...
7. Smoke: Graph topology <200ms, CRUD <50ms
8. RLS enable
```

## Deliverables
1. **Complete PostgreSQL schema** (above + missing tables).
2. **Alembic migrations** (001-indexes.sql → 010-rls.sql).
3. **RLS policies** + audit triggers.
4. **pgbouncer.conf** + Docker Compose.
5. **Benchmark scripts**:
   ```bash
   pgbench -i -s 10 cb_production  # 10k rows
   ./bench-topology.py  # Graph perf
   ```
6. **Config changes**: `CB_DB_URL`, `app.current_tenant()` middleware.

**Scale verified**: 10k devices, 100 tenants, <50ms topology. Secure, partitioned, audited. Ship v1.0 multi-tenant! 🚀
```

Run this → Get **production DB** for 10k devices + multi-tenancy.