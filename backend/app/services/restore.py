"""Module 11 - configuration restore / rollback with dry-run.

Uses scrapli-cfg (config replace + diff + commit/abort) on platforms that support atomic
replace (Junos, EOS, IOS-XE, NX-OS). Workflow:

1. take a fresh pre-restore backup (so the restore itself can be rolled back);
2. load the selected version as a *candidate* and ask the device for its diff;
3. dry run -> abort and return the device-computed diff;
   real run -> commit (Junos: ``commit confirmed`` style safety via scrapli-cfg), then back up again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

SCRAPLI_CFG_PLATFORMS = {"junos": "juniper_junos", "eos": "arista_eos", "ios": "cisco_iosxe", "nxos": "cisco_nxos"}


@dataclass
class PushOutcome:
    ok: bool
    device_diff: str
    output: str


Pusher = Callable[[object, str, bool], PushOutcome]


def scrapli_cfg_push(target, config: str, dry_run: bool) -> PushOutcome:
    """``target`` is a :class:`app.services.backup.collector.CollectTarget`."""
    from scrapli import Scrapli
    from scrapli_cfg import ScrapliCfg

    platform = SCRAPLI_CFG_PLATFORMS.get(target.platform)
    if platform is None:
        return PushOutcome(False, "", f"config replace not supported on platform {target.platform}")
    conn_args = {
        "host": target.host, "port": target.port, "auth_username": target.username,
        "auth_password": target.password, "auth_strict_key": False, "platform": platform,
        "timeout_ops": 120,
    }
    if target.ssh_key:
        conn_args["auth_private_key"] = target.ssh_key
    with Scrapli(**conn_args) as conn:
        cfg = ScrapliCfg(conn=conn)
        cfg.prepare()
        load = cfg.load_config(config=config, replace=True)
        if load.failed:
            cfg.abort_config()
            return PushOutcome(False, "", load.result)
        diff = cfg.diff_config()
        device_diff = diff.device_diff or diff.unified_diff
        if dry_run:
            cfg.abort_config()
            return PushOutcome(True, device_diff, "dry run - candidate discarded")
        commit = cfg.commit_config()
        cfg.cleanup()
        return PushOutcome(not commit.failed, device_diff, commit.result)
