-- Migration 0007: Docker Network Topology
-- Adds Docker-specific columns to networks, services, and app_settings tables.
-- Safe to re-run idempotently with IF NOT EXISTS guards.

-- Docker network columns on networks table
ALTER TABLE networks ADD COLUMN IF NOT EXISTS docker_network_id TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS docker_driver TEXT;
ALTER TABLE networks ADD COLUMN IF NOT EXISTS is_docker_network INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_networks_docker_network_id
    ON networks(docker_network_id) WHERE docker_network_id IS NOT NULL;

-- Docker container columns on services table
ALTER TABLE services ADD COLUMN IF NOT EXISTS docker_container_id TEXT;
ALTER TABLE services ADD COLUMN IF NOT EXISTS docker_image TEXT;
ALTER TABLE services ADD COLUMN IF NOT EXISTS is_docker_container INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_services_docker_container_id
    ON services(docker_container_id) WHERE docker_container_id IS NOT NULL;

-- Docker discovery + graph layout settings
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS docker_socket_path TEXT NOT NULL DEFAULT '/var/run/docker.sock';
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS docker_sync_interval_minutes INTEGER NOT NULL DEFAULT 5;
ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS graph_default_layout TEXT NOT NULL DEFAULT 'dagre';
