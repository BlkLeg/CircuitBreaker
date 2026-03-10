-- Migration 0002: FastAPI-Users user model extensions
-- Adds columns required by FastAPI-Users and renames password_hash
-- to hashed_password to match the library convention.
-- All statements are idempotent (safe to re-run).

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at DATETIME;

-- Backfill: existing admins become superusers
UPDATE users SET is_superuser = 1 WHERE is_admin = 1 AND is_superuser = 0;

-- Rename password_hash → hashed_password is handled by the Python
-- migration in main.py with a proper column-existence guard (SQLite
-- has no IF EXISTS for RENAME COLUMN).

-- AppSettings: new Phase 1 fields
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS registration_open BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS rate_limit_profile TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS dev_mode BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS audit_log_retention_days INTEGER NOT NULL DEFAULT 90;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS audit_log_hide_ip BOOLEAN NOT NULL DEFAULT 0;
