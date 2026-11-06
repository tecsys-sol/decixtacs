from datetime import UTC, datetime, timedelta

from app.models import CommandLog


def test_activity_counts_the_whole_window(admin, db, tenant):
    now = datetime.now(UTC) - timedelta(minutes=1)  # in the past, so every row is inside the window
    rows = []
    # 1,500 commands a day for 10 days - well past the 1,000 rows the charts used to load
    for day in range(10):
        for k in range(1500):
            rows.append(
                CommandLog(
                    tenant_id=tenant.id,
                    username="rancid",
                    device_address="10.0.0.1",
                    command="show configuration | display set",
                    timestamp=now - timedelta(days=day, seconds=k),
                )
            )
    rows.append(
        CommandLog(
            tenant_id=tenant.id,
            username="manoj",
            device_address="10.0.0.2",
            command="request system reboot",
            timestamp=now - timedelta(days=3),
        )
    )
    db.add_all(rows)
    db.commit()

    week = admin.get("/api/v1/accounting/activity", params={"days": 7}).json()
    assert week["grain"] == "day" and len(week["buckets"]) in (7, 8)
    # everything inside the 7 days counts, not just the latest 1,000
    assert week["total"] == sum(b["commands"] + b["dangerous"] for b in week["buckets"])
    assert week["total"] == 7 * 1500 + 1
    assert sum(b["dangerous"] for b in week["buckets"]) == 1
    assert sum(map(sum, week["weekday_hour"])) == week["total"]

    month = admin.get("/api/v1/accounting/activity", params={"days": 30}).json()
    assert month["total"] == 10 * 1500 + 1

    day = admin.get("/api/v1/accounting/activity", params={"days": 1}).json()
    assert day["grain"] == "hour" and 24 <= len(day["buckets"]) <= 25

    # filters apply as on the command list
    only = admin.get("/api/v1/accounting/activity", params={"days": 30, "user": "manoj"}).json()
    assert only["total"] == 1 and sum(b["dangerous"] for b in only["buckets"]) == 1


def test_activity_uses_the_viewers_time_zone(admin, db, tenant):
    # 20:00 UTC on a Monday is 01:30 on Tuesday in India
    t = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)
    db.add(
        CommandLog(tenant_id=tenant.id, username="u", device_address="10.0.0.1", command="show version", timestamp=t)
    )
    db.commit()
    window = {"start": (t - timedelta(days=3)).isoformat(), "end": (t + timedelta(days=1)).isoformat()}
    utc = admin.get("/api/v1/accounting/activity", params={**window, "tz": "UTC"}).json()
    ist = admin.get("/api/v1/accounting/activity", params={**window, "tz": "Asia/Kolkata"}).json()
    assert utc["weekday_hour"][0][20] == 1  # Monday 20:00
    assert ist["weekday_hour"][1][1] == 1  # Tuesday 01:00
    assert [b["t"] for b in ist["buckets"] if b["commands"]] == ["2026-11-03T00:00"]
    assert admin.get("/api/v1/accounting/activity", params={"tz": "Mars/Base"}).status_code == 422
