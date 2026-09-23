"""Module 11 - configuration restore / rollback with dry-run.

Uses scrapli-cfg (config replace + diff + commit/abort) on platforms that support atomic
replace (Junos, EOS, IOS-XE, NX-OS). Workflow:

1. take a fresh pre-restore backup (so the restore itself can be rolled back);
2. load the selected version as a *candidate* and ask the device for its diff;
3. dry run -> abort and return the device-computed diff;
   real run -> commit, then back up again.

Junos backups are stored in ``display set`` format; see :func:`junos_load_plan` for how they are
replayed as a full replace (docs/backup-architecture.md).
"""

from __future__ import annotations

import logging
import re
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


JUNOS_LOAD_ERROR = re.compile(r"^error:|syntax error|load complete \(\d+ errors?\)", re.M | re.I)
JUNOS_SET_VERBS = ("set ", "delete ", "deactivate ", "activate ", "insert ", "protect ", "unprotect ")


def is_junos_set_format(config: str) -> bool:
    lines = [ln for ln in config.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return bool(lines) and all(ln.startswith(JUNOS_SET_VERBS) for ln in lines)


def junos_load_plan(config: str) -> tuple[str, dict]:
    """How to load a stored Junos config through scrapli-cfg as a *replace*.

    scrapli-cfg writes the candidate to a file with ``echo >> file '<line>'`` and then runs either
    ``load override <file>`` (``replace=True``) or ``load set <file>`` (``set=True``). ``load override``
    only accepts the hierarchical (curly-brace) format, but backups are collected as
    ``show configuration | display set``. For set-format content we therefore load in ``set`` mode
    with a leading top-level ``delete``: inside a ``load set`` file that empties the candidate
    without the interactive confirmation, and the following ``set`` lines rebuild it - i.e. a full
    replace, still atomic because nothing is committed until ``commit``. Hierarchical content keeps
    using ``load override``.

    Returns (payload, load_config kwargs). Single quotes are escaped for the ``echo '...'`` wrapper.
    """
    if is_junos_set_format(config):
        body = [ln.rstrip() for ln in config.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        payload, kwargs = "\n".join(["delete", *body]), {"replace": False, "set": True}
    else:
        payload = "\n".join(ln.rstrip() for ln in config.splitlines() if not ln.startswith("## Last"))
        kwargs = {"replace": True}
    return payload.replace("'", "'\"'\"'"), kwargs


def _outputs(resp) -> str:
    return "\n".join(r.result for r in getattr(resp, "scrapli_responses", []) if getattr(r, "result", ""))


def push_with_cfg(cfg, platform: str, config: str, dry_run: bool) -> PushOutcome:
    """Load -> device diff -> abort (dry run) or commit, on an already prepared ScrapliCfg object."""
    if platform == "junos":
        payload, kwargs = junos_load_plan(config)
    else:
        payload, kwargs = config, {"replace": True}
    load = cfg.load_config(config=payload, **kwargs)
    load_out = _outputs(load)
    if load.failed or (platform == "junos" and JUNOS_LOAD_ERROR.search(load_out)):
        cfg.abort_config()
        return PushOutcome(False, "", load.result or load_out or "load failed")
    diff = cfg.diff_config()
    device_diff = diff.device_diff or diff.unified_diff
    if dry_run:
        cfg.abort_config()
        return PushOutcome(True, device_diff, "dry run - candidate discarded")
    commit = cfg.commit_config()
    return PushOutcome(not commit.failed, device_diff, commit.result or _outputs(commit))


def scrapli_cfg_push(target, config: str, dry_run: bool) -> PushOutcome:
    """``target`` is a :class:`app.services.backup.collector.CollectTarget`."""
    from scrapli import Scrapli
    from scrapli_cfg import ScrapliCfg

    platform = SCRAPLI_CFG_PLATFORMS.get(target.platform)
    if platform is None:
        return PushOutcome(False, "", f"config replace not supported on platform {target.platform}")
    conn_args = {
        "host": target.host,
        "port": target.port,
        "auth_username": target.username,
        "auth_password": target.password,
        "auth_strict_key": False,
        "platform": platform,
        "timeout_ops": 120,
    }
    if target.ssh_key:
        conn_args["auth_private_key"] = target.ssh_key
    with Scrapli(**conn_args) as conn:
        cfg = ScrapliCfg(conn=conn)
        cfg.prepare()
        try:
            return push_with_cfg(cfg, target.platform, config, dry_run)
        finally:
            cfg.cleanup()
