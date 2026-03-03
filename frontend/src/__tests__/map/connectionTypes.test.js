import { describe, expect, it } from 'vitest';
import {
  computeParticleDuration,
  formatBandwidth,
  isConnectionTyped,
  normalizeConnectionType,
} from '../../components/map/connectionTypes';

describe('connectionTypes helpers', () => {
  it('normalizes legacy wireguard type to wg', () => {
    expect(normalizeConnectionType('wireguard')).toBe('wg');
    expect(normalizeConnectionType('WG')).toBe('wg');
  });

  it('identifies typed and untyped connection values', () => {
    expect(isConnectionTyped('vpn')).toBe(true);
    expect(isConnectionTyped('wireguard')).toBe(true);
    expect(isConnectionTyped('invalid')).toBe(false);
  });

  it('formats bandwidth labels for Mbps and Gbps', () => {
    expect(formatBandwidth(866)).toBe('866M');
    expect(formatBandwidth(1000)).toBe('1G');
    expect(formatBandwidth(1500)).toBe('1.5G');
    expect(formatBandwidth(10000)).toBe('10G');
  });

  it('makes higher bandwidth animate faster (shorter duration)', () => {
    const slow = computeParticleDuration(2.0, 1000);
    const fast = computeParticleDuration(2.0, 10000);
    expect(fast).toBeLessThan(slow);
  });
});
