import pytest

from app.core import redis as nom_redis
from app.core.config import Settings
from app.core.ratelimit import RateLimiter


class FakeRedis:
    """Just enough of redis-py for EphemeralStore / RateLimiter."""

    def __init__(self):
        self.data, self.ttl = {}, {}

    def set(self, k, v, ex=None):
        self.data[k], self.ttl[k] = v, ex

    def getdel(self, k):
        return self.data.pop(k, None)


class DeadRedis:
    calls = 0

    def __getattr__(self, name):
        def boom(*a, **kw):
            DeadRedis.calls += 1
            raise ConnectionError("redis down")

        return boom


def test_parse_sentinels():
    assert nom_redis.parse_sentinels("10.0.0.1:26379, s2:26380,s3,[2001:db8::1]:5000, ") == [
        ("10.0.0.1", 26379),
        ("s2", 26380),
        ("s3", 26379),
        ("2001:db8::1", 5000),
    ]


def test_celery_config_plain_and_sentinel():
    plain = Settings(redis_url="redis://:pw@redis:6379/2")
    assert nom_redis.celery_redis_config(plain) == {
        "broker_url": "redis://:pw@redis:6379/2",
        "result_backend": "redis://:pw@redis:6379/2",
    }
    s = Settings(
        redis_url="redis://:p%40ss@ignored:6379/3",
        redis_sentinels="sen1:26379,sen2:26379,sen3",
        redis_sentinel_master="nom-master",
        redis_sentinel_password="sentinel-pw",
    )
    cfg = nom_redis.celery_redis_config(s)
    assert cfg["broker_url"] == (
        "sentinel://:p%40ss@sen1:26379/3;sentinel://:p%40ss@sen2:26379/3;sentinel://:p%40ss@sen3:26379/3"
    )
    assert cfg["result_backend"] == cfg["broker_url"]
    expected = {"master_name": "nom-master", "sentinel_kwargs": {"password": "sentinel-pw"}}
    assert cfg["broker_transport_options"] == expected
    assert cfg["result_backend_transport_options"] == expected
    no_auth = nom_redis.celery_redis_config(Settings(redis_url="redis://x/0", redis_sentinels="a:1"))
    assert no_auth["broker_url"] == "sentinel://a:1/0" and no_auth["broker_transport_options"] == {
        "master_name": "mymaster"
    }


def test_celery_app_uses_helper():
    from app.workers.celery_app import celery_app

    assert celery_app.conf.broker_url == nom_redis.celery_redis_config()["broker_url"]


def test_redis_client_sentinel(monkeypatch):
    from redis.sentinel import SentinelConnectionPool

    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "redis_sentinels", "sen1:26379,sen2:26379")
    monkeypatch.setattr(s, "redis_sentinel_master", "nom-master")
    monkeypatch.setattr(s, "redis_url", "redis://:secret@whatever:6379/4")
    nom_redis.redis_client.cache_clear()
    try:
        c = nom_redis.redis_client(0.3)
        pool = c.connection_pool
        assert isinstance(pool, SentinelConnectionPool) and pool.service_name == "nom-master"
        assert pool.connection_kwargs["password"] == "secret" and pool.connection_kwargs["db"] == 4
        assert [(x.connection_pool.connection_kwargs["host"]) for x in pool.sentinel_manager.sentinels] == [
            "sen1",
            "sen2",
        ]
    finally:
        nom_redis.redis_client.cache_clear()


def test_ephemeral_store_redis_one_time_use():
    fake = FakeRedis()
    store = nom_redis.EphemeralStore("nom:oidc:state:", fake)
    store.put("abc", {"verifier": "v", "tenant": None}, 600)
    assert fake.ttl["nom:oidc:state:abc"] == 600
    assert store.pop("abc") == {"verifier": "v", "tenant": None}
    assert store.pop("abc") is None  # GETDEL: one-time
    assert store.pop("nope") is None


def test_ephemeral_store_falls_back_to_memory(monkeypatch):
    DeadRedis.calls = 0
    store = nom_redis.EphemeralStore("p:", DeadRedis())
    store.put("s1", {"a": 1}, 600)
    assert DeadRedis.calls == 1 and not store.breaker.closed
    store.put("s2", {"a": 2}, 600)
    assert DeadRedis.calls == 1  # breaker open: redis skipped
    assert store.pop("s1") == {"a": 1} and store.pop("s1") is None
    store.put("old", {"a": 3}, 10)
    t = nom_redis.time.monotonic()
    monkeypatch.setattr(nom_redis.time, "monotonic", lambda: t + 31)
    assert store.pop("old") is None  # expired
    # after the cool-down redis is tried again
    assert store.breaker.closed
    assert store.pop("unknown") is None and DeadRedis.calls == 2


def test_rate_limiter_degrades_to_memory():
    rl = RateLimiter(DeadRedis())
    assert rl.hit("k", 2, 60) == (True, 1)
    assert rl.hit("k", 2, 60) == (True, 0)
    assert rl.hit("k", 2, 60) == (False, 0)


@pytest.mark.parametrize("db_ok,redis_state,code", [(True, "down", 200), (False, "ok", 503)])
def test_readyz(client, monkeypatch, db_ok, redis_state, code):
    from app.core.config import get_settings
    from app.db import session as db_session

    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(nom_redis, "ping", lambda: redis_state)
    if not db_ok:

        class Broken:
            def connect(self):
                raise OSError("db down")

        monkeypatch.setattr(db_session, "engine", Broken())
    r = client.get("/readyz")
    assert r.status_code == code
    body = r.json()
    assert body["checks"] == {"database": "ok" if db_ok else "down", "redis": redis_state}
    assert body["degraded"] is (redis_state == "down")
