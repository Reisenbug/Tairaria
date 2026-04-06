from __future__ import annotations

import time

import numpy as np

from terraria_agent.cerebellum.damage_detector import DamageDetector
from terraria_agent.cerebellum.ui_reader import UIReader, UIState
from terraria_agent.models.game_state import GameState, Player


class UIVisionDetector:
    def __init__(self, ui_reader: UIReader | None = None) -> None:
        self._ui_reader = ui_reader or UIReader()
        self._damage = DamageDetector()

    def detect(self, frame: np.ndarray) -> GameState:
        ui = self._ui_reader.read(frame)
        damage = self._damage.update(ui.hp, ui.max_hp, time.time())
        return self._build_game_state(ui, damage)

    def _build_game_state(self, ui: UIState, damage) -> GameState:
        player = Player(
            hp=ui.hp,
            max_hp=max(ui.max_hp, 1),
            pos=(0.0, 0.0),
            buffs=["unknown"] if ui.buff_active else [],
            took_damage=damage.took_damage,
            damage_amount=damage.damage_amount,
            danger_level=damage.danger_level,
            hp_trend=damage.hp_trend,
            selected_slot=ui.selected_slot,
            inventory_open=ui.inventory_open,
        )
        return GameState(player=player)

    def reset(self) -> None:
        self._damage.reset()
