import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import MapCanvasOverlays from '../components/map/MapCanvasOverlays';

describe('MapCanvasOverlays', () => {
  it('renders boundary label and draw hint overlays', () => {
    render(
      <MapCanvasOverlays
        boundaryRenderData={[
          {
            id: 'boundary-1',
            name: 'Prod',
            path: 'M 0 0 L 10 0 L 10 10 Z',
            fill: 'rgba(0,0,0,0.1)',
            stroke: '#ff9900',
            labelScreen: { x: 20, y: 20 },
            flowBBox: { minX: 0, maxX: 10, minY: 0, maxY: 10 },
            behindNodes: false,
          },
        ]}
        selectedBoundaryId={null}
        startBoundaryDrag={vi.fn()}
        startBoundaryResize={vi.fn()}
        openBoundaryContextMenu={vi.fn()}
        viewport={{ x: 0, y: 0, zoom: 1 }}
        visualLines={[]}
        selectedVisualLineId={null}
        setSelectedVisualLineId={vi.fn()}
        openVisualLineContextMenu={vi.fn()}
        startVisualLineDrag={vi.fn()}
        editingBoundaryId={null}
        editingBoundaryName=""
        setEditingBoundaryName={vi.fn()}
        setEditingBoundaryId={vi.fn()}
        commitBoundaryRename={vi.fn()}
        handleBoundaryClick={vi.fn()}
        beginBoundaryRename={vi.fn()}
        mapLabels={[]}
        resolveBoundaryPreset={() => ({ stroke: '#ff9900' })}
        boundaryFillString={() => 'rgba(255,153,0,0.15)'}
        startMapLabelDrag={vi.fn()}
        setMapLabelMenuOpenId={vi.fn()}
        updateMapLabel={vi.fn()}
        removeMapLabel={vi.fn()}
        mapLabelMenuOpenId={null}
        openMapLabelMenuPosition={null}
        labelMenuRef={{ current: null }}
        boundaryDrawMode={false}
        boundaryDraft={null}
        lineDrawMode="ethernet"
        lineDrawDraft={null}
      />
    );

    expect(screen.getByRole('button', { name: 'Prod' })).toBeInTheDocument();
    expect(screen.getByText('Drag on the canvas to draw a ethernet line')).toBeInTheDocument();
  });
});
