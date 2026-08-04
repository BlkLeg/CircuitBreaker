package hostinfo

import "net"

// primaryMACs returns the normalized (net.HardwareAddr.String(), lowercase colon-separated)
// hardware addresses of this host's non-loopback network interfaces, excluding invalid
// addresses. Returns nil rather than erroring if the interface list can't be read (e.g. a
// sandboxed environment without /sys/class/net) — a hello with no MACs is still a valid hello.
func primaryMACs() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	return filterPrimaryMACs(ifaces)
}

// filterPrimaryMACs applies the actual filtering logic against an already-enumerated interface
// list, kept separate from primaryMACs so tests can exercise it against fixture interfaces
// without depending on the host's real network configuration.
func filterPrimaryMACs(ifaces []net.Interface) []string {
	var macs []string
	for _, iface := range ifaces {
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		if !isValidHardwareAddr(iface.HardwareAddr) {
			continue
		}
		macs = append(macs, iface.HardwareAddr.String())
	}
	return macs
}

// isValidHardwareAddr rejects addresses that can't be a real, meaningful primary MAC: absent
// (many virtual/tunnel interfaces report a zero-length HardwareAddr), a length that isn't one of
// the standard EUI-48/EUI-64/InfiniBand widths (malformed), or all-zero (present but
// unconfigured).
func isValidHardwareAddr(addr net.HardwareAddr) bool {
	switch len(addr) {
	case 6, 8, 20:
	default:
		return false
	}
	for _, b := range addr {
		if b != 0 {
			return true
		}
	}
	return false // all-zero
}
