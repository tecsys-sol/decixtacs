from app.services.dcim import ports

FORTIOS = """config global
config system interface
    edit "port1"
        set vdom "root"
        set ip 10.20.0.1 255.255.255.254
        set allowaccess ping
        set type physical
        set alias "WAN"
        set description "uplink to del-02-rtr01 xe-0/0/3"
        config ipv6
            set ip6-address 2001:db8:20::1/127
        end
        set snmp-index 1
    next
    edit "port2"
        set vdom "root"
        set type physical
        set status down
    next
    edit "LACP-CORE"
        set vdom "root"
        set type aggregate
        set member "port3" "port4"
        set description "core bundle"
    next
    edit "vl100"
        set vdom "root"
        set ip 192.0.2.1 255.255.255.0
        set interface "LACP-CORE"
        set vlanid 100
        set description "mgmt vlan"
    next
    edit "ssl.root"
        set vdom "root"
        set type tunnel
    next
end
end
config router static
    edit 1
        set gateway 10.20.0.0
    next
end
"""

ROUTEROS = """# 2026-10-01 by RouterOS 7.14
/interface ethernet set [ find default-name=ether1 ] comment="to blr-01-ixp01 et-0/0/7" name=ether1-uplink
/interface ethernet set [ find default-name=ether5 ] disabled=yes
/interface bonding add mode=802.3ad name=bond1 slaves=ether2,ether3 comment=core
/interface vlan add interface=bond1 name=vlan200 vlan-id=200 comment="peering vlan"
/ip address add address=10.30.0.1/31 interface=ether1-uplink network=10.30.0.0
/ip address add address=198.51.100.1/24 interface=vlan200
/ipv6 address add address=2001:db8:30::1/127 interface=ether1-uplink advertise=no
"""

VYOS = """set interfaces ethernet eth0 address '10.40.0.1/31'
set interfaces ethernet eth0 description 'to maa-01-rtr01 et-0/0/1'
set interfaces ethernet eth1 bond-group 'bond0'
set interfaces ethernet eth2 disable
set interfaces bonding bond0 member interface 'eth3'
set interfaces bonding bond0 vif 300 address '203.0.113.1/24'
set interfaces bonding bond0 vif 300 description 'ix vlan'
set interfaces loopback lo address '10.255.0.9/32'
set interfaces wireguard wg0 address '10.99.0.1/31'
"""


def test_fortios_interfaces():
    ifs = ports.parse(FORTIOS, "fortios")
    p1 = ifs["port1"]
    assert p1.description == "uplink to del-02-rtr01 xe-0/0/3"
    assert p1.addresses() == ["10.20.0.1/31", "2001:db8:20::1/127"]
    assert ifs["port2"].disabled
    lag = ifs["LACP-CORE"]
    assert lag.is_lag and ifs["port3"].lag == "LACP-CORE" and ifs["port4"].lag == "LACP-CORE"
    assert lag.units["100"].addresses == ["192.0.2.1/24"] and lag.units["100"].description == "mgmt vlan"
    assert "vl100" not in ifs  # a VLAN interface is a unit of its parent
    assert ifs["ssl.root"].is_virtual and not p1.is_virtual
    assert ports.parse(FORTIOS, None).keys() == ifs.keys()  # recognised without a platform


def test_routeros_interfaces():
    ifs = ports.parse(ROUTEROS, "routeros")
    up = ifs["ether1-uplink"]
    assert up.description == "to blr-01-ixp01 et-0/0/7"
    assert up.addresses() == ["10.30.0.1/31", "2001:db8:30::1/127"]
    assert ifs["ether5"].disabled
    assert ifs["bond1"].is_lag and ifs["ether2"].lag == "bond1" and ifs["ether3"].lag == "bond1"
    assert ifs["bond1"].units["200"].addresses == ["198.51.100.1/24"]
    assert ifs["bond1"].units["200"].description == "peering vlan"


def test_vyos_interfaces():
    ifs = ports.parse(VYOS, "vyos")
    assert ifs["eth0"].addresses() == ["10.40.0.1/31"] and ifs["eth0"].description == "to maa-01-rtr01 et-0/0/1"
    assert ifs["eth1"].lag == "bond0" and ifs["eth3"].lag == "bond0" and ifs["bond0"].is_lag
    assert ifs["eth2"].disabled
    assert ifs["bond0"].units["300"].addresses == ["203.0.113.1/24"]
    assert ifs["lo"].is_virtual and ifs["wg0"].is_virtual and not ifs["eth0"].is_virtual


def test_device_names_in_descriptions():
    from types import SimpleNamespace

    from app.services.dcim import topology

    a = SimpleNamespace(id=1, hostname="DEL-02-IXP01")
    b = SimpleNamespace(id=2, hostname="maa-01-rtr01.maa.int.theixp.net")
    names = topology.DeviceNames([a, b])
    for text in (
        "core: to del-02-ixp01 et-0/0/1",
        "TO_DEL-02-IXP01_et-0/0/1",
        "DEL-02-IXP01-et-0/0/1",
        "uplink del02-ixp01",
        "[DEL02IXP01] ae0",
    ):
        assert names.find(text) == [a], text
    assert names.find("to maa-01-rtr01.maa.int.theixp.net xe-1/0/0") == [b]
    assert names.find("MAA-01-RTR01 ae1") == [b]
    assert names.find("del-02-ixp010 spare") == [] and names.find("xdel-02-ixp01") == []
    assert topology.asns_in("AS13335 Cloudflare / as-6939_HE / AS 32934") == [13335, 6939, 32934]
    assert topology.asns_in("CLASS2 BAS1") == []


def test_port_hint_resolves_abbreviations_and_lags():
    from app.services.dcim import topology

    junos = ports.parse(
        "set interfaces et-0/0/1 ether-options 802.3ad ae0\nset interfaces et-0/0/2 unit 0 family inet address 10.0.0.0/31\n",
        "junos",
    )
    assert topology.port_hint(" et-0/0/1 (bundle)", junos) == "ae0"
    assert topology.port_hint(" port et-0/0/2", junos) == "et-0/0/2"
    ios = ports.parse("interface GigabitEthernet0/0/1\n description x\n", "ios")
    assert topology.port_hint(" Gi0/0/1", ios) == "GigabitEthernet0/0/1"
    assert topology.port_hint(" nothing here", ios) is None


def test_canonical_ifname_ignores_bare_numbers():
    from app.services.dcim import topology

    forti = ports.parse(
        'config system interface\n    edit "port1"\n        set ip 10.0.0.1 255.255.255.254\n    next\nend\n', "fortios"
    )
    assert topology.canonical_ifname("1", forti) is None
    assert topology.canonical_ifname("531", forti) is None
    assert topology.canonical_ifname("port1", forti) == "port1"
