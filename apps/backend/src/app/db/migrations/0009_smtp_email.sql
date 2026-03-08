-- Migration 0009: SMTP configuration and invite email tracking
-- Adds SMTP delivery settings to app_settings and email status columns to user_invites.

-- SMTP configuration on app_settings
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_host TEXT NOT NULL DEFAULT '';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_port INTEGER NOT NULL DEFAULT 587;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_username TEXT NOT NULL DEFAULT '';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_password_enc TEXT;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_from_email TEXT NOT NULL DEFAULT '';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_from_name TEXT NOT NULL DEFAULT 'Circuit Breaker';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_tls INTEGER NOT NULL DEFAULT 1;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_last_test_at TEXT;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS smtp_last_test_status TEXT;

-- Email delivery tracking on user_invites
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS email_sent_at TEXT;
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS email_status TEXT NOT NULL DEFAULT 'not_sent';
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS email_error TEXT;
