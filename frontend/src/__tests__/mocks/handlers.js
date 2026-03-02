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
    HttpResponse.json({ timezone: 'UTC', theme_preset: 'one-dark', auth_enabled: false })
  ),
];
