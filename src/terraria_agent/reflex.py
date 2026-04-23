from __future__ import annotations

from terraria_agent.models.game_state import GameState

_HEAL_HP_RATIO = 0.6


def check(state: GameState) -> dict | None:
    p = state.player

    if p.hp < p.max_hp * _HEAL_HP_RATIO:
        potions = [s for s in state.inventory_slots if s.name and "治疗药水" in s.name and s.stack > 0]
        if potions:
            return {"quick_heal": True}

    return None
