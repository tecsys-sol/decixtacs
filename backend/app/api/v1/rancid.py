"""RANCID migration: import logins from .cloginrc/router.db and compare RANCID's configs with NOM's backups."""

from __future__ import annotations

import difflib
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.api.deps import Ctx, get_owned, require
from app.api.v1.inventory import _default_credential_id, _set_default_credential, visible_devices_filter
from app.core.security import decrypt_secret, encrypt_secret
from app.db.base import utcnow
from app.models import Credential, Device, Platform, RancidConfig
from app.services import audit
from app.services import diff as diffsvc
from app.services import rancid as rs
from app.services.backup.engine import device_relpath, store_for

router = APIRouter(prefix="/rancid", tags=["rancid"])

MAX_ARCHIVE = 200 * 1024 * 1024


def _match_devices(devices: list[Device]) -> dict[str, Device]:
    """lookup keys (hostname, short hostname, management IP; lower case) -> device"""
    m: dict[str, Device] = {}
    for d in devices:
        for k in (d.hostname.lower(), rs.short(d.hostname), (d.management_ip or "").lower()):
            if k:
                m.setdefault(k, d)
    return m


def _find(m: dict[str, Device], name: str) -> Device | None:
    return m.get(name.lower()) or m.get(rs.short(name))


# --- credentials ---------------------------------------------------------------------------


class ImportCredentialsIn(BaseModel):
    cloginrc: str
    router_db: str = ""
    dry_run: bool = True
    # set the platform of inventory devices that have none from the router.db type
    set_platforms: bool = True
    # replace credentials already assigned to devices (default: only fill devices without one)
    overwrite: bool = False
    default_user: str = "rancid"


class PlannedCredential(BaseModel):
    name: str
    username: str
    has_password: bool
    has_enable_secret: bool
    existing: bool  # an identical credential already exists and is reused
    is_default: bool
    devices: list[str]


class ImportCredentialsOut(BaseModel):
    dry_run: bool
    credentials: list[PlannedCredential]
    assigned: int
    kept_existing: list[str]  # devices that already had their own credential
    no_login: list[str]  # devices no .cloginrc line matches
    ssh_keys: list[str]  # devices RANCID logs in to with an SSH key file
    router_db_not_in_inventory: list[str]
    router_db_down: list[str]
    platforms_set: list[str]
    warnings: list[str]


@router.post("/import-credentials", response_model=ImportCredentialsOut)
def import_credentials(body: ImportCredentialsIn, ctx: Ctx = Depends(require("credentials:write"))):
    """Turn RANCID's .cloginrc into credentials: devices sharing a login share one credential, the
    most common login becomes the tenant default, the others are assigned per device."""
    directives, warnings = rs.parse_cloginrc(body.cloginrc)
    if not directives:
        raise HTTPException(422, "no 'add user/password ...' lines found in .cloginrc")
    entries, w2 = rs.parse_router_db(body.router_db) if body.router_db.strip() else ([], [])
    warnings += w2
    devices = list(
        ctx.db.scalars(
            select(Device)
            .where(Device.tenant_id == ctx.tenant_id)
            .options(selectinload(Device.platform), selectinload(Device.credential))
        )
    )
    by_key = _match_devices(devices)
    out = ImportCredentialsOut(
        dry_run=body.dry_run,
        credentials=[],
        assigned=0,
        kept_existing=[],
        no_login=[],
        ssh_keys=[],
        router_db_not_in_inventory=[],
        router_db_down=[],
        platforms_set=[],
        warnings=warnings,
    )

    # which devices, under which RANCID name
    targets: list[tuple[Device, str]] = []
    if entries:
        platforms = {p.slug: p for p in ctx.db.scalars(select(Platform))}
        seen: set[uuid.UUID] = set()
        for e in entries:
            d = _find(by_key, e.name)
            if d is None:
                out.router_db_not_in_inventory.append(e.name)
                continue
            if e.state != "up":
                out.router_db_down.append(f"{d.hostname} ({e.state})")
            slug = rs.RANCID_TYPES.get(e.type)
            if body.set_platforms and d.platform_id is None and slug in platforms:
                d.platform_id = platforms[slug].id
                out.platforms_set.append(f"{d.hostname} → {slug}")
            elif slug is None:
                warnings.append(f"router.db: {e.name}: RANCID type '{e.type}' has no NOM platform")
            if d.id not in seen:
                seen.add(d.id)
                targets.append((d, e.name))
    else:
        targets = [(d, d.hostname) for d in devices]

    logins: dict[tuple, rs.Login] = {}
    users_of: dict[tuple, list[Device]] = {}
    for d, name in targets:
        names = [name, d.hostname, rs.short(d.hostname)] + ([d.management_ip] if d.management_ip else [])
        login = rs.login_for(directives, names, body.default_user)
        if login is None:
            out.no_login.append(d.hostname)
            continue
        if login.identity and not login.password:
            out.ssh_keys.append(f"{d.hostname} ({login.identity})")
            continue
        logins.setdefault(login.key, login)
        users_of.setdefault(login.key, []).append(d)
    if out.ssh_keys:
        warnings.append(
            "RANCID uses SSH key files for some devices - add those keys to a credential manually "
            "(the key file itself is not in .cloginrc)"
        )

    existing = list(ctx.db.scalars(select(Credential).where(Credential.tenant_id == ctx.tenant_id)))
    names_taken = {c.name for c in existing}
    default_id = _default_credential_id(ctx)
    ranked = sorted(users_of, key=lambda k: -len(users_of[k]))
    for i, key in enumerate(ranked):
        login = logins[key]
        cred = next(
            (
                c
                for c in existing
                if c.username == login.username
                and decrypt_secret(c.password_enc) == login.password
                and decrypt_secret(c.enable_secret_enc) == login.enable
            ),
            None,
        )
        reused = cred is not None
        if cred is None:
            base = f"rancid-{login.username}"
            name, n = base, 2
            while name in names_taken:
                name, n = f"{base}-{n}", n + 1
            names_taken.add(name)
            cred = Credential(
                tenant_id=ctx.tenant_id,
                name=name,
                username=login.username,
                password_enc=encrypt_secret(login.password) if login.password else None,
                enable_secret_enc=encrypt_secret(login.enable) if login.enable else None,
                rotated_at=utcnow(),
            )
            ctx.db.add(cred)
            ctx.db.flush()
            existing.append(cred)
        make_default = i == 0 and default_id is None
        if make_default:
            _set_default_credential(ctx, cred.id)
            default_id = str(cred.id)
        is_default = default_id == str(cred.id)
        for d in users_of[key]:
            if d.credential_id and d.credential_id != cred.id and not body.overwrite:
                out.kept_existing.append(d.hostname)
                continue
            target = None if is_default else cred.id  # default covers devices without their own
            if d.credential_id != target:
                d.credential_id = target
                out.assigned += 1
        out.credentials.append(
            PlannedCredential(
                name=cred.name,
                username=login.username,
                has_password=bool(login.password),
                has_enable_secret=bool(login.enable),
                existing=reused,
                is_default=is_default,
                devices=sorted(d.hostname for d in users_of[key]),
            )
        )
    if body.dry_run:
        ctx.db.rollback()
        return out
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="credential.import_rancid",
        actor=ctx.user,
        after={
            "credentials": [c.name for c in out.credentials],
            "assigned": out.assigned,
            "platforms_set": len(out.platforms_set),
        },
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return out


# --- config comparison ---------------------------------------------------------------------


class UploadOut(BaseModel):
    files: int
    matched: int
    unmatched: list[str]


@router.post("/configs", response_model=UploadOut)
async def upload_configs(file: UploadFile = File(...), ctx: Ctx = Depends(require("configs:backup"))):
    """Upload RANCID's configs as .tar.gz/.zip (``tar czf rancid.tgz -C /var/lib/rancid .``).
    Replaces previously uploaded copies of the same routers."""
    data = await file.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise HTTPException(413, "archive larger than 200 MB")
    try:
        files = rs.read_archive(data)
    except Exception as e:  # noqa: BLE001 - corrupt/unsupported archives
        raise HTTPException(422, f"could not read the archive: {e}") from e
    if not files:
        raise HTTPException(422, "no <group>/configs/<router> files found in the archive")
    by_key = _match_devices(list(ctx.db.scalars(select(Device).where(Device.tenant_id == ctx.tenant_id))))
    ctx.db.execute(
        delete(RancidConfig).where(RancidConfig.tenant_id == ctx.tenant_id, RancidConfig.name.in_(list(files)))
    )
    unmatched = []
    for name, (group, content) in files.items():
        d = _find(by_key, name)
        if d is None:
            unmatched.append(name)
        ctx.db.add(
            RancidConfig(
                tenant_id=ctx.tenant_id,
                name=name[:255],
                rancid_group=group,
                device_id=d.id if d else None,
                content=content,
            )
        )
    audit.record(
        ctx.db,
        tenant_id=ctx.tenant_id,
        action="config.rancid_upload",
        actor=ctx.user,
        after={"files": len(files), "unmatched": len(unmatched)},
        source_ip=ctx.ip,
    )
    ctx.db.commit()
    return UploadOut(files=len(files), matched=len(files) - len(unmatched), unmatched=sorted(unmatched))


class CompareRow(BaseModel):
    id: uuid.UUID
    rancid_name: str
    rancid_group: str | None
    device_id: uuid.UUID | None
    hostname: str | None
    platform: str | None
    status: str  # identical|differs|no_portal_backup|not_in_inventory
    rancid_lines: int
    portal_lines: int
    only_in_rancid: int
    only_in_portal: int
    similarity: float  # 0..100
    portal_collected_at: datetime | None
    imported_at: datetime


def _compare(a: list[str], b: list[str]) -> tuple[int, int, float]:
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    same = sum(bl.size for bl in sm.get_matching_blocks())
    ratio = 100.0 if not a and not b else round(200.0 * same / (len(a) + len(b)), 1)
    return len(a) - same, len(b) - same, ratio


@router.get("/compare", response_model=list[CompareRow])
def compare(ctx: Ctx = Depends(require("configs:read"))):
    """Every uploaded RANCID config next to NOM's latest backup of the same device."""
    visible = set(
        ctx.db.scalars(
            visible_devices_filter(ctx, select(Device.id).where(Device.tenant_id == ctx.tenant_id), "configs:read")
        )
    )
    store = store_for(ctx.db, ctx.tenant_id)
    from app.models import ConfigBackup

    rows = []
    for rc in ctx.db.scalars(
        select(RancidConfig)
        .where(RancidConfig.tenant_id == ctx.tenant_id)
        .order_by(RancidConfig.name)
        .options(selectinload(RancidConfig.device).selectinload(Device.platform))
    ):
        d = rc.device
        if d is not None and d.id not in visible:
            continue
        plat = d.platform.slug if d and d.platform else None
        a = rs.normalise(rc.content, plat)
        portal = store.read(device_relpath(d)) if d else None
        last = (
            ctx.db.scalar(
                select(ConfigBackup.collected_at)
                .where(ConfigBackup.device_id == d.id, ConfigBackup.status != "failed")
                .order_by(ConfigBackup.collected_at.desc())
                .limit(1)
            )
            if d
            else None
        )
        if portal is None:
            status, b = ("not_in_inventory" if d is None else "no_portal_backup"), []
            only_r, only_p, sim = len(a), 0, 0.0
        else:
            b = rs.normalise(portal, plat)
            only_r, only_p, sim = _compare(a, b)
            status = "identical" if only_r == 0 and only_p == 0 else "differs"
        rows.append(
            CompareRow(
                id=rc.id,
                rancid_name=rc.name,
                rancid_group=rc.rancid_group,
                device_id=d.id if d else None,
                hostname=d.hostname if d else None,
                platform=plat,
                status=status,
                rancid_lines=len(a),
                portal_lines=len(b),
                only_in_rancid=only_r,
                only_in_portal=only_p,
                similarity=sim,
                portal_collected_at=last,
                imported_at=rc.imported_at,
            )
        )
    return rows


@router.get("/compare/{rancid_id}")
def compare_one(rancid_id: uuid.UUID, context: int = 3, ctx: Ctx = Depends(require("configs:read"))):
    """Side-by-side diff: RANCID's copy (old/left) vs NOM's latest backup (new/right), both normalised."""
    rc = get_owned(ctx, RancidConfig, rancid_id, "RANCID config")
    d = ctx.db.get(Device, rc.device_id) if rc.device_id else None
    if d is not None and not ctx.principal.can_on_device("configs:read", d):
        raise HTTPException(404, "RANCID config not found")
    plat = d.platform.slug if d and d.platform else None
    portal = store_for(ctx.db, ctx.tenant_id).read(device_relpath(d)) if d else None
    a = "\n".join(rs.normalise(rc.content, plat)) + "\n"
    b = "\n".join(rs.normalise(portal, plat)) + "\n" if portal is not None else ""
    st = diffsvc.stats(a, b)
    return {
        "old_rev": f"rancid:{rc.name}",
        "new_rev": f"nom:{d.hostname}" if d else "nom:(not in inventory)",
        "unified": diffsvc.unified(a, b, f"rancid/{rc.name}", f"nom/{d.hostname if d else '-'}", context),
        "side_by_side": diffsvc.side_by_side(a, b, context),
        "added": st.added,
        "removed": st.removed,
        "risk": {"score": 0, "level": "low", "findings": [], "summary": "RANCID vs NOM comparison (normalised)"},
        "junos_converted": plat == "junos" and not rc.content.lstrip().startswith("set "),
    }


@router.delete("/configs", status_code=204)
def clear_configs(ctx: Ctx = Depends(require("configs:backup"))):
    ctx.db.execute(delete(RancidConfig).where(RancidConfig.tenant_id == ctx.tenant_id))
    ctx.db.commit()
