package hostinfo

import (
	"net"
	"reflect"
	"testing"
)

func TestFilterPrimaryMACs(t *testing.T) {
	tests := []struct {
		name   string
		ifaces []net.Interface
		want   []string
	}{
		{
			name: "single normal interface is normalized to lowercase colon form",
			ifaces: []net.Interface{
				{Name: "eth0", HardwareAddr: net.HardwareAddr{0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}},
			},
			want: []string{"aa:bb:cc:dd:ee:ff"},
		},
		{
			name: "loopback-only: the loopback interface's MAC is excluded",
			ifaces: []net.Interface{
				{Name: "lo", Flags: net.FlagLoopback, HardwareAddr: net.HardwareAddr{0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
			},
			want: nil,
		},
		{
			name: "loopback alongside a real interface: only the real one is kept",
			ifaces: []net.Interface{
				{Name: "lo", Flags: net.FlagLoopback, HardwareAddr: net.HardwareAddr{0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
				{Name: "eth0", HardwareAddr: net.HardwareAddr{0x02, 0x42, 0xac, 0x11, 0x00, 0x02}},
			},
			want: []string{"02:42:ac:11:00:02"},
		},
		{
			name:   "no interfaces at all",
			ifaces: nil,
			want:   nil,
		},
		{
			name: "no MACs: every interface has an absent (zero-length) hardware address",
			ifaces: []net.Interface{
				{Name: "tun0", HardwareAddr: nil},
				{Name: "wg0", HardwareAddr: net.HardwareAddr{}},
			},
			want: nil,
		},
		{
			name: "malformed: hardware address length isn't a valid MAC width",
			ifaces: []net.Interface{
				{Name: "weird0", HardwareAddr: net.HardwareAddr{0x01, 0x02, 0x03}},                         // 3 bytes
				{Name: "weird1", HardwareAddr: net.HardwareAddr{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07}}, // 7 bytes
			},
			want: nil,
		},
		{
			name: "all-zero hardware address is excluded even though the length is valid",
			ifaces: []net.Interface{
				{Name: "dummy0", HardwareAddr: net.HardwareAddr{0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
			},
			want: nil,
		},
		{
			name: "EUI-64 (8-byte) and InfiniBand (20-byte) widths are accepted",
			ifaces: []net.Interface{
				{Name: "eui64", HardwareAddr: net.HardwareAddr{0x02, 0x42, 0xac, 0x11, 0x00, 0x02, 0x00, 0x01}},
				{Name: "ib0", HardwareAddr: net.HardwareAddr{
					0x80, 0x00, 0x02, 0x08, 0xfe, 0x80, 0x00, 0x00, 0x00, 0x00,
					0x00, 0x00, 0x00, 0x02, 0xc9, 0x03, 0x00, 0x00, 0x13, 0x17,
				}},
			},
			want: []string{
				"02:42:ac:11:00:02:00:01",
				"80:00:02:08:fe:80:00:00:00:00:00:00:00:02:c9:03:00:00:13:17",
			},
		},
		{
			name: "mix of loopback, no-MAC, malformed, and one valid interface",
			ifaces: []net.Interface{
				{Name: "lo", Flags: net.FlagLoopback, HardwareAddr: net.HardwareAddr{0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
				{Name: "tun0", HardwareAddr: nil},
				{Name: "weird0", HardwareAddr: net.HardwareAddr{0x01, 0x02, 0x03}},
				{Name: "eth0", HardwareAddr: net.HardwareAddr{0x00, 0x1a, 0x2b, 0x3c, 0x4d, 0x5e}},
			},
			want: []string{"00:1a:2b:3c:4d:5e"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := filterPrimaryMACs(tt.ifaces)
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("filterPrimaryMACs() = %#v, want %#v", got, tt.want)
			}
		})
	}
}

func TestPrimaryMACs_RealHost(t *testing.T) {
	// Smoke test only: exercises the real net.Interfaces() path without asserting on specific
	// hardware, since CI/dev environments vary. It must not panic or error.
	got := primaryMACs()
	for _, mac := range got {
		if _, err := net.ParseMAC(mac); err != nil {
			t.Errorf("primaryMACs() returned non-parseable MAC %q: %v", mac, err)
		}
	}
}
