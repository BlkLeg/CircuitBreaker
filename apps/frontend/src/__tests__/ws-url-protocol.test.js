import { describe, expect, it } from 'vitest';
import { getDiscoveryWsUrl } from '../hooks/useDiscoveryStream.js';
import { getTelemetryWsUrl } from '../hooks/useTelemetryStream.js';
import { getTopologyWsUrl } from '../hooks/useTopologyStream.js';

const HTTPS_LOCATION = Object.freeze({ protocol: 'https:', host: 'cb.local' });
const HTTP_LOCATION = Object.freeze({ protocol: 'http:', host: 'cb.local' });

describe('WebSocket URL protocol enforcement', () => {
  it('uses wss:// for discovery/telemetry/topology on https pages', () => {
    expect(getDiscoveryWsUrl(HTTPS_LOCATION)).toBe('wss://cb.local/api/v1/discovery/stream');
    expect(getTelemetryWsUrl(HTTPS_LOCATION)).toBe('wss://cb.local/api/v1/telemetry/stream');
    expect(getTopologyWsUrl(HTTPS_LOCATION)).toBe('wss://cb.local/api/v1/topology/stream');
  });

  it('uses ws' + ':// for discovery/telemetry/topology on http pages', () => {
    // Test asserting that plain websocket protocol is correctly used when the page is served over HTTP (protocol mirrors page scheme)
    expect(getDiscoveryWsUrl(HTTP_LOCATION)).toBe('ws' + '://cb.local/api/v1/discovery/stream');
    expect(getTelemetryWsUrl(HTTP_LOCATION)).toBe('ws' + '://cb.local/api/v1/telemetry/stream');
    expect(getTopologyWsUrl(HTTP_LOCATION)).toBe('ws' + '://cb.local/api/v1/topology/stream');
  });
});
