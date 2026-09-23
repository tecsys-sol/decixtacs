"""Sophos Firewall (SFOS) collector over the XML API.

SFOS has no usable ``show running-config`` over SSH (the console is a menu), so devices with
platform slug ``sfos`` are collected with one API call instead of Nornir/SSH::

    POST https://<fw>:4444/webconsole/APIController      (multipart field ``reqxml``)
    <Request><Login><Username>..</Username><Password>..</Password></Login>
             <Get><IPHost/><FirewallRule/>...</Get></Request>

The API must be enabled on the firewall (Backup & firmware > API) with the collector's source IP
allow-listed. The entity list is ``NOM_SFOS_ENTITIES`` (per device: ``custom_fields.sfos_entities``,
a list or comma separated string); the port is ``NOM_SFOS_API_PORT`` (per device:
``custom_fields.api_port``); TLS verification ``NOM_SFOS_VERIFY_TLS`` (per device:
``custom_fields.verify_tls``). The response is stored as pretty-printed XML with the login block and
per-request attributes removed so unchanged configs produce identical text.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET  # noqa: N817
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import httpx

from app.core.config import get_settings
from app.services.backup.collector import CollectResult, CollectTarget

log = logging.getLogger(__name__)

API_PATH = "/webconsole/APIController"
VOLATILE_ATTRS = ("transactionid", "IPS_CAT_VER")


class SfosError(RuntimeError):
    pass


def entities_for(target: CollectTarget) -> list[str]:
    raw = target.extras.get("sfos_entities") or get_settings().sfos_entities
    items = raw.split(",") if isinstance(raw, str) else raw
    return [e.strip() for e in items if e and e.strip()]


def build_request(username: str, password: str, entities: list[str]) -> str:
    gets = "".join(f"<{e}/>" for e in entities if e.isidentifier())
    return (
        f"<Request><Login><Username>{escape(username)}</Username><Password>{escape(password)}</Password>"
        f"</Login><Get>{gets}</Get></Request>"
    )


def parse_response(text: str) -> str:
    """Validate the API response and render the configuration as stable, indented XML."""
    if "<!DOCTYPE" in text[:1024] or "<!ENTITY" in text:
        raise SfosError("refusing XML with a DOCTYPE/ENTITY declaration")
    try:
        root = ET.fromstring(text)  # noqa: S314 - DOCTYPE/entities rejected above
    except ET.ParseError as exc:
        raise SfosError(f"invalid XML from firewall: {exc}") from exc
    if root.tag != "Response":
        raise SfosError(f"unexpected response root <{root.tag}>")
    login = root.find("Login")
    status = (login.findtext("status") or "").strip() if login is not None else ""
    if login is not None and "success" not in status.lower():
        raise SfosError(f"SFOS API login failed: {status or 'no status'}")
    top_status = root.find("Status")
    if top_status is not None and len(root) == 1:
        raise SfosError(f"SFOS API error {top_status.get('code', '')}: {(top_status.text or '').strip()}")
    if login is not None:
        root.remove(login)
    for el in root.iter():
        for a in VOLATILE_ATTRS:
            el.attrib.pop(a, None)
        if el.text is not None and not el.text.strip():
            el.text = None
        if el.tail is not None and not el.tail.strip():
            el.tail = None
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def collect_one(target: CollectTarget, timeout: int = 60, client: httpx.Client | None = None) -> CollectResult:
    s = get_settings()
    start = time.monotonic()
    port = int(target.extras.get("api_port") or s.sfos_api_port)
    verify = target.extras.get("verify_tls", s.sfos_verify_tls)
    url = f"https://{target.host}:{port}{API_PATH}"
    body = build_request(target.username, target.password or "", entities_for(target))
    try:
        http = client or httpx.Client(verify=bool(verify), timeout=timeout)
        try:
            r = http.post(url, files={"reqxml": (None, body)})
            r.raise_for_status()
        finally:
            if client is None:
                http.close()
        config = parse_response(r.text)
    except (httpx.HTTPError, SfosError) as exc:
        return CollectResult(target.device_id, False, error=f"{type(exc).__name__}: {exc}"[:2000])
    return CollectResult(target.device_id, True, config=config, duration_ms=int((time.monotonic() - start) * 1000))


def sfos_collect(targets: list[CollectTarget], workers: int = 50, timeout: int = 60) -> list[CollectResult]:
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets)))) as pool:
        return list(pool.map(lambda t: collect_one(t, timeout), targets))
