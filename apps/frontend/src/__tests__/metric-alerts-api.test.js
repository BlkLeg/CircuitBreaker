import { describe, expect, it, vi, beforeEach } from 'vitest';

// metricAlertsApi lives inside client.jsx, so client.jsx itself is the module
// under test and cannot be vi.mock'ed the way intel-api.test.js mocks the
// transport for ../api/intel. Spying on the real axios instance pins the same
// thing -- the paths -- against the real code, so a path that drifts in
// client.jsx fails here instead of relying on a reviewer's eye.
import client, { metricAlertsApi } from '../api/client.jsx';

vi.spyOn(client, 'get').mockImplementation(() => Promise.resolve({ data: [] }));
vi.spyOn(client, 'post').mockImplementation(() => Promise.resolve({ data: {} }));
vi.spyOn(client, 'put').mockImplementation(() => Promise.resolve({ data: {} }));
vi.spyOn(client, 'delete').mockImplementation(() => Promise.resolve({ data: null }));

beforeEach(() => vi.clearAllMocks());

describe('metricAlertsApi', () => {
  it('reads the metric catalog', () => {
    metricAlertsApi.catalog();
    expect(client.get).toHaveBeenCalledWith('/monitors/alert-rules/catalog');
  });

  it('lists rules', () => {
    metricAlertsApi.list();
    expect(client.get).toHaveBeenCalledWith('/monitors/alert-rules');
  });

  it('gets a rule by id', () => {
    metricAlertsApi.get(7);
    expect(client.get).toHaveBeenCalledWith('/monitors/alert-rules/7');
  });

  it('creates a rule', () => {
    metricAlertsApi.create({ name: 'x' });
    expect(client.post).toHaveBeenCalledWith('/monitors/alert-rules', { name: 'x' });
  });

  it('updates a rule by id', () => {
    metricAlertsApi.update(7, { name: 'x', revision: 2 });
    expect(client.put).toHaveBeenCalledWith('/monitors/alert-rules/7', {
      name: 'x',
      revision: 2,
    });
  });

  it('deletes a rule by id', () => {
    metricAlertsApi.remove(7);
    expect(client.delete).toHaveBeenCalledWith('/monitors/alert-rules/7');
  });

  it('wraps a preview in the request envelope the endpoint expects', () => {
    metricAlertsApi.preview({ name: 'x' }, 3600);
    expect(client.post).toHaveBeenCalledWith('/monitors/alert-rules/preview', {
      rule: { name: 'x' },
      window_seconds: 3600,
    });
  });
});
