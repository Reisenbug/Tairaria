from __future__ import annotations

from typing import Protocol

import numpy as np

from terraria_agent.models.game_state import GameState


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> GameState: ...
