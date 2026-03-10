-- Migration 0005: Uptime Monitoring — hardware_monitors and uptime_events tables
-- All statements are idempotent (safe to re-run).

CREATE TABLE IF NOT EXISTS hardware_monitors (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    hardware_id          INTEGER NOT NULL UNIQUE REFERENCES hardware(id) ON DELETE CASCADE,
    enabled              INTEGER NOT NULL DEFAULT 1,
    interval_secs        INTEGER NOT NULL DEFAULT 60,
    probe_methods        TEXT    NOT NULL DEFAULT '["icmp","tcp","http"]',
    last_status          TEXT    NOT NULL DEFAULT 'unknown',
    last_checked_at      TEXT,
    latency_ms           REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    uptime_pct_24h       REAL,
    created_at           TEXT    NOT NULL,
    updated_at           TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hardware_monitors_hardware_id ON hardware_monitors(hardware_id);
CREATE INDEX IF NOT EXISTS idx_hardware_monitors_enabled     ON hardware_monitors(enabled);

CREATE TABLE IF NOT EXISTS uptime_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hardware_id   INTEGER NOT NULL REFERENCES hardware(id) ON DELETE CASCADE,
    status        TEXT    NOT NULL,   -- 'up' | 'down'
    latency_ms    REAL,
    probe_method  TEXT,               -- which method succeeded or was last tried
    checked_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uptime_events_hardware_id ON uptime_events(hardware_id);
CREATE INDEX IF NOT EXISTS idx_uptime_events_checked_at  ON uptime_events(checked_at);
