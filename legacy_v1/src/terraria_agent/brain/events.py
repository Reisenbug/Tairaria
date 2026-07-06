from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    TICK = "tick"
    TACTICAL = "tactical"
    STRATEGIC = "strategic"


@dataclass
class BrainEvent:
    type: str
    details: dict = field(default_factory=dict)
    tick: int = 0
    severity: Severity = Severity.TACTICAL
    timestamp: float = 0.0


_STRATEGIC_TYPES = {
    "goal_achieved", "died", "new_biome", "boss_defeated",
    "inventory_milestone", "stuck_persistent",
}


def classify(event_type: str) -> Severity:
    if event_type in _STRATEGIC_TYPES:
        return Severity.STRATEGIC
    return Severity.TACTICAL


class EventBuffer:
    """Shared rolling buffer. Consumers filter by severity."""

    def __init__(self, maxlen: int = 50) -> None:
        self._events: deque[BrainEvent] = deque(maxlen=maxlen)

    def append(self, event: BrainEvent) -> None:
        self._events.append(event)

    def extend(self, events: list[BrainEvent]) -> None:
        self._events.extend(events)

    def recent_at_least(self, min_severity: Severity, limit: int = 20) -> list[BrainEvent]:
        order = {Severity.TICK: 0, Severity.TACTICAL: 1, Severity.STRATEGIC: 2}
        threshold = order[min_severity]
        items = [e for e in self._events if order[e.severity] >= threshold]
        return items[-limit:]

    def all_recent(self, limit: int = 20) -> list[BrainEvent]:
        return list(self._events)[-limit:]
