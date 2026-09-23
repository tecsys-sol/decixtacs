from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from networkops._client import BaseClient


class Resource:
    def __init__(self, client: BaseClient):
        self._c = client
