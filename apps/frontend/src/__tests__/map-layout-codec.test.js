/**
 * Versioned layout codec.
 *
 * A saved layout is a self-hoster's map. Three shapes exist in the wild: the
 * legacy flat node-position map, the current structured document with no
 * version marker, and the versioned document this codec writes.
 */
import { describe, expect, it } from 'vitest';
import { decodeLayout, encodeLayout, LAYOUT_SCHEMA_VERSION } from '../utils/layoutCodec';

const DOC = {
  nodes: { 'hw-1': { x: 1, y: 2 } },
  nodeShapes: { 'hw-1': 'circle' },
  edges: { 'e-1': { sourceSide: 'left' } },
  boundaries: [{ id: 'b-1', name: 'Rack' }],
  labels: [{ id: 'l-1', text: 'Closet' }],
  visualLines: [{ id: 'v-1', lineType: 'fiber' }],
  edgeMode: 'straight',
  edgeLabelVisible: false,
  nodeSpacing: 2,
  groupBy: 'environment',
};

describe('decodeLayout', () => {
  it('reads a legacy flat node-position map', () => {
    const decoded = decodeLayout({ 'hw-1': { x: 10, y: 20 } });

    expect(decoded.nodes).toEqual({ 'hw-1': { x: 10, y: 20 } });
    expect(decoded.edgeMode).toBe('smoothstep');
  });

  it('reads an unversioned structured document', () => {
    const decoded = decodeLayout(DOC);

    expect(decoded.nodes).toEqual(DOC.nodes);
    expect(decoded.edgeMode).toBe('straight');
    expect(decoded.edgeLabelVisible).toBe(false);
  });

  it('reads a versioned document with nested view options', () => {
    const decoded = decodeLayout({
      schemaVersion: 2,
      nodes: DOC.nodes,
      view: { edgeMode: 'step', edgeLabelVisible: false, nodeSpacing: 3, groupBy: 'type' },
    });

    expect(decoded.edgeMode).toBe('step');
    expect(decoded.nodeSpacing).toBe(3);
    expect(decoded.groupBy).toBe('type');
  });

  it('prefers nested view options over the flat mirror', () => {
    const decoded = decodeLayout({
      schemaVersion: 2,
      nodes: {},
      edgeMode: 'smoothstep',
      view: { edgeMode: 'step' },
    });

    expect(decoded.edgeMode).toBe('step');
  });

  it('parses a JSON string identically to the object', () => {
    expect(decodeLayout(JSON.stringify(DOC))).toEqual(decodeLayout(DOC));
  });

  it('coerces a non-array visualLines to an empty array', () => {
    expect(decodeLayout({ ...DOC, visualLines: { bogus: true } }).visualLines).toEqual([]);
  });
});

describe('encodeLayout', () => {
  it('stamps the schema version and nests the view options', () => {
    const encoded = encodeLayout(DOC);

    expect(encoded.schemaVersion).toBe(LAYOUT_SCHEMA_VERSION);
    expect(encoded.view).toEqual({
      edgeMode: 'straight',
      edgeLabelVisible: false,
      nodeSpacing: 2,
      groupBy: 'environment',
    });
  });

  it('also writes the view options flat, so an older frontend still reads them', () => {
    const encoded = encodeLayout(DOC);

    // Backward compatibility: a self-hoster may run a rebuilt frontend against
    // a server they have not restarted, or roll back. An older parser looks for
    // these at the top level and would otherwise silently reset the user's view.
    expect(encoded.edgeMode).toBe('straight');
    expect(encoded.edgeLabelVisible).toBe(false);
    expect(encoded.nodeSpacing).toBe(2);
    expect(encoded.groupBy).toBe('environment');
  });

  it('round-trips a document without loss', () => {
    expect(decodeLayout(encodeLayout(DOC))).toEqual(decodeLayout(DOC));
  });

  it('round-trips through JSON', () => {
    expect(decodeLayout(JSON.stringify(encodeLayout(DOC)))).toEqual(decodeLayout(DOC));
  });
});
