import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import EntityPicker from '../components/common/EntityPicker';

vi.mock('../api/client', () => ({
  inventoryApi: {
    options: vi.fn(),
  },
}));

import { inventoryApi } from '../api/client';

describe('EntityPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    inventoryApi.options.mockResolvedValue({
      data: {
        items: [
          {
            ref: { entity_type: 'hardware', entity_id: 1, key: 'hardware:1' },
            label: 'pve-01',
            description: 'Server',
            available: true,
          },
        ],
        selected: [],
        has_more: false,
        limit: 25,
      },
    });
  });

  it('searches options and selects a result', async () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<EntityPicker isOpen onClose={onClose} onSelect={onSelect} types={['hardware']} />);

    expect(await screen.findByText('pve-01')).toBeInTheDocument();
    expect(inventoryApi.options).toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Search every page/i), { target: { value: 'pve' } });
    await waitFor(() =>
      expect(inventoryApi.options).toHaveBeenCalledWith(
        expect.objectContaining({ q: 'pve', types: ['hardware'] })
      )
    );

    fireEvent.click(screen.getByText('pve-01'));
    expect(onSelect).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});
