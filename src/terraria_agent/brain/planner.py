from __future__ import annotations

from typing import Protocol

from terraria_agent.models.game_state import GameState
from terraria_agent.models.task_queue import TaskQueue


class Planner(Protocol):
    def plan(self, state: GameState, memory: dict) -> TaskQueue: ...
