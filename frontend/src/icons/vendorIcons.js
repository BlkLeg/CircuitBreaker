export const VENDOR_ICON_MAP = {
  amd:        { label: 'AMD',          path: '/icons/vendors/amd-dark.svg' },
  intel:      { label: 'Intel',        path: '/icons/vendors/intel.svg' },
  nvidia:     { label: 'Nvidia',       path: '/icons/vendors/nvidia.svg' },
  arm:        { label: 'ARM',          path: '/icons/vendors/arm.svg' },
  apple:      { label: 'Apple',        path: '/icons/vendors/apple.svg' },
  dell:       { label: 'Dell',         path: '/icons/vendors/dell.svg' },
  hp:         { label: 'HP',           path: '/icons/vendors/hp.svg' },
  lenovo:     { label: 'Lenovo',       path: '/icons/vendors/lenovo.svg' },
  supermicro: { label: 'Supermicro',   path: '/icons/vendors/supermicro.svg' },
  asus:       { label: 'ASUS',         path: '/icons/vendors/asus.svg' },
  gigabyte:   { label: 'Gigabyte',     path: '/icons/vendors/generic.svg' },
  asrock:     { label: 'ASRock',       path: '/icons/vendors/asrock.svg' },
  cisco:      { label: 'Cisco',        path: '/icons/vendors/cisco.svg' },
  ubiquiti:   { label: 'Ubiquiti',     path: '/icons/vendors/ubiquiti.svg' },
  mikrotik:   { label: 'MikroTik',     path: '/icons/vendors/mikrotik-dark.svg' },
  synology:   { label: 'Synology',     path: '/icons/vendors/synology.svg' },
  qnap:       { label: 'QNAP',         path: '/icons/vendors/qnap.svg' },
  proxmox:    { label: 'Proxmox',      path: '/icons/vendors/proxmox-dark.svg' },
  other:      { label: 'Other',        path: '/icons/vendors/generic.svg' },
  // Generic topology icons (auto-attributed by role/type)
  router:   { label: 'Router',               path: '/icons/vendors/router.svg'   },
  switch:   { label: 'Network Switch',       path: '/icons/vendors/switch.svg'   },
  firewall: { label: 'Firewall',             path: '/icons/vendors/firewall.svg' },
  internet: { label: 'Internet / WAN',       path: '/icons/vendors/internet.svg' },
  network:  { label: 'Network Segment',      path: '/icons/vendors/network.svg'  },
  hdd:      { label: 'Hard Drive',           path: '/icons/vendors/hdd.svg'      },
  nas:      { label: 'NAS / Network Storage',path: '/icons/vendors/nas.svg'      },
};

export function getVendorIcon(slug) {
  return VENDOR_ICON_MAP[slug] ?? VENDOR_ICON_MAP['other'];
}
