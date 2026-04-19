from __future__ import annotations

import time
from dataclasses import dataclass, field

from terraria_agent.brain.events import BrainEvent, classify
from terraria_agent.models.actions import GameAction
from terraria_agent.models.game_state import CombatMode, GameState
from terraria_agent.models.goal import Goal
from terraria_agent.models.task_queue import TaskQueue

__all__ = ["BrainEvent", "TickContext"]


@dataclass
class TickContext:
    game_state: GameState
    task_queue: TaskQueue
    action_buffer: list[GameAction] = field(default_factory=list)
    brain_events: list[BrainEvent] = field(default_factory=list)
    interrupt_brain: bool = False
    interrupt_reason: str = ""
    dt: float = 0.2
    bt_trace: list[str] = field(default_factory=list)
    smart_cursor: bool = False
    exclusive_active: bool = False
    looted_chests: set = field(default_factory=set)
    combat_mode: CombatMode = CombatMode.CAUTIOUS
    active_goal: Goal | None = None

    def report(self, event_type: str, **details) -> None:
        self.brain_events.append(BrainEvent(
            type=event_type,
            details=details,
            severity=classify(event_type),
            timestamp=time.time(),
        ))
