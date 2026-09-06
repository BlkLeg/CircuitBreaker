import { test } from '@playwright/test';
import { stubApi } from './fixtures/api';

const now = new Date().toISOString();

const FS = (mountpoint: string) => ({
  device: '/dev/mapper/fedora-root',
  fs_type: 'btrfs',
  mountpoint,
  read_only: false,
  total_bytes: 1024731513088,
  used_bytes: 350604964124,
  available_bytes: 674126548964,
  used_pct: 34.2119730380465,
});

const TEMPS = [
  ['hwmon0/temp1', 25.3],
  ['hwmon10/temp1', 36],
  ['hwmon4/temp1', 38.85],
  ['hwmon4/temp2', 39.85],
  ['hwmon4/temp3', 38.85],
  ['hwmon7/temp1', 80],
  ['hwmon7/temp2', 53],
  ['hwmon7/temp3', 44],
  ['hwmon7/temp4', 54],
  ['hwmon7/temp5', 25],
  ['hwmon7/temp6', 88],
  ['hwmon7/temp7', 53],
  ['hwmon8/temp1', 44],
  ['hwmon8/temp2', 56],
  ['hwmon8/temp3', 25],
  ['hwmon9/temp1', 81],
  ['hwmon9/temp10', 80],
  ['hwmon9/temp11', 81],
  ['hwmon9/temp12', 88],
  ['hwmon9/temp14', 56],
  ['hwmon9/temp15', 59],
  ['hwmon9/temp16', 59],
].map(([name, temp_c]) => ({ name, temp_c, warning_c: name === 'hwmon0/temp1' ? '' : 95 }));

test('telemetry tab', async ({ page }) => {
  await stubApi(page, {
    agents: [{ id: 1, name: 'branch-office-01', hostname: 'box1', status: 'active' }],
    'agents/1': {
      id: 1,
      name: 'branch-office-01',
      hostname: 'box1',
      status: 'active',
      os: 'linux',
      arch: 'amd64',
      agent_version: '0.8.1',
      fingerprint: 'a'.repeat(32),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      hardware: null,
    },
    'agents/1/events': [],
    'agents/1/telemetry': {
      latest: {
        collected_at: now,
        projected: false,
        summary: {
          cpu_pct: 12.5,
          mem_pct: 41.2,
          root_disk_pct: 34.2,
          net_rx_bps: 20973103,
          net_tx_bps: 1683114,
          max_temp_c: 88,
          load_1: 0.42,
          uptime_s: 273600,
        },
        payload: {
          filesystems: [
            FS('/'),
            FS('/home'),
            FS('/etc/resolv.conf'),
            FS('/etc/circuit-breaker/agent.toml'),
            FS('/var/lib/cb-agent'),
          ],
          disks: [
            {
              device: 'nvme0n1',
              read_bytes: 80438508644,
              write_bytes: 46073867604,
              read_bps: 0,
              write_bps: 51068510308,
            },
            {
              device: 'nvme0n1p1',
              read_bytes: 19144446,
              write_bytes: 1034,
              read_bps: 0,
              write_bps: 0,
            },
            {
              device: 'nvme0n1p2',
              read_bytes: 21277852,
              write_bytes: 68682496,
              read_bps: 0,
              write_bps: 0,
            },
            {
              device: 'zram0',
              read_bytes: 1712138,
              write_bytes: 258048,
              read_bps: 0,
              write_bps: 0,
            },
          ],
          interfaces: [
            {
              name: 'eth0',
              state: 'up',
              speed_mbps: 10000,
              rx_bytes: 20973103,
              tx_bytes: 1683114,
              rx_bps: 4427454,
              tx_bps: 168829000,
              rx_errors: 0,
              tx_errors: 0,
            },
          ],
          temperatures: TEMPS,
        },
      },
      readiness: [
        {
          collector: 'docker',
          state: 'degraded',
          reason: 'the daemon socket is not readable',
          remediation: 'add the agent user to the docker group',
        },
      ],
      capability: { enabled: true, config: { interval_s: 30 } },
      spool: { depth: 42, bytes: 1048576 },
    },
    'agents/1/telemetry/history': {
      points: Array.from({ length: 40 }, (_, i) => ({
        collected_at: new Date(Date.now() - (40 - i) * 90_000).toISOString(),
        summary: {
          cpu_pct: 10 + 30 * Math.abs(Math.sin(i / 4)),
          mem_pct: 38 + i / 6,
          root_disk_pct: 34.2,
          net_rx_bps: 4_000_000 + 9_000_000 * Math.abs(Math.sin(i / 3)),
          max_temp_c: 70 + 18 * Math.abs(Math.sin(i / 5)),
        },
      })),
    },
    'agents/capability-defaults': {
      host_telemetry: {
        enabled: true,
        config: {
          interval_s: 30,
          include_filesystems: true,
          include_disks: true,
          include_interfaces: true,
          include_temperatures: true,
          include_docker: false,
        },
      },
    },
  });

  await page.setViewportSize({ width: 1440, height: 2400 });
  await page.goto('/agents/1?tab=telemetry');
  await page.getByRole('tab', { name: /^Telemetry/ }).click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: '/tmp/telemetry-tab.png', fullPage: true });
});
