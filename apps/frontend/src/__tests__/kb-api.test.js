import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
}));

import client from '../api/client.jsx';
import * as kb from '../api/kb';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('kb api module', () => {
  it('lists OUI entries with params', () => {
    kb.listOui({ source: 'learned', offset: 0, limit: 100 });
    expect(client.get).toHaveBeenCalledWith('/kb/oui', {
      params: { source: 'learned', offset: 0, limit: 100 },
    });
  });

  it('updates an OUI entry by prefix, not by id', () => {
    kb.updateOui('001122', { vendor: 'Acme' });
    expect(client.put).toHaveBeenCalledWith('/kb/oui/001122', { vendor: 'Acme' });
  });

  it('deletes an OUI entry by prefix', () => {
    kb.deleteOui('001122');
    expect(client.delete).toHaveBeenCalledWith('/kb/oui/001122');
  });

  it('updates a hostname entry by numeric id', () => {
    kb.updateHostname(7, { match_type: 'exact' });
    expect(client.put).toHaveBeenCalledWith('/kb/hostname/7', { match_type: 'exact' });
  });

  it('exports each table from its own export route', () => {
    kb.exportOui();
    expect(client.get).toHaveBeenCalledWith('/kb/oui/export');
    kb.exportHostname();
    expect(client.get).toHaveBeenCalledWith('/kb/hostname/export');
  });
});
