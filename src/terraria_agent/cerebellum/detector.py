from __future__ import annotations

from typing import Protocol

from terraria_agent.models.game_state import GameState


class Detector(Protocol):
    def detect(self, frame: bytes) -> GameState: ...
