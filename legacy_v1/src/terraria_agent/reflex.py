from __future__ import annotations

from terraria_agent.models.game_state import GameState

_HEAL_HP_RATIO = 0.6
_TREE_HEIGHT_MIN = 15


def check(state: GameState, trees_chopped: int = 0, tree_chop_limit: int = 999) -> dict | None:
    p = state.player

    if p.hp < p.max_hp * _HEAL_HP_RATIO:
        potions = [s for s in state.inventory_slots if s.name and "治疗药水" in s.name and s.stack > 0]
        if potions:
            return {"ctrl": {"quick_heal": True}}

    if trees_chopped < tree_chop_limit:
        big_trees = [o for o in state.objects if o.type == "tree" and o.height >= _TREE_HEIGHT_MIN]
        if big_trees:
            return {"goal": "chop_tree", "target": {"type": "tree"}, "timeout": 30}

    return None
