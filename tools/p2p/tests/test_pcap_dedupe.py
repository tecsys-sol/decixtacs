import importlib.util
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pcap_dedupe", HERE.parent / "pcap-dedupe.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)


def ipv4_udp(src: bytes, payload: bytes) -> bytes:
    udp = struct.pack("!HHHH", 50000, 6343, 8 + len(payload), 0) + payload
    return struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0, src, b"\x0a\x00\x00\x09") + udp


def pcap(link: int, frames) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, link)
    for f in frames:
        out += struct.pack("<IIII", 0, 0, len(f), len(f)) + f
    return out


def run(tmp_path, link, frames):
    src, dst = tmp_path / "in.pcap", tmp_path / "out.pcap"
    src.write_bytes(pcap(link, frames))
    assert pd.main([str(src), str(dst)]) == 0
    return (len(dst.read_bytes()) - 24) // 16  # rough: frames are the same size below


def test_linux_cooked_duplicates_across_interfaces(tmp_path, capsys):
    a = ipv4_udp(b"\xac\x11\x8a\x0b", b"sflow datagram 1".ljust(40, b"."))
    b = ipv4_udp(b"\xac\x11\x8a\x0b", b"sflow datagram 2".ljust(40, b"."))
    other_switch = ipv4_udp(b"\xac\x11\x8a\x0c", b"sflow datagram 1".ljust(40, b"."))

    def sll(ifhint: int, ip: bytes) -> bytes:  # same packet, different interface header
        return struct.pack("!HHH8sH", 0, 1, 6, bytes([ifhint] * 8), 0x0800) + ip

    run(tmp_path, pd.LINK_SLL, [sll(1, a), sll(2, a), sll(3, a), sll(1, b), sll(1, other_switch)])
    # a captured three times on three interfaces; the same bytes from another switch are not a duplicate
    assert "kept 3 of 5 packets (2 duplicates dropped)" in capsys.readouterr().err


def test_ethernet_with_vlan_tag(tmp_path, capsys):
    ip = ipv4_udp(b"\xac\x11\x8a\x0b", b"x" * 40)
    plain = b"\x00" * 12 + b"\x08\x00" + ip
    tagged = b"\x00" * 12 + b"\x81\x00\x00\x64\x08\x00" + ip
    run(tmp_path, pd.LINK_ETHERNET, [plain, tagged])
    assert "kept 1 of 2 packets" in capsys.readouterr().err
