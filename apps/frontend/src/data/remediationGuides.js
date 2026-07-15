/**
 * Static remediation guides keyed by remediation_id (matches backend rule
 * catalogs in app/services/privacy_rules.py). Guided instructions only —
 * no fake one-click fixes.
 */
export const REMEDIATION_GUIDES = {
  disable_telnet: {
    title: 'Disable Telnet',
    steps: [
      'Open the device admin interface (web UI or vendor app).',
      'Find remote-management or administration settings.',
      'Disable the Telnet service; enable SSH instead if remote CLI access is needed.',
      'If the device offers no toggle, block TCP port 23 at your router/firewall.',
      'Re-run a discovery scan to confirm the port is closed.',
    ],
    links: [],
  },
  disable_ftp: {
    title: 'Disable FTP',
    steps: [
      'Open the device admin interface.',
      'Locate file-sharing or FTP-server settings.',
      'Disable FTP; prefer SFTP or SMB3 with authentication for file transfer.',
      'Re-run a discovery scan to confirm TCP port 21 is closed.',
    ],
    links: [],
  },
  disable_legacy_smb: {
    title: 'Disable legacy SMB / NetBIOS',
    steps: [
      'On Windows: Control Panel → Programs → Turn Windows features on/off → uncheck "SMB 1.0/CIFS File Sharing Support".',
      'On NAS devices: set the minimum SMB protocol to SMB2 or SMB3 in file-service settings.',
      'Disable NetBIOS over TCP/IP in the adapter’s advanced network settings when not required.',
      'Re-run a discovery scan to confirm ports 137–139 are closed.',
    ],
    links: [],
  },
  disable_upnp: {
    title: 'Disable UPnP',
    steps: [
      'Open your router’s admin interface.',
      'Find UPnP under advanced or NAT settings.',
      'Disable UPnP, then add any needed port-forwards manually.',
      'On media devices, disable DLNA/UPnP services you don’t use.',
      'Re-run a discovery scan to confirm ports 1900/5000 are closed.',
    ],
    links: [],
  },
  captive_portal_info: {
    title: 'Captive portal or connectivity interference',
    steps: [
      'Connectivity probes are being intercepted — common on hotel/guest Wi-Fi.',
      'If this is your home network, check the router for a guest-portal feature that may be enabled.',
      'If interception persists on a trusted network, inspect upstream proxy or ISP equipment.',
      'Consider a VPN so traffic is opaque to the intercepting device.',
    ],
    links: [{ label: 'Windscribe VPN', url: 'https://windscribe.com' }],
  },
  dns_tamper_response: {
    title: 'Respond to DNS tampering',
    steps: [
      'Known-stable DNS answers are being rewritten on this network — treat it as hostile.',
      'Check your router’s DNS settings for unexpected upstream servers and reset them.',
      'Change the router admin password; DNS hijacking often follows a compromised router.',
      'Switch devices to a trusted encrypted resolver (DoH/DoT such as 1.1.1.1 or Control D).',
      'Re-check this page after the change — the alert clears when canary answers match again.',
    ],
    links: [{ label: 'Control D setup', url: 'https://controld.com' }],
  },
  setup_dns_filtering: {
    title: 'Add DNS-level malware filtering',
    steps: [
      'Your network resolves known-malicious domains — a filtering resolver blocks these for every device at once.',
      'Option A: point your router’s DNS at Control D or Windscribe’s R.O.B.E.R.T. filtering resolver.',
      'Option B: run a local filter (Pi-hole/AdGuard Home) and use it as the router’s DNS.',
      'Verify afterwards: this finding clears when sampled malware domains stop resolving.',
    ],
    links: [
      { label: 'Windscribe R.O.B.E.R.T.', url: 'https://windscribe.com/features/robert' },
      { label: 'Control D free DNS', url: 'https://controld.com/free-dns' },
    ],
  },
};

export function getRemediationGuide(remediationId) {
  return REMEDIATION_GUIDES[remediationId] || null;
}
