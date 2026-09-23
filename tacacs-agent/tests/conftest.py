from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from nom_tacacs_agent.api import ApiError, ConfigResponse


@dataclass
class FakeAPI:
    """In-memory stand-in for AgentAPI used by deployer / shipper / uploader tests."""

    config: ConfigResponse | None = None
    fetch_error: ApiError | None = None
    heartbeats: list[tuple[str | None, str, str | None]] = field(default_factory=list)
    etags_sent: list[str | None] = field(default_factory=list)
    ingest_results: list[object] = field(default_factory=list)  # ApiError to raise or dict to return
    ingested: list[list[str]] = field(default_factory=list)
    uploads: list[tuple[str, dict]] = field(default_factory=list)
    upload_error: ApiError | None = None

    def fetch_config(self, etag):
        self.etags_sent.append(etag)
        if self.fetch_error:
            raise self.fetch_error
        assert self.config is not None
        if self.config.state == "changed" and etag and etag == self.config.etag:
            return ConfigResponse("unchanged", etag=etag)
        return self.config

    def heartbeat(self, running_sha256, status="ok", message=None):
        self.heartbeats.append((running_sha256, status, message))

    def ingest(self, lines):
        if self.ingest_results:
            r = self.ingest_results.pop(0)
            if isinstance(r, ApiError):
                raise r
            self.ingested.append(list(lines))
            return r
        self.ingested.append(list(lines))
        return {"accounting": len(lines), "auth": 0, "skipped": 0}

    def upload_recording(self, path, meta):
        if self.upload_error:
            raise self.upload_error
        self.uploads.append((path.name, dict(meta)))
        return {"id": "x"}


@pytest.fixture
def fake_api():
    return FakeAPI()
