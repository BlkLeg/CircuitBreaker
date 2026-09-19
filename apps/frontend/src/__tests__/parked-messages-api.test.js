import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// The real module, with the axios instance spied on — not a mock that restates
// the paths it claims to verify. A test that redefines the code under test
// cannot fail when that code is wrong.
import client, { failedMessagesApi } from '../api/client.jsx';

beforeEach(() => {
  vi.spyOn(client, 'get').mockResolvedValue({ data: [] });
  vi.spyOn(client, 'post').mockResolvedValue({ data: {} });
});

afterEach(() => vi.restoreAllMocks());

describe('failedMessagesApi', () => {
  it('lists a page of parked messages', () => {
    failedMessagesApi.list({ include_resolved: false, limit: 100, offset: 0 });

    expect(client.get).toHaveBeenCalledWith('/failed-messages', {
      params: { include_resolved: false, limit: 100, offset: 0 },
    });
  });

  it('requeues by id', () => {
    failedMessagesApi.requeue(7);

    expect(client.post).toHaveBeenCalledWith('/failed-messages/7/requeue');
  });

  it('discards by id', () => {
    failedMessagesApi.discard(7);

    expect(client.post).toHaveBeenCalledWith('/failed-messages/7/discard');
  });
});
