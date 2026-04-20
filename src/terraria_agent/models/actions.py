from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ActionType(str, Enum):
    MOVE = "move"
    JUMP = "jump"
    ATTACK = "attack"
    USE_ITEM = "use_item"
    SWITCH_SLOT = "switch_slot"
    PLACE_BLOCK = "place_block"
    PLACE = "place"
    PLACE_STOP = "place_stop"
    INTERACT = "interact"
    CRAFT = "craft"
    PICK_UP = "pick_up"
    KEY_PRESS = "key_press"
    LOOT_ALL = "loot_all"
    QUICK_HEAL = "quick_heal"
    NONE = "none"


class GameAction(BaseModel):
    action: ActionType
    direction: Optional[str] = None
    target: Optional[tuple[float, float]] = None
    tile: Optional[tuple[int, int]] = None
    slot: Optional[int] = None
    item: Optional[str] = None
    quantity: Optional[int] = None
    dx: Optional[int] = None
    dy: Optional[int] = None
    duration_frames: Optional[int] = None
    smart_cursor: Optional[bool] = None


class ActionBundle(BaseModel):
    actions: list[GameAction]
    priority: int = 0
    interrupt_brain: bool = False
    interrupt_reason: str = ""
