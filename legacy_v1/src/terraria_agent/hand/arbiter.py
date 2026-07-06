from __future__ import annotations

from enum import Enum

from terraria_agent.models.actions import ActionType, GameAction


class Resource(str, Enum):
    MOUSE = "mouse"
    MOVEMENT = "movement"
    JUMP = "jump"
    HOTBAR = "hotbar"
    HTTP = "http"


_RESOURCE_MAP: dict[ActionType, tuple[Resource, ...]] = {
    ActionType.MOVE: (Resource.MOVEMENT,),
    ActionType.JUMP: (Resource.JUMP,),
    ActionType.ATTACK: (Resource.MOUSE,),
    ActionType.USE_ITEM: (Resource.MOUSE, Resource.HOTBAR),
    ActionType.SWITCH_SLOT: (Resource.HOTBAR,),
    ActionType.PLACE_BLOCK: (Resource.MOUSE,),
    ActionType.INTERACT: (Resource.MOUSE,),
    ActionType.CRAFT: (),
    ActionType.KEY_PRESS: (),
    ActionType.LOOT_ALL: (Resource.HTTP,),
    ActionType.QUICK_HEAL: (Resource.HTTP,),
    ActionType.PICK_UP: (),
    ActionType.NONE: (),
}


def arbitrate(actions: list[GameAction]) -> tuple[list[GameAction], list[tuple[GameAction, Resource]]]:
    """Filter actions so no two claim the same resource. Earlier actions win.

    Returns (kept, dropped_with_reason). Order of `actions` is the priority order.
    """
    claimed: set[Resource] = set()
    kept: list[GameAction] = []
    dropped: list[tuple[GameAction, Resource]] = []
    for a in actions:
        resources = _RESOURCE_MAP.get(a.action, ())
        conflict = next((r for r in resources if r in claimed), None)
        if conflict is not None:
            dropped.append((a, conflict))
            continue
        for r in resources:
            claimed.add(r)
        kept.append(a)
    return kept, dropped
