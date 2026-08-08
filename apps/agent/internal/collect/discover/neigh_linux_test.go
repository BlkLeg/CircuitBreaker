//go:build linux

package discover

import (
	"context"
	"encoding/binary"
	"errors"
	"net/netip"
	"testing"

	"golang.org/x/sys/unix"
)

// The fixtures below are assembled from the kernel ABI rather than captured from a live host on
// purpose: a real `ip neigh` dump carries the contributor's own LAN addresses and hardware
// addresses, and committing those would put someone's home network in the repository forever.
// Everything a capture would prove — native byte order, 4-byte attribute padding, multi-part
// framing — is reproduced here byte for byte.

// neighAttr is one rtattr to place after the ndmsg header.
type neighAttr struct {
	typ  uint16
	data []byte
}

// buildNeighMsg encodes one RTM_NEWNEIGH message exactly as the kernel writes it: a 16-byte
// nlmsghdr, a 12-byte ndmsg, then rtattrs each padded up to a 4-byte boundary. msgType is a
// parameter so the error and end-of-dump messages share the framing code with the payload ones.
func buildNeighMsg(msgType uint16, family uint8, state uint16, attrs ...neighAttr) []byte {
	body := make([]byte, unix.SizeofNdMsg)
	body[0] = family
	binary.NativeEndian.PutUint32(body[4:8], 3) // Ifindex; nothing reads it, but the kernel sets it
	binary.NativeEndian.PutUint16(body[8:10], state)
	for _, a := range attrs {
		hdr := make([]byte, unix.SizeofRtAttr)
		binary.NativeEndian.PutUint16(hdr[0:2], uint16(unix.SizeofRtAttr+len(a.data)))
		binary.NativeEndian.PutUint16(hdr[2:4], a.typ)
		body = append(body, hdr...)
		body = append(body, a.data...)
		for len(body)%unix.RTA_ALIGNTO != 0 {
			body = append(body, 0)
		}
	}
	return wrapNlMsg(msgType, body)
}

// wrapNlMsg prefixes a netlink message header declaring the true total length.
func wrapNlMsg(msgType uint16, body []byte) []byte {
	msg := make([]byte, unix.SizeofNlMsghdr, unix.SizeofNlMsghdr+len(body))
	binary.NativeEndian.PutUint32(msg[0:4], uint32(unix.SizeofNlMsghdr+len(body)))
	binary.NativeEndian.PutUint16(msg[4:6], msgType)
	binary.NativeEndian.PutUint16(msg[6:8], unix.NLM_F_MULTI)
	binary.NativeEndian.PutUint32(msg[8:12], 1)  // Seq
	binary.NativeEndian.PutUint32(msg[12:16], 0) // Pid: the kernel
	return append(msg, body...)
}

func doneMsg() []byte {
	body := make([]byte, 4) // NLMSG_DONE carries the dump's exit status
	return wrapNlMsg(unix.NLMSG_DONE, body)
}

func errMsg(errno int32) []byte {
	body := make([]byte, unix.SizeofNlMsgerr)
	binary.NativeEndian.PutUint32(body[0:4], uint32(errno))
	return wrapNlMsg(unix.NLMSG_ERROR, body)
}

func mustAddr(t *testing.T, s string) netip.Addr {
	t.Helper()
	a, err := netip.ParseAddr(s)
	if err != nil {
		t.Fatalf("bad test address %q: %v", s, err)
	}
	return a
}

func TestParseNeighborDump(t *testing.T) {
	v4 := []byte{10, 20, 0, 24}
	v6 := []byte{0xfd, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x11}
	mac := []byte{0x00, 0x11, 0x22, 0xaa, 0xbb, 0xcc}

	tests := []struct {
		name    string
		buf     []byte
		want    []Neighbor
		done    bool
		wantErr bool
	}{
		{
			name: "reachable ipv4 entry carries its address, mac and state",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac}),
			want: []Neighbor{{IP: mustAddr(t, "10.20.0.24"), MAC: "00:11:22:aa:bb:cc", State: NeighborReachable}},
		},
		{
			name: "stale ipv6 entry survives",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET6, unix.NUD_STALE,
				neighAttr{unix.NDA_DST, v6}, neighAttr{unix.NDA_LLADDR, mac}),
			want: []Neighbor{{IP: mustAddr(t, "fd00::11"), MAC: "00:11:22:aa:bb:cc", State: NeighborStale}},
		},
		{
			name: "NUD_FAILED entry is dropped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_FAILED,
				neighAttr{unix.NDA_DST, v4}),
			want: nil,
		},
		{
			name: "NUD_INCOMPLETE entry is dropped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_INCOMPLETE,
				neighAttr{unix.NDA_DST, v4}),
			want: nil,
		},
		{
			name: "NUD_NONE entry is dropped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_NONE,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac}),
			want: nil,
		},
		{
			name: "an all-zero mac keeps the address and reports no mac",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_NOARP,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, make([]byte, 6)}),
			want: []Neighbor{{IP: mustAddr(t, "10.20.0.24"), MAC: "", State: NeighborNoARP}},
		},
		{
			name: "a link-layer address that is not an EUI-48 reports no mac",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_PERMANENT,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, []byte{192, 0, 2, 1}}),
			want: []Neighbor{{IP: mustAddr(t, "10.20.0.24"), MAC: "", State: NeighborPermanent}},
		},
		{
			name: "an unknown address family is skipped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_BRIDGE, unix.NUD_PERMANENT,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac}),
			want: nil,
		},
		{
			name: "an address whose length disagrees with its family is skipped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
				neighAttr{unix.NDA_DST, v6}, neighAttr{unix.NDA_LLADDR, mac}),
			want: nil,
		},
		{
			name: "an entry with no address at all is skipped",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
				neighAttr{unix.NDA_LLADDR, mac}),
			want: nil,
		},
		{
			name: "an unrelated message type between entries is ignored",
			buf: concat(
				buildNeighMsg(unix.RTM_NEWLINK, unix.AF_INET, unix.NUD_REACHABLE, neighAttr{unix.NDA_DST, v4}),
				buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_DELAY,
					neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac}),
			),
			want: []Neighbor{{IP: mustAddr(t, "10.20.0.24"), MAC: "00:11:22:aa:bb:cc", State: NeighborDelay}},
		},
		{
			name: "several messages in one read are all walked",
			buf: concat(
				buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
					neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac}),
				buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET6, unix.NUD_PROBE,
					neighAttr{unix.NDA_DST, v6}, neighAttr{unix.NDA_LLADDR, mac}),
				doneMsg(),
			),
			want: []Neighbor{
				{IP: mustAddr(t, "10.20.0.24"), MAC: "00:11:22:aa:bb:cc", State: NeighborReachable},
				{IP: mustAddr(t, "fd00::11"), MAC: "00:11:22:aa:bb:cc", State: NeighborProbe},
			},
			done: true,
		},
		{
			name: "NLMSG_DONE stops the dump and discards what follows it",
			buf: concat(
				doneMsg(),
				buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE, neighAttr{unix.NDA_DST, v4}),
			),
			want: nil,
			done: true,
		},
		{
			name:    "NLMSG_ERROR fails the dump",
			buf:     errMsg(-int32(unix.EPERM)),
			wantErr: true,
		},
		{
			name: "an NLMSG_ERROR carrying zero is an ack, not a failure",
			buf:  concat(errMsg(0), doneMsg()),
			want: nil,
			done: true,
		},
		{
			name: "a message header cut short is an error",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
				neighAttr{unix.NDA_DST, v4})[:unix.SizeofNlMsghdr-1],
			wantErr: true,
		},
		{
			name: "a message claiming more bytes than the buffer holds is an error",
			buf: buildNeighMsg(unix.RTM_NEWNEIGH, unix.AF_INET, unix.NUD_REACHABLE,
				neighAttr{unix.NDA_DST, v4}, neighAttr{unix.NDA_LLADDR, mac})[:unix.SizeofNlMsghdr+unix.SizeofNdMsg+4],
			wantErr: true,
		},
		{
			name:    "a message shorter than the ndmsg header is an error",
			buf:     wrapNlMsg(unix.RTM_NEWNEIGH, make([]byte, unix.SizeofNdMsg-1)),
			wantErr: true,
		},
		{
			name:    "an attribute claiming more bytes than the message holds is an error",
			buf:     overlongAttr(),
			wantErr: true,
		},
		{
			name:    "an attribute shorter than its own header is an error",
			buf:     wrapNlMsg(unix.RTM_NEWNEIGH, append(ndmsgHeader(unix.AF_INET, unix.NUD_REACHABLE), 0x02, 0x00, 0x01, 0x00)),
			wantErr: true,
		},
		{
			name: "an empty buffer yields nothing and does not end the dump",
			buf:  nil,
			want: nil,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, done, err := parseNeighborDump(tc.buf, nil)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected an error, got %d neighbors", len(got))
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if done != tc.done {
				t.Fatalf("done = %v, want %v", done, tc.done)
			}
			if len(got) != len(tc.want) {
				t.Fatalf("got %d neighbors %v, want %d %v", len(got), got, len(tc.want), tc.want)
			}
			for i := range got {
				if got[i] != tc.want[i] {
					t.Fatalf("neighbor %d = %+v, want %+v", i, got[i], tc.want[i])
				}
			}
		})
	}
}

func concat(parts ...[]byte) []byte {
	var out []byte
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func ndmsgHeader(family uint8, state uint16) []byte {
	body := make([]byte, unix.SizeofNdMsg)
	body[0] = family
	binary.NativeEndian.PutUint16(body[8:10], state)
	return body
}

// overlongAttr declares an rtattr longer than the message that contains it — the shape a
// hostile or corrupt sender would use to walk the parser off the end of the buffer.
func overlongAttr() []byte {
	body := ndmsgHeader(unix.AF_INET, unix.NUD_REACHABLE)
	hdr := make([]byte, unix.SizeofRtAttr)
	binary.NativeEndian.PutUint16(hdr[0:2], 64)
	binary.NativeEndian.PutUint16(hdr[2:4], unix.NDA_DST)
	body = append(body, hdr...)
	body = append(body, 10, 20, 0, 24)
	return wrapNlMsg(unix.RTM_NEWNEIGH, body)
}

// TestNeighborsReadsTheKernelTable is the only test here that touches a socket. It asserts the
// invariants the parser promises rather than a specific table, since the table belongs to
// whatever host is running the suite. A sandboxed CI runner may forbid AF_NETLINK outright,
// which is a legitimate environment and not a defect — hence the skip.
func TestNeighborsReadsTheKernelTable(t *testing.T) {
	neighbors, err := Neighbors(context.Background())
	if err != nil {
		if errors.Is(err, ErrNeighborsUnsupported) {
			t.Fatal("Neighbors reported unsupported on linux; the stub was compiled in by mistake")
		}
		t.Skipf("netlink is unavailable in this environment: %v", err)
	}
	for _, n := range neighbors {
		if !n.IP.IsValid() {
			t.Fatalf("neighbor %+v has no address", n)
		}
		if n.State == "" {
			t.Fatalf("neighbor %+v has no state", n)
		}
	}
}
