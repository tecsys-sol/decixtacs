"""Configuration collectors.

Bulk collection runs through Nornir (threaded runner, ``backup_concurrency`` workers) using
Scrapli for platforms with a native Scrapli driver and Netmiko for the rest. The collection
recipe (commands per platform) is data-driven via ``Platform.backup_commands``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Default recipes, seeded into the ``platforms`` table.
DEFAULT_PLATFORMS: list[dict] = [
    {
        "slug": "junos",
        "name": "Juniper Junos",
        "vendor": "juniper",
        "scrapli": "juniper_junos",
        "netmiko": "juniper_junos",
        "commands": ["show configuration | display set | no-more"],
        "tacacs_service": "junos-exec",
        "replace": True,
    },
    {
        "slug": "eos",
        "name": "Arista EOS",
        "vendor": "arista",
        "scrapli": "arista_eos",
        "netmiko": "arista_eos",
        "commands": ["show running-config"],
        "replace": True,
    },
    {
        "slug": "ios",
        "name": "Cisco IOS / IOS-XE",
        "vendor": "cisco",
        "scrapli": "cisco_iosxe",
        "netmiko": "cisco_ios",
        "commands": ["show running-config"],
        "replace": True,
    },
    {
        "slug": "nxos",
        "name": "Cisco NX-OS",
        "vendor": "cisco",
        "scrapli": "cisco_nxos",
        "netmiko": "cisco_nxos",
        "commands": ["show running-config"],
        "replace": True,
    },
    {
        "slug": "fortios",
        "name": "Fortinet FortiOS",
        "vendor": "fortinet",
        "scrapli": None,
        "netmiko": "fortinet",
        "commands": ["show"],
        "tacacs_service": "fortigate",
    },
    {
        "slug": "sfos",
        "name": "Sophos SFOS",
        "vendor": "sophos",
        "scrapli": None,
        "netmiko": "sophos_sfos",
        "commands": [],  # collected over the XML API (services/backup/sfos.py, NOM_SFOS_ENTITIES)
    },
    {
        "slug": "routeros",
        "name": "MikroTik RouterOS",
        "vendor": "mikrotik",
        "scrapli": None,
        "netmiko": "mikrotik_routeros",
        "commands": ["/export terse"],
        "supports_tacacs": False,
    },
    {
        "slug": "vyos",
        "name": "VyOS",
        "vendor": "vyos",
        "scrapli": None,
        "netmiko": "vyos",
        "commands": ["show configuration commands"],
    },
    {
        "slug": "linux",
        "name": "Linux",
        "vendor": "linux",
        "scrapli": None,
        "netmiko": "linux",
        "commands": ["cat /etc/network/interfaces 2>/dev/null; cat /etc/bird/bird.conf 2>/dev/null"],
    },
]


@dataclass
class CollectTarget:
    device_id: str
    hostname: str
    host: str
    port: int
    platform: str
    scrapli_platform: str | None
    netmiko_device_type: str | None
    commands: Sequence[str]
    username: str
    password: str | None = None
    ssh_key: str | None = None
    enable_secret: str | None = None
    extras: dict = field(default_factory=dict)


@dataclass
class CollectResult:
    device_id: str
    ok: bool
    config: str = ""
    error: str | None = None
    duration_ms: int = 0


Collector = Callable[[list[CollectTarget]], list[CollectResult]]


def nornir_collect(targets: list[CollectTarget], workers: int = 50, timeout: int = 60) -> list[CollectResult]:
    """Collect configs from many devices in parallel with Nornir."""
    import time

    from nornir.core import Nornir
    from nornir.core.configuration import Config
    from nornir.core.inventory import ConnectionOptions, Defaults, Groups, Host, Hosts, Inventory
    from nornir.core.plugins.connections import ConnectionPluginRegister
    from nornir.core.task import Result, Task
    from nornir.plugins.runners import ThreadedRunner

    ConnectionPluginRegister.auto_register()  # scrapli / netmiko plugins (normally done by InitNornir)

    hosts = Hosts()
    for t in targets:
        extras: dict = {"auth_strict_key": False, "timeout_socket": timeout, "timeout_ops": timeout}
        if t.ssh_key:
            extras["auth_private_key"] = t.ssh_key
        if t.enable_secret:
            extras["auth_secondary"] = t.enable_secret
        hosts[t.device_id] = Host(
            name=t.device_id,
            hostname=t.host,
            port=t.port,
            username=t.username,
            password=t.password,
            platform=t.scrapli_platform or t.netmiko_device_type,
            data={"target": t},
            connection_options={
                "scrapli": ConnectionOptions(platform=t.scrapli_platform, extras=extras),
                "netmiko": ConnectionOptions(
                    platform=t.netmiko_device_type,
                    extras={"secret": t.enable_secret, "timeout": timeout, "fast_cli": False}
                    | ({"key_file": t.ssh_key} if t.ssh_key else {}),
                ),
            },
        )
    # Build the Nornir object directly from the in-memory inventory: there is no built-in
    # "DictInventory" plugin (only SimpleInventory, which reads YAML files).
    nr = Nornir(
        inventory=Inventory(hosts=hosts, groups=Groups(), defaults=Defaults()),
        runner=ThreadedRunner(num_workers=workers),
        config=Config(),  # InitNornir would also configure logging; we deliberately do not
    )

    def collect(task: Task) -> Result:
        t: CollectTarget = task.host.data["target"]
        start = time.monotonic()
        outputs: list[str] = []
        if t.scrapli_platform:
            conn = task.host.get_connection("scrapli", task.nornir.config)
            for cmd in t.commands:
                resp = conn.send_command(cmd)
                resp.raise_for_status()
                outputs.append(resp.result)
        else:
            conn = task.host.get_connection("netmiko", task.nornir.config)
            for cmd in t.commands:
                outputs.append(conn.send_command(cmd, read_timeout=timeout))
        return Result(
            host=task.host, result={"config": "\n".join(outputs), "ms": int((time.monotonic() - start) * 1000)}
        )

    agg = nr.run(task=collect)
    results = []
    for device_id, multi in agg.items():
        r = multi[0]
        if r.failed:
            results.append(CollectResult(device_id, False, error=str(r.exception or r.result)[:2000]))
        else:
            results.append(CollectResult(device_id, True, config=r.result["config"], duration_ms=r.result["ms"]))
    nr.close_connections()
    return results
