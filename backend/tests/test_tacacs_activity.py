from datetime import UTC, datetime, timedelta

from app.models import CommandLog, TacacsAuthEvent


def _event(tenant, t, kind="authen", result="pass"):
    return TacacsAuthEvent(
        tenant_id=tenant.id, username="u", device_address="10.0.0.1", kind=kind, result=result, timestamp=t
    )


def test_activity_counts_every_event_in_the_window(admin, db, tenant):
    now = datetime.now(UTC) - timedelta(minutes=1)
    # 1,500 of each kind in the last 24 hours - more than the 1,000 rows the charts used to load
    rows = []
    for k in range(1500):
        t = now - timedelta(seconds=k * 50)  # spread over ~21 hours
        rows += [
            _event(tenant, t, "authen", "pass" if k % 3 else "fail"),
            _event(tenant, t, "author", "permit"),
            CommandLog(
                tenant_id=tenant.id, username="u", device_address="10.0.0.1", command="show version", timestamp=t
            ),
        ]
    rows.append(_event(tenant, now - timedelta(days=3)))  # outside 24h, inside 7d
    db.add_all(rows)
    db.commit()

    day = admin.get("/api/v1/tacacs/activity", params={"range": "24h", "tz": "Asia/Kolkata"}).json()
    assert len(day["starts"]) == 24
    assert day["totals"] == {"authen": 1500, "author": 1500, "acct": 1500}
    assert all(len(v) == 24 for v in day["series"].values())

    week = admin.get("/api/v1/tacacs/activity", params={"range": "7d"}).json()
    assert len(week["starts"]) == 28 and week["totals"]["authen"] == 1501

    by_result = admin.get("/api/v1/tacacs/activity", params={"range": "24h", "group": "result"}).json()
    assert by_result["totals"] == {"pass": 1000, "fail": 500, "permit": 1500}
    assert by_result["kinds"] == {"authen": 1500, "author": 1500}

    assert admin.get("/api/v1/tacacs/activity", params={"range": "1y"}).status_code == 422
    assert admin.get("/api/v1/tacacs/activity", params={"tz": "Mars/Base"}).status_code == 422


def test_buckets_align_to_the_viewers_day(admin, db, tenant):
    month = admin.get("/api/v1/tacacs/activity", params={"range": "30d", "tz": "Asia/Kolkata"}).json()
    assert len(month["starts"]) == 30 and all(s.endswith("T00:00") for s in month["starts"])
    week = admin.get("/api/v1/tacacs/activity", params={"range": "7d", "tz": "Asia/Kolkata"}).json()
    assert all(int(s[11:13]) % 6 == 0 and s.endswith(":00") for s in week["starts"])
