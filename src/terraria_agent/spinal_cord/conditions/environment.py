from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.game_state import TerrainType
from terraria_agent.spinal_cord.bt.leaves import Condition

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class IsPitAhead(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.terrain_ahead == TerrainType.PIT


class IsBlockWallAhead(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.terrain_ahead == TerrainType.BLOCK_WALL


class IsDark(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.is_dark


class HasTreeNearby(Condition):
    def __init__(self, max_distance: float = 300.0, name: str = ""):
        super().__init__(name)
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        return any(
            o.type == "tree" and o.distance <= self.max_distance
            for o in ctx.game_state.objects
        )


class HasChestNearby(Condition):
    def __init__(self, max_distance: float = 300.0, name: str = ""):
        super().__init__(name)
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        return any(
            o.type == "chest" and o.distance <= self.max_distance
            for o in ctx.game_state.objects
        )
