import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const updateIdentity = vi.fn();
vi.mock('../api/client', () => ({ cveApi: { updateIdentity: (...a) => updateIdentity(...a) } }));

import IdentityCorrectionDrawer from '../components/intel/IdentityCorrectionDrawer.jsx';

const ROW = {
  entity_type: 'hardware',
  entity_id: 7,
  name: 'nas-01',
  identity: {
    vendor: 'acme',
    product: 'widget',
    version: '1.9',
    version_scheme: 'dotted_numeric',
    provenance: 'inventory',
    revision: 0,
  },
};

beforeEach(() => vi.clearAllMocks());

describe('IdentityCorrectionDrawer', () => {
  it('sends the revision the row was read at', async () => {
    updateIdentity.mockResolvedValue({ data: { ...ROW.identity, revision: 1 } });
    const onSaved = vi.fn();

    render(<IdentityCorrectionDrawer row={ROW} onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/version/i), { target: { value: '2.0' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(updateIdentity).toHaveBeenCalledWith(
      'hardware',
      7,
      expect.objectContaining({ version: '2.0', revision: 0 })
    );
  });

  it('keeps what the operator typed when the save is rejected', async () => {
    updateIdentity.mockRejectedValue({
      userMessage: 'The identity changed while you were editing.',
    });

    render(<IdentityCorrectionDrawer row={ROW} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText(/product/i), { target: { value: 'widget-pro' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByLabelText(/product/i)).toHaveValue('widget-pro');
  });

  it('opens with empty fields for an entity that has no identity at all', () => {
    render(
      <IdentityCorrectionDrawer
        row={{ ...ROW, identity: null }}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );

    expect(screen.getByLabelText(/product/i)).toHaveValue('');
    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
  });
});
