"""Exponential backoff with full jitter."""

from __future__ import annotations

import random
from collections.abc import Callable


class Backoff:
    def __init__(self, base: float = 1.0, factor: float = 2.0, maximum: float = 300.0,
                 rand: Callable[[], float] = random.random):
        self.base, self.factor, self.maximum = base, factor, maximum
        self._rand = rand
        self.attempt = 0

    def next_delay(self) -> float:
        """Delay before the next attempt: uniform in [base/2, min(max, base*factor^n)]."""
        cap = min(self.maximum, self.base * (self.factor ** self.attempt))
        self.attempt += 1
        return max(self.base / 2, cap * self._rand())

    def reset(self) -> None:
        self.attempt = 0
