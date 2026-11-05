#!/usr/bin/env python3
"""Drop duplicate UDP datagrams from a pcap.

``tcpdump -i any`` records a packet once on every interface it crosses: a datagram that
arrives over a bond, a VLAN sub-interface or a bridge is captured two or more times. The
application reading the socket sees it once, so an audit of the capture must too. Two
packets are duplicates when their UDP payload is identical; link-layer headers, which
differ per interface, are ignored.

    pcap-dedupe.py in.pcap out.pcap        # prints "kept N of M packets" on stderr

Handles classic pcap with Ethernet, Linux "cooked" (SLL, SLL2, as -i any writes), and
raw IP link types. Python 3.6+, standard library only.
"""

import hashlib
import struct
import sys

# link type -> bytes before the IP header (Ethernet is variable: VLAN tags)
LINK_SLL, LINK_SLL2, LINK_ETHERNET, LINK_RAW, LINK_IPV4, LINK_IPV6 = 113, 276, 1, 101, 228, 229


def udp_payload(link: int, frame: bytes):
    if link == LINK_SLL:
        off, ethertype = 16, struct.unpack("!H", frame[14:16])[0]
    elif link == LINK_SLL2:
        off, ethertype = 20, struct.unpack("!H", frame[0:2])[0]
    elif link == LINK_ETHERNET:
        off, ethertype = 14, struct.unpack("!H", frame[12:14])[0]
        while ethertype in (0x8100, 0x88A8) and len(frame) >= off + 4:
            ethertype = struct.unpack("!H", frame[off + 2 : off + 4])[0]
            off += 4
    elif link in (LINK_RAW, LINK_IPV4, LINK_IPV6):
        off = 0
        ethertype = 0x0800 if frame[:1] and frame[0] >> 4 == 4 else 0x86DD
    else:
        return None
    ip = frame[off:]
    if ethertype == 0x0800 and len(ip) >= 20:
        ihl = (ip[0] & 0x0F) * 4
        if ip[9] != 17:
            return None
        # source address as well: two switches could send identical bytes
        return ip[12:16] + ip[ihl + 8 :]
    if ethertype == 0x86DD and len(ip) >= 40:
        if ip[6] != 17:  # no extension headers expected on sFlow
            return None
        return ip[8:24] + ip[48:]
    return None


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write(__doc__)
        return 2
    with open(args[0], "rb") as fin:
        head = fin.read(24)
        if len(head) < 24:
            sys.stderr.write("not a pcap file\n")
            return 1
        magic = head[:4]
        if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            end = "<"
        elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            end = ">"
        else:
            sys.stderr.write("not a classic pcap file (pcapng is not supported: use tcpdump -w)\n")
            return 1
        link = struct.unpack(end + "I", head[20:24])[0] & 0x0FFFFFFF
        seen = set()
        total = kept = 0
        with open(args[1], "wb") as fout:
            fout.write(head)
            while True:
                rec = fin.read(16)
                if len(rec) < 16:
                    break
                incl = struct.unpack(end + "I", rec[8:12])[0]
                frame = fin.read(incl)
                if len(frame) < incl:
                    break
                total += 1
                payload = udp_payload(link, frame)
                if payload is not None:
                    key = hashlib.blake2b(payload, digest_size=16).digest()
                    if key in seen:
                        continue
                    seen.add(key)
                fout.write(rec + frame)
                kept += 1
    sys.stderr.write(f"kept {kept} of {total} packets ({total - kept} duplicates dropped)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
