"""Normalise and sanitise collected configs (Oxidized-style) before they are committed.

* strips volatile lines (timestamps, uptime, NTP clock-period ...) so unchanged configs do not
  create noise commits;
* optionally masks secrets so the Git repository can be shared with a wider audience.
"""

from __future__ import annotations

import re

VOLATILE: dict[str, list[str]] = {
    "junos": [r"^## Last (commit|changed):.*$", r"^# Last (commit|changed):.*$"],
    "eos": [r"^! Time:.*$", r"^! Startup-config last modified.*$", r"^! device: .*uptime.*$"],
    "ios": [
        r"^! Last configuration change.*$",
        r"^! NVRAM config last updated.*$",
        r"^ntp clock-period .*$",
        r"^Building configuration.*$",
        r"^Current configuration : \d+ bytes$",
    ],
    "nxos": [r"^!Time:.*$", r"^!Running configuration last done at:.*$"],
    "fortios": [r"^#conf_file_ver=.*$", r"^#buildno=.*$"],
    "routeros": [
        r"^# \w{3}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} by RouterOS.*$",
        r"^# \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} by RouterOS.*$",
    ],
    "vyos": [],
    "sfos": [],
    "linux": [],
}

SECRETS: dict[str, list[tuple[str, str]]] = {
    "junos": [
        (
            r'((?:encrypted-password|authentication-key|secret|pre-shared-key ascii-text|hash) )"?[^";\s]+"?',
            r'\1"<removed>"',
        ),
        (r"(\bkey )\"?\$9\$[^\";\s]+\"?", r'\1"<removed>"'),
    ],
    "eos": [
        (r"(\bsecret (?:sha512|5|7|0) )\S+", r"\1<removed>"),
        (r"(\bpassword (?:7 )?)\S+", r"\1<removed>"),
        (r"(\bkey (?:7 )?)\S+$", r"\1<removed>"),
        (r"(snmp-server community )\S+", r"\1<removed>"),
    ],
    "ios": [
        (r"(\bsecret (?:\d )?)\S+", r"\1<removed>"),
        (r"(\bpassword (?:\d )?)\S+", r"\1<removed>"),
        (r"(snmp-server community )\S+", r"\1<removed>"),
        (r"(\bkey (?:\d )?)\S+$", r"\1<removed>"),
    ],
    "nxos": [
        (r"(\bpassword (?:\d )?)\S+", r"\1<removed>"),
        (r"(snmp-server community )\S+", r"\1<removed>"),
        (r"(\bkey (?:\d )?)\S+$", r"\1<removed>"),
    ],
    "fortios": [(r"(set (?:password|passwd|psksecret|secret|key|private-key) )ENC \S+", r"\1ENC <removed>")],
    "routeros": [(r"((?:password|secret|authentication-key)=)\S+", r"\1<removed>")],
    "vyos": [(r"((?:encrypted-password|password|secret|key) )\S+", r"\1<removed>")],
    # SFOS XML: any element whose name says it holds a secret (Password, EncryptedPassword,
    # PresharedKey, SharedSecret, Passphrase, PrivateKey ...). Escaped so the XML stays valid.
    "sfos": [
        (
            r"(?i)(<(\w*(?:password|passphrase|secret|presharedkey|psk|sharedkey|privatekey|authkey)\w*)>)"
            r"[^<]*(</\2>)",
            r"\1&lt;removed&gt;\3",
        )
    ],
}


def normalise(config: str, platform: str) -> str:
    text = config.replace("\r\n", "\n").replace("\r", "\n")
    for pat in VOLATILE.get(platform, []):
        text = re.sub(pat, "", text, flags=re.MULTILINE)
    # collapse the blank lines left behind and strip trailing whitespace
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue
        out.append(ln)
    return "\n".join(out).strip("\n") + "\n"


def mask_secrets(config: str, platform: str) -> str:
    for pat, repl in SECRETS.get(platform, []):
        config = re.sub(pat, repl, config, flags=re.MULTILINE)
    return config


def prepare(config: str, platform: str, sanitize: bool) -> str:
    text = normalise(config, platform)
    return mask_secrets(text, platform) if sanitize else text
