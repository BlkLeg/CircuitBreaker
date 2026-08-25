import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ForgotPasswordModal from '../components/auth/ForgotPasswordModal.jsx';
import ResetPasswordPage from '../pages/ResetPasswordPage.jsx';
import { PASSWORD_RECOVERY_MESSAGE } from '../api/auth';

/**
 * INC-08. Self-service password reset is disabled and is not coming back for 1.0.0, so
 * the two surfaces that say so have to say the same thing — and it has to be something a
 * locked-out user can act on. "Temporarily disabled" was neither: it named no path and
 * promised a return.
 *
 * Both surfaces read one exported string. Two surfaces answering the same question
 * differently is the shape of INC-02 and INC-03.
 */

vi.mock('../api/client', () => ({ default: { post: vi.fn(), get: vi.fn() } }));

const inRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('the password recovery message', () => {
  it('names the administrator path, not just the vault key', () => {
    expect(PASSWORD_RECOVERY_MESSAGE.toLowerCase()).toContain('administrator');
    expect(PASSWORD_RECOVERY_MESSAGE.toLowerCase()).toContain('vault key');
  });

  it('does not promise the feature is coming back', () => {
    expect(PASSWORD_RECOVERY_MESSAGE.toLowerCase()).not.toContain('temporarily');
  });

  it('is what the forgot-password modal renders', () => {
    inRouter(<ForgotPasswordModal isOpen onClose={() => {}} />);

    expect(screen.getByText(PASSWORD_RECOVERY_MESSAGE)).toBeTruthy();
  });

  it('is what the reset-password page renders', () => {
    inRouter(<ResetPasswordPage />);

    expect(screen.getByText(PASSWORD_RECOVERY_MESSAGE)).toBeTruthy();
  });

  it('both surfaces still offer the vault-key route out', () => {
    const { unmount } = inRouter(<ResetPasswordPage />);
    expect(screen.getByRole('button', { name: /vault key/i })).toBeTruthy();
    unmount();

    inRouter(<ForgotPasswordModal isOpen onClose={() => {}} />);
    expect(screen.getByRole('button', { name: /vault key/i })).toBeTruthy();
  });
});
