from __future__ import annotations

import pytest
import respx

from networkops import NetworkOpsClient

BASE = "https://nom.example.net/api/v1"


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        yield m


@pytest.fixture
def client(mock):
    c = NetworkOpsClient("https://nom.example.net", token="nomt_test", sleep=lambda s: None)
    yield c
    c.close()


def page(items, total=None, limit=100, offset=0):
    return {"items": items, "total": len(items) if total is None else total, "limit": limit, "offset": offset}
