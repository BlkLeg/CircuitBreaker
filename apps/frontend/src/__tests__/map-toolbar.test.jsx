/**
 * MapToolbar — viewOptions props.
 *
 * MapToolbar's only live reference (map-page.test.jsx) mocks the component
 * away, so nothing exercises the real edge-mode select or label-toggle
 * behavior. This file renders the real component.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import MapToolbar from '../components/MapToolbar.jsx';

describe('MapToolbar viewOptions', () => {
  it('renders link mode selector with smoothstep default', () => {
    render(
      <MapToolbar
        layout="dagre"
        onChange={vi.fn()}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={vi.fn()}
      />
    );

    // Labels toggle button should be visible
    expect(screen.getByTitle('Toggle edge labels')).toBeInTheDocument();

    // Links selector should show
    expect(screen.getByTitle('Edge rendering style')).toBeInTheDocument();
  });

  it('calls onViewOptionsChange when edge mode changes', () => {
    const onChange = vi.fn();
    const onViewOptionsChange = vi.fn();

    render(
      <MapToolbar
        layout="dagre"
        onChange={onChange}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={onViewOptionsChange}
      />
    );

    const edgeModeSelect = screen.getByTitle('Edge rendering style');
    fireEvent.change(edgeModeSelect, { target: { value: 'straight' } });
    expect(onViewOptionsChange).toHaveBeenCalledWith(
      expect.objectContaining({ edgeMode: 'straight' })
    );
  });

  it('toggles edge label visibility on button click', () => {
    const onViewOptionsChange = vi.fn();

    render(
      <MapToolbar
        layout="dagre"
        onChange={vi.fn()}
        viewOptions={{ edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 }}
        onViewOptionsChange={onViewOptionsChange}
      />
    );

    fireEvent.click(screen.getByTitle('Toggle edge labels'));
    expect(onViewOptionsChange).toHaveBeenCalledWith(
      expect.objectContaining({ edgeLabelVisible: false })
    );
  });
});
