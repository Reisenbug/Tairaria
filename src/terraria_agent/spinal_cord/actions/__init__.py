from .movement import MoveLeft, MoveRight, Jump, PlacePlatform, BuildBridge, MoveToObject, MineForward, Swim
from .combat import AttackNearest, SwitchToSword, SwitchToBestWeapon, Dodge
from .interaction import ShakeTree, ChopBigTree, BigTreeChopped, PickUpValuableDrop, OpenChest, PickUp
from .survival import UsePotion, PlaceTorch, SignalBrainEmergency
from .crafting import CraftPlatforms

__all__ = [
    "MoveLeft", "MoveRight", "Jump", "PlacePlatform", "MoveToObject", "MineForward",
    "AttackNearest", "SwitchToSword", "SwitchToBestWeapon", "Dodge",
    "ShakeTree", "ChopBigTree", "BigTreeChopped", "PickUpValuableDrop", "OpenChest", "PickUp",
    "UsePotion", "PlaceTorch", "SignalBrainEmergency",
    "CraftPlatforms",
]
