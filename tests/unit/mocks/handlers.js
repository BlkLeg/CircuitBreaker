import { http, HttpResponse } from 'msw';

const BASE = '/api/v1';

export const handlers = [
  // Categories
  http.get(`${BASE}/categories`, () =>
    HttpResponse.json([])
  ),
  http.post(`${BASE}/categories`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      { id: 1, name: body.name, color: body.color ?? null, service_count: 0, created_at: new Date().toISOString() },
      { status: 201 }
    );
  }),

  // Environments
  http.get(`${BASE}/environments`, () =>
    HttpResponse.json([])
  ),
  http.post(`${BASE}/environments`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      { id: 1, name: body.name, color: body.color ?? null, usage_count: 0, created_at: new Date().toISOString() },
      { status: 201 }
    );
  }),

  // IP check — clean by default
  http.post(`${BASE}/ip-check`, () =>
    HttpResponse.json({ conflicts: [] })
  ),

  // Timezones
  http.get(`${BASE}/timezones`, () =>
    HttpResponse.json({
      timezones: [
        'Africa/Abidjan', 'America/Denver', 'America/New_York',
        'Asia/Tokyo', 'Europe/London', 'Pacific/Auckland', 'UTC',
      ],
    })
  ),

  // Logs
  http.get(`${BASE}/logs`, () =>
    HttpResponse.json({ logs: [], total_count: 0, has_more: false })
  ),
  http.get(`${BASE}/logs/actions`, () =>
    HttpResponse.json({ actions: ['created', 'updated', 'deleted', 'login_failed'] })
  ),

  // Settings
  http.get(`${BASE}/settings`, () =>
    HttpResponse.json({
      timezone: 'UTC', theme_preset: 'one-dark', auth_enabled: true,
      scan_ack_accepted: false,
      discovery_enabled: false,
      discovery_auto_merge: false,
      discovery_default_cidr: '192.168.1.0/24',
      discovery_nmap_args: '-sV -O --open -T4',
      discovery_http_probe: true,
      discovery_retention_days: 30,
    })
  ),
  http.put(`${BASE}/settings`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({ ...body });
  }),

  // Discovery — profiles
  http.get(`${BASE}/discovery/profiles`, () =>
    HttpResponse.json([
      { id: 1, name: 'Home LAN', cidr: '192.168.1.0/24', scan_types: ['nmap','snmp'],
        nmap_arguments: '-sV', snmp_version: '2c', snmp_port: 161,
        schedule_cron: null, enabled: true, last_run: null,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ])
  ),
  http.post(`${BASE}/discovery/profiles`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      { id: 2, ...body, scan_types: body.scan_types ?? ['nmap'],
        snmp_version: body.snmp_version ?? '2c', snmp_port: body.snmp_port ?? 161,
        enabled: body.enabled ?? true, last_run: null,
        created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { status: 201 }
    );
  }),
  http.patch(`${BASE}/discovery/profiles/:id`, async ({ params, request }) => {
    const body = await request.json();
    return HttpResponse.json({ id: Number(params.id), ...body });
  }),
  http.delete(`${BASE}/discovery/profiles/:id`, () =>
    new HttpResponse(null, { status: 204 })
  ),
  http.post(`${BASE}/discovery/profiles/:id/run`, () =>
    HttpResponse.json({ id: 99, target_cidr: '192.168.1.0/24', status: 'queued',
      scan_types_json: '["nmap"]', hosts_found: 0, hosts_new: 0,
      hosts_updated: 0, hosts_conflict: 0, created_at: new Date().toISOString() })
  ),

  // Discovery — ad-hoc scan
  http.post(`${BASE}/discovery/scan`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({ id: 42, target_cidr: body.cidr, status: 'queued',
      scan_types_json: JSON.stringify(body.scan_types ?? ['nmap']),
      hosts_found: 0, hosts_new: 0, hosts_updated: 0, hosts_conflict: 0,
      created_at: new Date().toISOString() });
  }),

  // Discovery — jobs
  http.get(`${BASE}/discovery/jobs`, () =>
    HttpResponse.json({ jobs: [] })
  ),
  http.get(`${BASE}/discovery/jobs/:id`, ({ params }) =>
    HttpResponse.json({ id: Number(params.id), status: 'done', target_cidr: '192.168.1.0/24',
      scan_types_json: '["nmap"]', hosts_found: 3, hosts_new: 2, hosts_updated: 1,
      hosts_conflict: 0, created_at: new Date().toISOString() })
  ),
  http.delete(`${BASE}/discovery/jobs/:id`, () =>
    new HttpResponse(null, { status: 204 })
  ),
  http.get(`${BASE}/discovery/jobs/:id/results`, () =>
    HttpResponse.json({ results: [] })
  ),

  // Discovery — results
  http.get(`${BASE}/discovery/results`, () =>
    HttpResponse.json({ results: [], total: 0 })
  ),
  http.get(`${BASE}/discovery/results/:id`, ({ params }) =>
    HttpResponse.json({ id: Number(params.id), ip_address: '10.0.0.5',
      state: 'new', merge_status: 'pending', open_ports_json: null,
      created_at: new Date().toISOString() })
  ),
  http.post(`${BASE}/discovery/results/:id/merge`, async ({ request }) => {
    const body = await request.json();
    if (body.action === 'reject') return HttpResponse.json({ rejected: true });
    return HttpResponse.json({
      entity_type: 'hardware', entity_id: 101, name: 'test-host',
      ports: [
        { port: 22, protocol: 'tcp', suggested_name: 'SSH', suggested_category: 'infrastructure' },
        { port: 443, protocol: 'tcp', suggested_name: 'HTTPS', suggested_category: 'web' },
      ],
    });
  }),
  http.post(`${BASE}/discovery/results/bulk-merge`, async ({ request }) => {
    const body = await request.json();
    const count = body.result_ids?.length ?? 0;
    if (body.action === 'reject') return HttpResponse.json({ accepted: 0, rejected: count, skipped: 0 });
    return HttpResponse.json({ accepted: count, rejected: 0, skipped: 0 });
  }),

  // Discovery — status
  http.get(`${BASE}/discovery/status`, () =>
    HttpResponse.json({ pending_results: 3, running_jobs: 0 })
  ),

  // Services (for ServiceChecklistModal)
  http.post(`${BASE}/services`, async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({ id: 201, ...body }, { status: 201 });
  }),
];
