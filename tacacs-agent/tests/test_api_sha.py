from nom_tacacs_agent.api import config_sha256

SHA = "10fbf4e1cd9324101fdfa6dda786df21930f694e3852cddaa86376b487cc4683"


def test_prefers_dedicated_header():
    assert config_sha256({"X-Config-Sha256": SHA, "ETag": "garbage"}) == SHA


def test_etag_rewritten_by_proxies():
    for etag in (SHA, f'"{SHA}"', f"{SHA}-gzip", f'W/"{SHA}-zstd"', f'"{SHA.upper()}"'):
        assert config_sha256({"ETag": etag}) == SHA


def test_missing_or_bogus():
    assert config_sha256({}) is None
    assert config_sha256({"ETag": "abc"}) is None
