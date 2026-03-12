import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ResetPasswordPage from '../pages/ResetPasswordPage.jsx';

describe('ResetPasswordPage', () => {
  it('routes users to vault recovery flow', () => {
    render(
      <MemoryRouter initialEntries={['/reset-password']}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/reset-password/vault" element={<div>Vault Reset Route</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'Email Reset Is Disabled' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reset With Vault Key' }));
    expect(screen.getByText('Vault Reset Route')).toBeTruthy();
  });
});
