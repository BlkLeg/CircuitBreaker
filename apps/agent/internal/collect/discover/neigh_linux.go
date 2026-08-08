//go:build linux

package discover

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"time"

	"golang.org/x/sys/unix"
)

// x/sys/unix supplies the constants and the socket calls but no message parsing: NetlinkRIB,
// ParseNetlinkMessage and ParseNetlinkRouteAttr live only in the frozen stdlib syscall package
// (D-11). So the framing below is hand-written, and it is hand-written defensively — a netlink
// socket is readable by anything on the host that can reach it, and every length in the stream is
// attacker-influenced until it has been checked against the bytes actually present.

// neighborDumpTimeout caps one full RTM_GETNEIGH dump. A neighbor table is a few hundred entries
// read off a local socket; anything approaching this is a wedged socket, not a slow one.
const neighborDumpTimeout = 3 * time.Second

// neighborReadSlice is how long a single recvfrom blocks before the loop re-checks the context.
// The socket has no other cancellation path, so this — not neighborDumpTimeout — is the latency
// a `discovery.cancel` sees, and it has to stay well inside one host timeout (1500 ms).
const neighborReadSlice = 250 * time.Millisecond

// neighborReadBuffer holds one netlink datagram. The kernel splits a dump into messages well
// under 32 KiB, and MSG_TRUNC below turns any surprise into an error instead of a silent
// half-table.
const neighborReadBuffer = 64 << 10

// nudUnusable are the states that say the kernel tried to resolve an address, not that a host
// answered. NUD_NONE is zero, so it is matched by equality rather than by mask.
const nudUnusable = unix.NUD_FAILED | unix.NUD_INCOMPLETE

func neighbors(ctx context.Context) ([]Neighbor, error) {
	// SOCK_CLOEXEC is not optional: internal/update re-execs the agent binary, and a netlink fd
	// leaked across that exec would survive every future upgrade.
	fd, err := unix.Socket(unix.AF_NETLINK, unix.SOCK_RAW|unix.SOCK_CLOEXEC, unix.NETLINK_ROUTE)
	if err != nil {
		return nil, fmt.Errorf("discover: open netlink socket: %w", err)
	}
	defer unix.Close(fd)

	// Pid 0 asks the kernel to allocate the port id. Binding to a fixed one would collide with
	// any other netlink user in the same process.
	if err := unix.Bind(fd, &unix.SockaddrNetlink{Family: unix.AF_NETLINK}); err != nil {
		return nil, fmt.Errorf("discover: bind netlink socket: %w", err)
	}

	slice := unix.NsecToTimeval(int64(neighborReadSlice))
	if err := unix.SetsockoptTimeval(fd, unix.SOL_SOCKET, unix.SO_RCVTIMEO, &slice); err != nil {
		return nil, fmt.Errorf("discover: set netlink read timeout: %w", err)
	}

	if err := unix.Sendto(fd, neighborDumpRequest(), 0, &unix.SockaddrNetlink{Family: unix.AF_NETLINK}); err != nil {
		return nil, fmt.Errorf("discover: request neighbor dump: %w", err)
	}

	deadline := time.Now().Add(neighborDumpTimeout)
	if ctxDeadline, ok := ctx.Deadline(); ok && ctxDeadline.Before(deadline) {
		deadline = ctxDeadline
	}

	buf := make([]byte, neighborReadBuffer)
	var out []Neighbor
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if !time.Now().Before(deadline) {
			return nil, errors.New("discover: neighbor dump did not complete in time")
		}

		// MSG_TRUNC makes recvfrom report the datagram's real size even when it did not fit, so
		// an oversized message is an error here rather than a truncated-message parse failure
		// several frames later.
		n, from, err := unix.Recvfrom(fd, buf, unix.MSG_TRUNC)
		if err != nil {
			// EAGAIN is the read slice expiring, EINTR a signal; both mean "ask again", and the
			// deadline check at the top of the loop is what stops this from spinning forever.
			if errors.Is(err, unix.EAGAIN) || errors.Is(err, unix.EINTR) {
				continue
			}
			return nil, fmt.Errorf("discover: read neighbor dump: %w", err)
		}
		if n > len(buf) {
			return nil, fmt.Errorf("discover: netlink message of %d bytes exceeds the %d byte read buffer", n, len(buf))
		}

		// Netlink is not a kernel-only channel: any local process may unicast to this socket's
		// port id. Pid 0 is the kernel, and nothing else is allowed to inject neighbors.
		if sender, ok := from.(*unix.SockaddrNetlink); !ok || sender.Pid != 0 {
			continue
		}

		var done bool
		out, done, err = parseNeighborDump(buf[:n], out)
		if err != nil {
			return nil, err
		}
		if done {
			return out, nil
		}
	}
}

// neighborDumpRequest builds the one message this package ever sends: RTM_GETNEIGH with
// AF_UNSPEC, which asks for every family at once so IPv4 and IPv6 arrive in a single dump.
func neighborDumpRequest() []byte {
	req := make([]byte, unix.SizeofNlMsghdr+unix.SizeofNdMsg)
	binary.NativeEndian.PutUint32(req[0:4], uint32(len(req)))
	binary.NativeEndian.PutUint16(req[4:6], unix.RTM_GETNEIGH)
	binary.NativeEndian.PutUint16(req[6:8], unix.NLM_F_REQUEST|unix.NLM_F_DUMP)
	binary.NativeEndian.PutUint32(req[8:12], 1) // Seq
	req[unix.SizeofNlMsghdr] = unix.AF_UNSPEC
	return req
}

// parseNeighborDump walks one read's worth of netlink messages, appending every usable neighbor
// to out. done reports NLMSG_DONE, which is the only thing that ends a multi-part dump — a read
// returning no error and no NLMSG_DONE simply means more messages are still coming.
//
// Malformed framing is an error rather than a stopping point. A half-walked buffer would be
// reported to the backend as a complete neighbor table, and a discovery run that quietly loses
// half its hosts is worse than one that says the neighbor cache could not be read.
func parseNeighborDump(buf []byte, out []Neighbor) ([]Neighbor, bool, error) {
	for len(buf) > 0 {
		if len(buf) < unix.SizeofNlMsghdr {
			return out, false, fmt.Errorf("discover: netlink header truncated to %d bytes", len(buf))
		}
		msgLen := int(binary.NativeEndian.Uint32(buf[0:4]))
		msgType := binary.NativeEndian.Uint16(buf[4:6])
		if msgLen < unix.SizeofNlMsghdr || msgLen > len(buf) {
			return out, false, fmt.Errorf("discover: netlink message claims %d bytes of a %d byte buffer", msgLen, len(buf))
		}
		body := buf[unix.SizeofNlMsghdr:msgLen]

		switch msgType {
		case unix.NLMSG_DONE:
			return out, true, nil
		case unix.NLMSG_ERROR:
			if err := neighborDumpError(body); err != nil {
				return out, false, err
			}
		case unix.RTM_NEWNEIGH:
			n, ok, err := parseNeighbor(body)
			if err != nil {
				return out, false, err
			}
			if ok {
				out = append(out, n)
			}
		}

		// The kernel pads every message up to a 4-byte boundary, but the final message of a
		// datagram can end unpadded; clamping keeps a well-formed tail from reading as garbage.
		advance := (msgLen + unix.NLMSG_ALIGNTO - 1) &^ (unix.NLMSG_ALIGNTO - 1)
		if advance > len(buf) {
			advance = len(buf)
		}
		buf = buf[advance:]
	}
	return out, false, nil
}

// neighborDumpError decodes an NLMSG_ERROR body. A zero code is an acknowledgement, not a
// failure, so it must not abort the dump.
func neighborDumpError(body []byte) error {
	if len(body) < 4 {
		return errors.New("discover: netlink error message carries no code")
	}
	code := int32(binary.NativeEndian.Uint32(body[0:4]))
	if code == 0 {
		return nil
	}
	// The kernel reports the errno negated.
	return fmt.Errorf("discover: neighbor dump rejected: %w", unix.Errno(-code))
}

// parseNeighbor decodes one RTM_NEWNEIGH body. ok=false means the entry is real but not usable as
// discovery evidence — an error is reserved for framing the parser could not trust.
func parseNeighbor(body []byte) (Neighbor, bool, error) {
	if len(body) < unix.SizeofNdMsg {
		return Neighbor{}, false, fmt.Errorf("discover: neighbor message truncated to %d bytes", len(body))
	}
	family := body[0]
	state := binary.NativeEndian.Uint16(body[8:10])

	addrLen, ok := neighborAddrLen(family)
	if !ok {
		// AF_BRIDGE FDB entries and other families share the AF_UNSPEC dump. They are neighbors
		// of a sort, but not addresses this agent can probe or report.
		return Neighbor{}, false, nil
	}
	if state == unix.NUD_NONE || state&nudUnusable != 0 {
		return Neighbor{}, false, nil
	}

	var dst, lladdr []byte
	attrs := body[unix.SizeofNdMsg:]
	for len(attrs) > 0 {
		if len(attrs) < unix.SizeofRtAttr {
			return Neighbor{}, false, fmt.Errorf("discover: rtattr header truncated to %d bytes", len(attrs))
		}
		attrLen := int(binary.NativeEndian.Uint16(attrs[0:2]))
		attrType := binary.NativeEndian.Uint16(attrs[2:4])
		if attrLen < unix.SizeofRtAttr || attrLen > len(attrs) {
			return Neighbor{}, false, fmt.Errorf("discover: rtattr claims %d bytes of a %d byte message", attrLen, len(attrs))
		}
		switch attrType {
		case unix.NDA_DST:
			dst = attrs[unix.SizeofRtAttr:attrLen]
		case unix.NDA_LLADDR:
			lladdr = attrs[unix.SizeofRtAttr:attrLen]
		}
		advance := (attrLen + unix.RTA_ALIGNTO - 1) &^ (unix.RTA_ALIGNTO - 1)
		if advance > len(attrs) {
			advance = len(attrs)
		}
		attrs = attrs[advance:]
	}

	// An address whose width disagrees with its family is corrupt rather than merely unusual, but
	// dropping the one entry is the proportionate response: the rest of the dump is still sound.
	if len(dst) != addrLen {
		return Neighbor{}, false, nil
	}
	ip, ok := netip.AddrFromSlice(dst)
	if !ok {
		return Neighbor{}, false, nil
	}

	return Neighbor{IP: ip, MAC: neighborMAC(lladdr), State: neighborState(state)}, true, nil
}

// neighborAddrLen reports the address width this parser accepts for a family. Only IPv4 and IPv6
// are discoverable; everything else the dump carries is skipped.
func neighborAddrLen(family uint8) (int, bool) {
	switch family {
	case unix.AF_INET:
		return net.IPv4len, true
	case unix.AF_INET6:
		return net.IPv6len, true
	default:
		return 0, false
	}
}

// neighborMAC renders a link-layer address, or "" when there is nothing worth reporting.
//
// Only EUI-48 is accepted. NDA_LLADDR is whatever the link type uses — 4 bytes of IPv4 for an
// IPIP tunnel, 20 for InfiniBand, 0 for a link with no addressing — and the backend's MAC
// matcher (D-9) only understands 48-bit hardware addresses. An all-zero address is the kernel's
// placeholder and is dropped for the reason given on Neighbor.MAC.
func neighborMAC(lladdr []byte) string {
	if len(lladdr) != 6 {
		return ""
	}
	for _, b := range lladdr {
		if b != 0 {
			return net.HardwareAddr(lladdr).String()
		}
	}
	return ""
}

// neighborState names a NUD state. States combine in principle, so the most specific evidence of
// contact wins; an unrecognised state keeps its numeric form rather than being dropped, so a
// future kernel cannot make an otherwise good entry disappear.
func neighborState(state uint16) string {
	switch {
	case state&unix.NUD_REACHABLE != 0:
		return NeighborReachable
	case state&unix.NUD_PERMANENT != 0:
		return NeighborPermanent
	case state&unix.NUD_STALE != 0:
		return NeighborStale
	case state&unix.NUD_DELAY != 0:
		return NeighborDelay
	case state&unix.NUD_PROBE != 0:
		return NeighborProbe
	case state&unix.NUD_NOARP != 0:
		return NeighborNoARP
	default:
		return fmt.Sprintf("state(0x%02x)", state)
	}
}
