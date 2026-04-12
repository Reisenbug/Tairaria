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
    INTERACT = "interact"
    CRAFT = "craft"
    PICK_UP = "pick_up"
    KEY_PRESS = "key_press"
    NONE = "none"


class GameAction(BaseModel):
    action: ActionType
    direction: Optional[str] = None
    target: Optional[tuple[float, float]] = None
    slot: Optional[int] = None
    item: Optional[str] = None
    quantity: Optional[int] = None


class ActionBundle(BaseModel):
    actions: list[GameAction]
    priority: int = 0
    interrupt_brain: bool = False
    interrupt_reason: str = ""
