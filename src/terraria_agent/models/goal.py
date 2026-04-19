from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Goal:
    kind: str
    target_tile: tuple[int, int]
    ttl: float = 10.0
    max_attempts: int = 5
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    parent_strategic_goal: str = ""

    def expired(self, now: float | None = None) -> bool:
        t = time.time() if now is None else now
        return (t - self.created_at) > self.ttl

    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts
