-- Migration 0012: Add hostname to hardware
-- Stores the DNS hostname discovered during network scans, separate from the
-- display name so manual renames don't overwrite the resolved DNS name.

ALTER TABLE hardware ADD COLUMN IF NOT EXISTS hostname VARCHAR;
