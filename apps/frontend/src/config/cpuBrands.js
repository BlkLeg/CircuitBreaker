export const CPU_BRANDS = [
  { value: 'intel', label: 'Intel', icon: '/icons/vendors/intel.svg' },
  { value: 'amd', label: 'AMD', icon: '/icons/vendors/amd-logo.svg' },
  { value: 'amd_ryzen', label: 'AMD Ryzen', icon: '/icons/vendors/ryzen.svg' },
];

export const CPU_BRAND_MAP = Object.fromEntries(CPU_BRANDS.map((b) => [b.value, b]));
