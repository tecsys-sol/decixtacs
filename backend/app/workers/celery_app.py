"""Celery application + beat schedule."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("networkops", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    timezone="UTC",
    task_routes={
        "app.workers.tasks.backup_*": {"queue": "collect"},
        "app.workers.tasks.run_backup_schedule": {"queue": "collect"},
        "app.workers.tasks.deliver_alert": {"queue": "alerts"},
    },
    beat_schedule={
        "backups-hourly": {"task": "app.workers.tasks.run_backup_schedule", "schedule": crontab(minute=5)},
        "integrations-sync": {
            "task": "app.workers.tasks.sync_all_integrations",
            "schedule": s.netbox_sync_minutes * 60.0,
        },
        "compliance-daily": {"task": "app.workers.tasks.run_compliance_all", "schedule": crontab(hour=2, minute=30)},
        "retention-daily": {"task": "app.workers.tasks.apply_retention", "schedule": crontab(hour=3, minute=15)},
        "partitions-daily": {"task": "app.workers.tasks.ensure_partitions", "schedule": crontab(hour=0, minute=10)},
        "reports": {"task": "app.workers.tasks.run_report_schedules", "schedule": crontab(minute=0)},
    },
)
