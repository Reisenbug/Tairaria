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


class IsWaterAhead(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.terrain_ahead == TerrainType.WATER


class IsLavaAhead(Condition):
    def check(self, ctx: TickContext) -> bool:
        return ctx.game_state.terrain_ahead == TerrainType.LAVA


class CanJumpOverObstacle(Condition):
    def check(self, ctx: TickContext) -> bool:
        scan = ctx.game_state.terrain_scan
        if scan is None:
            return False
        if scan.terrain_type == TerrainType.BLOCK_WALL:
            from terraria_agent.cerebellum.terra_blind_client import _jump_peak_tiles
            return scan.depth_or_height <= _jump_peak_tiles(ctx.game_state.movement)
        return False


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
    """Chebyshev gap between player AABB and chest AABB in tiles (<= max_gap)."""

    def __init__(self, max_gap: int = 3, name: str = ""):
        super().__init__(name)
        self.max_gap = max_gap

    def check(self, ctx: TickContext) -> bool:
        p = ctx.game_state.player
        px = int(p.pos[0] / 16)
        py = int(p.pos[1] / 16)
        pw = max(1, int(p.width / 16)) if p.width else 2
        ph = max(1, int(p.height / 16)) if p.height else 3
        p_x1, p_x2 = px, px + pw - 1
        p_y1, p_y2 = py, py + ph - 1
        for o in ctx.game_state.objects:
            if o.type != "chest":
                continue
            cx, cy = o.tile_pos
            c_x1, c_x2 = cx, cx + 1
            c_y1, c_y2 = cy, cy + 1
            dx = max(0, p_x1 - c_x2, c_x1 - p_x2)
            dy = max(0, p_y1 - c_y2, c_y1 - p_y2)
            if max(dx, dy) <= self.max_gap:
                return True
        return False
