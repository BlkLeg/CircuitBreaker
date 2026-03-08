-- Migration 0004: Live Scan Logs — scan_logs table
-- All statements are idempotent (safe to re-run).

-- ScanLog entries table for storing detailed scan log entries
CREATE TABLE IF NOT EXISTS scan_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_job_id INTEGER NOT NULL REFERENCES scan_jobs(id),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,  -- 'INFO', 'SUCCESS', 'WARN', 'ERROR'
    phase TEXT,           -- 'ping', 'arp', 'nmap', 'snmp', 'http', etc.
    message TEXT NOT NULL,
    details TEXT,         -- Raw command output, error traces, etc.
    created_at TEXT NOT NULL
);

-- Index for efficient querying by scan_job_id and timestamp
CREATE INDEX IF NOT EXISTS idx_scan_logs_scan_job_id ON scan_logs(scan_job_id);
CREATE INDEX IF NOT EXISTS idx_scan_logs_timestamp ON scan_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_scan_logs_level ON scan_logs(level);