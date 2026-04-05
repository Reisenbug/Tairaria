from __future__ import annotations

from typing import Protocol

from terraria_agent.models.actions import GameAction


class Controller(Protocol):
    def execute(self, actions: list[GameAction]) -> None: ...
    def release_all(self) -> None: ...
