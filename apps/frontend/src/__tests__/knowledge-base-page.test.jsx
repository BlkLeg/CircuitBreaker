import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../components/kb/KbTable.jsx', () => ({
  default: ({ tab }) => <div data-testid="kb-table">{tab.key}</div>,
}));

import KnowledgeBasePage from '../pages/KnowledgeBasePage.jsx';

describe('KnowledgeBasePage', () => {
  it('shows the OUI tab first', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByTestId('kb-table')).toHaveTextContent('oui');
  });

  it('switches to the hostname tab', () => {
    render(<KnowledgeBasePage />);
    fireEvent.click(screen.getByRole('tab', { name: /hostname patterns/i }));
    expect(screen.getByTestId('kb-table')).toHaveTextContent('hostname');
  });

  it('marks the active tab for assistive technology', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByRole('tab', { name: /mac oui prefixes/i })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  it('renders its own heading when not embedded', () => {
    render(<KnowledgeBasePage />);
    expect(screen.getByRole('heading', { name: /knowledge base/i })).toBeInTheDocument();
  });

  it('omits the heading when embedded in Settings', () => {
    render(<KnowledgeBasePage embedded />);
    expect(screen.queryByRole('heading', { name: /knowledge base/i })).not.toBeInTheDocument();
  });
});
