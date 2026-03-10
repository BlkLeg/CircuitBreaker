-- Migration 0006: Docker Network Enhancement
-- Adds Docker network configuration fields to DiscoveryProfile table for enhanced
-- Docker network topology scanning, port discovery, and network type filtering.
-- Safe to re-run idempotently with IF NOT EXISTS guards.

-- Docker network configuration columns
ALTER TABLE discovery_profiles ADD COLUMN IF NOT EXISTS docker_network_types TEXT NOT NULL DEFAULT '["bridge"]';
ALTER TABLE discovery_profiles ADD COLUMN IF NOT EXISTS docker_port_scan INTEGER NOT NULL DEFAULT 0;
ALTER TABLE discovery_profiles ADD COLUMN IF NOT EXISTS docker_socket_path TEXT NOT NULL DEFAULT '/var/run/docker.sock';