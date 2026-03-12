import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import FormModal from '../components/common/FormModal.jsx';

vi.mock('../components/EntityForm', () => ({
  __esModule: true,
  default: () => <div data-testid="entity-form" />,
}));

describe('FormModal', () => {
  it('does not apply aria-hidden to active modal overlay', () => {
    const { container } = render(
      <FormModal
        open
        title="Test Modal"
        fields={[]}
        initialValues={{}}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByTestId('entity-form')).toBeInTheDocument();

    const overlay = container.querySelector('.modal-overlay');
    const dialog = container.querySelector('dialog.modal');

    expect(overlay).not.toBeNull();
    expect(overlay).not.toHaveAttribute('aria-hidden');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });
});
