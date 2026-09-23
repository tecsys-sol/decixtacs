"""Module 17 - alert generation and delivery (email, Slack, Microsoft Teams, webhook)."""

from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import Alert, AlertChannel, AlertRule
from app.services import metrics

log = logging.getLogger(__name__)

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
EVENT_TYPES = {
    "backup_failed", "device_unreachable", "unauthorized_command", "compliance_failure",
    "config_drift", "login_failed", "tacacs_deploy_failed", "change_approved", "sync_failed",
}


def emit_event(
    db: Session,
    tenant_id: uuid.UUID,
    event_type: str,
    *,
    severity: str,
    title: str,
    body: str | None = None,
    device_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
    deliver: bool = True,
) -> Alert | None:
    """Record an alert and queue delivery for matching rules. Returns None if suppressed by throttling."""
    rules = [
        r for r in db.scalars(
            select(AlertRule).where(AlertRule.tenant_id == tenant_id, AlertRule.event_type == event_type, AlertRule.enabled)
        )
        if SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(r.min_severity, 0)
    ]
    throttle = max([r.throttle_minutes for r in rules], default=15)
    if dedup_key:
        recent = db.scalar(
            select(Alert.id).where(
                Alert.tenant_id == tenant_id,
                Alert.dedup_key == dedup_key,
                Alert.created_at >= utcnow() - timedelta(minutes=throttle),
            ).limit(1)
        )
        if recent:
            return None
    alert = Alert(
        tenant_id=tenant_id, event_type=event_type, severity=severity, title=title, body=body,
        device_id=device_id, dedup_key=dedup_key, delivered=[],
    )
    db.add(alert)
    db.flush()
    metrics.ALERTS.labels(event_type=event_type, severity=severity).inc()
    channel_ids = {cid for r in rules for cid in r.channel_ids}
    if deliver and channel_ids:
        try:
            from app.workers.tasks import deliver_alert

            deliver_alert.delay(str(alert.id), [str(c) for c in channel_ids])
        except Exception:  # broker down: deliver inline so alerts are never lost silently
            log.warning("alert queue unavailable, delivering inline", exc_info=True)
            deliver_now(db, alert, [uuid.UUID(str(c)) for c in channel_ids])
    return alert


def deliver_now(db: Session, alert: Alert, channel_ids: list[uuid.UUID]) -> list[dict]:
    results = []
    for ch in db.scalars(select(AlertChannel).where(AlertChannel.id.in_(channel_ids), AlertChannel.enabled)):
        try:
            send(ch.kind, decrypt_secret(ch.target_enc) or "", alert.title, alert.body or "", alert.severity)
            results.append({"channel": str(ch.id), "ok": True})
        except Exception as exc:  # noqa: BLE001
            log.exception("alert delivery failed via %s", ch.kind)
            results.append({"channel": str(ch.id), "ok": False, "error": str(exc)[:200]})
    alert.delivered = [*(alert.delivered or []), *results]
    return results


def send(kind: str, target: str, title: str, body: str, severity: str) -> None:
    text = f"[{severity.upper()}] {title}"
    if kind == "slack":
        payload = {"text": text, "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": text[:150]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"```{body[:2900]}```" if body else " "}},
        ]}
        httpx.post(target, json=payload, timeout=10).raise_for_status()
    elif kind == "teams":
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard", "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": text, "weight": "Bolder", "wrap": True},
                        {"type": "TextBlock", "text": body[:4000], "wrap": True, "fontType": "Monospace"},
                    ],
                },
            }],
        }
        httpx.post(target, json=payload, timeout=10).raise_for_status()
    elif kind == "webhook":
        httpx.post(target, json={"title": title, "body": body, "severity": severity}, timeout=10).raise_for_status()
    elif kind == "email":
        s = get_settings()
        msg = EmailMessage()
        msg["Subject"] = text
        msg["From"] = s.smtp_from
        msg["To"] = target
        msg.set_content(body or title)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(msg)
    else:
        raise ValueError(f"unknown channel kind {kind}")
