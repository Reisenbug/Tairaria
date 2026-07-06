from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.spinal_cord.bt.leaves import Condition

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class HasItem(Condition):
    def __init__(self, item: str, min_count: int = 1, name: str = ""):
        super().__init__(name)
        self.item = item
        self.min_count = min_count

    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.inventory.get(self.item, 0) >= self.min_count


class HasEnoughWood(Condition):
    def __init__(self, amount: int = 10, name: str = ""):
        super().__init__(name)
        self.amount = amount

    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.inventory.get("wood", 0) >= self.amount


class HasTorch(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.inventory.get("torch", 0) > 0


class HasPotion(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.inventory.get("potion", 0) > 0


class HasPlatforms(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.inventory.get("platform", 0) > 0


class HasPickaxe(Condition):
    def check(self, ctx: TickContext) -> bool:
        return any(s and "pickaxe" in s for s in ctx.game_state.hotbar if s)
