-- Migration 0010: Add error_reason to scan_jobs
-- Records structured failure reasons (scan_timeout, tools_unavailable, scan_error:<type>)
-- so users can distinguish a clean 0-result scan from a silent tool failure.

ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS error_reason TEXT;
