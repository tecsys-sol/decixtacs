"""Device types from the NetBox community devicetype-library (CC0).

Resolution order for (vendor, model):

1. the bundled copies in ``library/`` (common ISP/IXP models, works offline);
2. the on-disk cache (``<NOM data>/devicetypes``);
3. GitHub: the repository file index (``git/trees``, refreshed weekly) finds the file for the
   model - also when NetBox calls it ``QFX5120-48Y`` and the library ``QFX5120-48Y-AFI`` - and the
   YAML plus the front-panel photo (``elevation-images``) are downloaded once and cached.

Nothing here is required for the rest of the portal: without a match the port view falls back
to the interfaces found in the configuration.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from app.core.config import get_settings

log = logging.getLogger(__name__)

BUNDLE = Path(__file__).parent / "library"
INDEX_TTL = 7 * 86400
MISS_TTL = 86400

# NOM vendor slug -> library manufacturer directory
MANUFACTURERS = {
    "juniper": "Juniper",
    "arista": "Arista",
    "cisco": "Cisco",
    "fortinet": "Fortinet",
    "mikrotik": "MikroTik",
    "sophos": "Sophos",
    "nokia": "Nokia",
    "huawei": "Huawei",
    "dell": "Dell",
    "extreme-networks": "Extreme Networks",
    "extreme": "Extreme Networks",
    "edgecore": "Edgecore",
    "mellanox": "Mellanox",
    "nvidia": "NVIDIA",
    "hpe": "HPE",
    "aruba": "Aruba",
    "ubiquiti": "Ubiquiti",
    "palo-alto": "Palo Alto",
    "vyos": "VyOS",
}

_lock = threading.Lock()


@dataclass
class DeviceType:
    manufacturer: str
    model: str
    slug: str
    u_height: float = 1
    part_number: str | None = None
    airflow: str | None = None
    interfaces: list[dict] = field(default_factory=list)  # {name, type, mgmt_only}
    console_ports: list[dict] = field(default_factory=list)
    power_ports: list[dict] = field(default_factory=list)
    module_bays: list[dict] = field(default_factory=list)
    comments: str | None = None
    source: str = "bundle"  # bundle|cache|github
    path: str = ""  # library path, e.g. device-types/Juniper/MX204.yaml
    front_image: str | None = None  # library path of the front photo when known

    @classmethod
    def from_yaml(cls, text: str, source: str, path: str) -> DeviceType:
        d = yaml.safe_load(text) or {}
        return cls(
            manufacturer=str(d.get("manufacturer") or ""),
            model=str(d.get("model") or ""),
            slug=str(d.get("slug") or ""),
            u_height=float(d.get("u_height") or 1),
            part_number=d.get("part_number"),
            airflow=d.get("airflow"),
            interfaces=[
                {"name": str(i.get("name")), "type": i.get("type") or "other", "mgmt_only": bool(i.get("mgmt_only"))}
                for i in d.get("interfaces") or []
                if i.get("name")
            ],
            console_ports=list(d.get("console-ports") or []),
            power_ports=list(d.get("power-ports") or []),
            module_bays=list(d.get("module-bays") or []),
            comments=d.get("comments"),
            source=source,
            path=path,
        )

    def to_dict(self) -> dict:
        return {
            "manufacturer": self.manufacturer,
            "model": self.model,
            "slug": self.slug,
            "u_height": self.u_height,
            "part_number": self.part_number,
            "airflow": self.airflow,
            "console_ports": len(self.console_ports),
            "power_ports": len(self.power_ports),
            "module_bays": [m.get("name") for m in self.module_bays],
            "source": self.source,
            "library_url": f"https://github.com/netbox-community/devicetype-library/blob/master/{self.path}"
            if self.path
            else None,
            "has_front_image": bool(self.front_image),
        }


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def manufacturer_dir(vendor_slug: str | None, vendor_name: str | None) -> str | None:
    if vendor_slug and vendor_slug.lower() in MANUFACTURERS:
        return MANUFACTURERS[vendor_slug.lower()]
    return vendor_name or None


def cache_dir() -> Path:
    s = get_settings()
    base = Path(s.devicetype_cache_dir) if s.devicetype_cache_dir else Path(s.backup_repo_root).parent / "devicetypes"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _pick(model: str, candidates: dict[str, str]) -> str | None:
    """candidates: normalised stem -> path. Exact match, then the shortest stem starting with the
    model (``qfx512048y`` -> ``qfx512048yafi``), then one the model starts with (``7280cr332p4f``)."""
    n = norm(model)
    if not n:
        return None
    if n in candidates:
        return candidates[n]
    starts = sorted((k for k in candidates if k.startswith(n)), key=len)
    if starts:
        return candidates[starts[0]]
    for prefix in ("dcs", "n9kc", "ws", "fg", "fortigate"):
        if prefix + n in candidates:
            return candidates[prefix + n]
        starts = sorted((k for k in candidates if k.startswith(prefix + n)), key=len)
        if starts:
            return candidates[starts[0]]
    within = sorted((k for k in candidates if n.startswith(k) and len(k) >= max(4, len(n) - 3)), key=len, reverse=True)
    return candidates[within[0]] if within else None


# --- GitHub index ------------------------------------------------------------------------------


def _http() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "networkops-manager"})


def load_index(refresh: bool = False) -> dict | None:
    """{"types": {manufacturer: {norm(stem): path}}, "images": {norm(slug): path}} or None offline."""
    s = get_settings()
    if not s.devicetype_index_url:
        return None
    f = cache_dir() / "index.json"
    with _lock:
        if f.exists() and not refresh:
            try:
                idx = json.loads(f.read_text())
                if time.time() - idx.get("fetched", 0) < INDEX_TTL or idx.get("offline"):
                    return idx if idx.get("types") else None
            except (OSError, ValueError):
                pass
        try:
            with _http() as h:
                r = h.get(s.devicetype_index_url)
                r.raise_for_status()
                tree = r.json().get("tree", [])
        except (httpx.HTTPError, ValueError) as e:
            log.info("devicetype-library index unavailable: %s", e)
            # remember for a day so page loads do not wait for a timeout each time
            f.write_text(json.dumps({"fetched": time.time() - INDEX_TTL + MISS_TTL, "offline": True}))
            return None
        types: dict[str, dict[str, str]] = {}
        images: dict[str, str] = {}
        for e in tree:
            p = e.get("path", "")
            parts = p.split("/")
            if len(parts) == 3 and parts[0] == "device-types" and p.endswith((".yaml", ".yml")):
                types.setdefault(parts[1], {})[norm(parts[2].rsplit(".", 1)[0])] = p
            elif len(parts) == 3 and parts[0] == "elevation-images" and ".front." in parts[2]:
                images[norm(parts[2].split(".front.")[0])] = p
        idx = {"fetched": time.time(), "types": types, "images": images}
        f.write_text(json.dumps(idx))
        return idx


def _download(path: str) -> bytes | None:
    s = get_settings()
    if not s.devicetype_library_url:
        return None
    target = cache_dir() / "files" / path
    if target.exists():
        return target.read_bytes()
    miss = target.with_name(target.name + ".miss")
    if miss.exists() and time.time() - miss.stat().st_mtime < MISS_TTL:
        return None
    try:
        with _http() as h:
            r = h.get(f"{s.devicetype_library_url.rstrip('/')}/{path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if r.status_code != 200:
            miss.touch()
            return None
        target.write_bytes(r.content)
        return r.content
    except (httpx.HTTPError, OSError) as e:
        log.info("devicetype-library download of %s failed: %s", path, e)
        return None


# --- resolution ----------------------------------------------------------------------------------


def _bundle_candidates(mdir: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    dirs = [BUNDLE / mdir] if mdir and (BUNDLE / mdir).is_dir() else [d for d in BUNDLE.iterdir() if d.is_dir()]
    for d in dirs:
        for f in d.glob("*.yaml"):
            out[norm(f.stem)] = f"device-types/{d.name}/{f.name}"
    return out


def resolve(vendor_slug: str | None, vendor_name: str | None, model: str | None) -> DeviceType | None:
    if not model:
        return None
    mdir = manufacturer_dir(vendor_slug, vendor_name)
    dt: DeviceType | None = None
    idx = load_index()
    if idx:
        cands = idx["types"].get(mdir or "", {})
        if not cands and not mdir:
            cands = {k: v for m in idx["types"].values() for k, v in m.items()}
        path = _pick(model, cands)
        if path:
            data = _download(path)
            if data:
                dt = DeviceType.from_yaml(data.decode("utf-8", "replace"), "github", path)
    if dt is None:
        path = _pick(model, _bundle_candidates(mdir))
        if path:
            f = BUNDLE / path.removeprefix("device-types/")
            dt = DeviceType.from_yaml(f.read_text(), "bundle", path)
    if dt is None:
        return None
    if idx and dt.slug:
        dt.front_image = idx.get("images", {}).get(norm(dt.slug))
    elif dt.slug and mdir:
        dt.front_image = f"elevation-images/{mdir}/{dt.slug}.front.png"  # best guess without the index
    return dt


def front_image(dt: DeviceType) -> tuple[bytes, str] | None:
    """(bytes, media type) of the front-panel photo, downloaded once and cached."""
    if not dt.front_image:
        return None
    for path in (dt.front_image, dt.front_image.replace(".png", ".jpg")):
        data = _download(path)
        if data:
            return data, "image/jpeg" if path.endswith((".jpg", ".jpeg")) else "image/png"
        if dt.source == "github":  # the index gave the exact path
            break
    return None
