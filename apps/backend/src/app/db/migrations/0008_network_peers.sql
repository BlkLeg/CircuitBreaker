-- Migration 0008: Network Peers
-- Introduces a network_peers join table so any two Network rows can be
-- linked as peers (e.g. Docker networks reachable via a shared container,
-- VPN tunnels, or VLAN trunks). The pair is stored with the lower ID first
-- to enforce uniqueness without a function-based constraint.

CREATE TABLE IF NOT EXISTS network_peers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    network_a_id INTEGER NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
    network_b_id INTEGER NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
    relation    TEXT    NOT NULL DEFAULT 'peers_with',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (network_a_id, network_b_id),
    CHECK (network_a_id < network_b_id)
);

CREATE INDEX IF NOT EXISTS ix_network_peers_a ON network_peers(network_a_id);
CREATE INDEX IF NOT EXISTS ix_network_peers_b ON network_peers(network_b_id);
