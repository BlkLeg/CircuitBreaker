export const HARDWARE_ROLES = [
  { value: 'router',       label: 'Router / Firewall' },
  { value: 'hypervisor',   label: 'Hypervisor' },
  { value: 'server',       label: 'Server' },
  { value: 'nas',          label: 'NAS' },
  { value: 'desktop',      label: 'Desktop' },
  { value: 'workstation',  label: 'Workstation' },
  { value: 'mini_pc',      label: 'Mini PC' },
  { value: 'raspberry_pi', label: 'Raspberry Pi' },
  { value: 'switch',       label: 'Network Switch' },
  { value: 'ap',           label: 'Access Point' },
  { value: 'other',        label: 'Other' },
];

export const HARDWARE_ROLE_LABELS = Object.fromEntries(
  HARDWARE_ROLES.map((r) => [r.value, r.label])
);
