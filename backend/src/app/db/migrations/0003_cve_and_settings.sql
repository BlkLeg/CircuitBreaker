-- Migration 0003: Phase 2 — CVE database settings + cve_entries table
-- All statements are idempotent (safe to re-run).

-- AppSettings: CVE sync fields
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS cve_sync_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS cve_sync_interval_hours INTEGER NOT NULL DEFAULT 24;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS cve_last_sync_at TEXT;

-- CVE entries table -- also created by cve_session.init_cve_db in data/cve.db
CREATE TABLE IF NOT EXISTS cve_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cve_id TEXT NOT NULL UNIQUE,
    vendor TEXT,
    product TEXT,
    version_start TEXT,
    version_end TEXT,
    severity TEXT,
    cvss_score REAL,
    summary TEXT,
    published_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_cve_entries_vendor ON cve_entries(vendor);
CREATE INDEX IF NOT EXISTS idx_cve_entries_product ON cve_entries(product);
CREATE INDEX IF NOT EXISTS idx_cve_entries_cve_id ON cve_entries(cve_id);
