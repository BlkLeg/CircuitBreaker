-- Migration 0001: Additive column guards
-- Adds columns introduced after the initial schema that may be absent on
-- databases created before these fields were added.  Every statement uses
-- IF NOT EXISTS so this file is safe to re-run idempotently.

-- Docs enhancements (v0.1.2)
ALTER TABLE docs ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '';
ALTER TABLE docs ADD COLUMN IF NOT EXISTS pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE docs ADD COLUMN IF NOT EXISTS icon TEXT NOT NULL DEFAULT '';

-- Hardware telemetry columns
ALTER TABLE hardware ADD COLUMN IF NOT EXISTS telemetry_config TEXT;
ALTER TABLE hardware ADD COLUMN IF NOT EXISTS telemetry_data TEXT;
ALTER TABLE hardware ADD COLUMN IF NOT EXISTS telemetry_status TEXT;
ALTER TABLE hardware ADD COLUMN IF NOT EXISTS telemetry_last_polled TEXT;
ALTER TABLE hardware ADD COLUMN IF NOT EXISTS telemetry_enabled INTEGER NOT NULL DEFAULT 0;

-- AppSettings additions
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS auth_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS registration_open INTEGER NOT NULL DEFAULT 1;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS rate_limit_profile TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS dev_mode INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS audit_log_retention_days INTEGER NOT NULL DEFAULT 90;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS audit_log_hide_ip INTEGER NOT NULL DEFAULT 0;

-- Audit logs table (created if absent for environments that predate this table)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id INTEGER,
    ip TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs (timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs (entity_type, entity_id);
