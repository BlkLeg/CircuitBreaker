// Common OS brands for the Compute Units OS dropdown.
// `icon` maps to a file in /icons/vendors/
export const OS_OPTIONS = [
  { value: 'ubuntu',          label: 'Ubuntu',              icon: '/icons/vendors/ubuntu-linux.svg' },
  { value: 'debian',          label: 'Debian',              icon: '/icons/vendors/debian-linux.svg' },
  { value: 'alpine',          label: 'Alpine Linux',        icon: '/icons/vendors/alpine-linux.svg' },
  { value: 'arch',            label: 'Arch Linux',          icon: '/icons/vendors/arch-linux.svg' },
  { value: 'fedora',          label: 'Fedora',              icon: '/icons/vendors/fedora.svg' },
  { value: 'linux',           label: 'Linux (Generic)',     icon: '/icons/vendors/linux.svg' },
  { value: 'proxmox',         label: 'Proxmox VE',         icon: '/icons/vendors/proxmox-dark.svg' },
  { value: 'truenas',         label: 'TrueNAS',             icon: '/icons/vendors/truenas.svg' },
  { value: 'openmediavault',  label: 'OpenMediaVault',     icon: '/icons/vendors/openmediavault.svg' },
  { value: 'xcp-ng',          label: 'XCP-ng',              icon: '/icons/vendors/xcp-ng.svg' },
  { value: 'vmware-esxi',     label: 'VMware ESXi',        icon: '/icons/vendors/vmware-esxi.svg' },
  { value: 'docker',          label: 'Docker',              icon: '/icons/vendors/docker.svg' },
  { value: 'windows-server',  label: 'Windows Server',     icon: '/icons/vendors/generic.svg' },
  { value: 'apple',           label: 'macOS / Darwin',     icon: '/icons/vendors/apple.svg' },
  { value: 'freebsd',         label: 'FreeBSD',             icon: '/icons/vendors/generic.svg' },
  { value: 'other',           label: 'Other / Custom',     icon: '/icons/vendors/generic.svg' },
];

export function getOsOption(value) {
  return OS_OPTIONS.find((o) => o.value === value) ?? OS_OPTIONS[OS_OPTIONS.length - 1];
}
