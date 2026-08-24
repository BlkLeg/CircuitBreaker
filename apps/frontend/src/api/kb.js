import client from './client.jsx';

// Knowledge-base lookup tables that feed discovery naming (INC-11).
// Both tables are admin-only (`require_role("admin")` on every route in
// app/api/kb.py) and paginate server-side at limit <= 500.

// ── MAC OUI prefixes ─────────────────────────────────────────────────────────
// Keyed by `prefix` (String(6) primary key), NOT by a surrogate id — there is
// no `id` column on kb_oui.
export const listOui = (params = {}) => client.get('/kb/oui', { params });
export const createOui = (body) => client.post('/kb/oui', body);
export const updateOui = (prefix, body) => client.put(`/kb/oui/${prefix}`, body);
export const deleteOui = (prefix) => client.delete(`/kb/oui/${prefix}`);
export const exportOui = () => client.get('/kb/oui/export');

// ── Hostname patterns ────────────────────────────────────────────────────────
export const listHostname = (params = {}) => client.get('/kb/hostname', { params });
export const createHostname = (body) => client.post('/kb/hostname', body);
export const updateHostname = (id, body) => client.put(`/kb/hostname/${id}`, body);
export const deleteHostname = (id) => client.delete(`/kb/hostname/${id}`);
export const exportHostname = () => client.get('/kb/hostname/export');
