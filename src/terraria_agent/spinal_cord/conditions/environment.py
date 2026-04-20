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


class IsCliffEdge(Condition):
    """Ahead terrain is un-jumpable. FAIL walking to stop bot.
    Two stop conditions:
      1. Gap (no-solid column with drop>jump_recover) wider than jump_reach.
      2. Cumulative ground descent over lookahead >= fatal_depth (slope trap).
    On-ground only."""

    def __init__(self, lookahead: int = 15, jump_reach: int = 5,
                 jump_recover: int = 6, fatal_depth: int = 25, name: str = ""):
        super().__init__(name)
        self.lookahead = lookahead
        self.jump_reach = jump_reach
        self.jump_recover = jump_recover
        self.fatal_depth = fatal_depth

    def check(self, ctx: TickContext) -> bool:
        from terraria_agent.diag_log import diag
        gs = ctx.game_state
        p = gs.player
        if abs(p.velocity[1]) > 0.5:
            diag("cliff_edge", f"skip airborne vy={p.velocity[1]} pos={p.pos}")
            return False
        tw = gs.tile_window
        if not tw or not tw.rows:
            diag("cliff_edge", f"skip no_tile_window pos={p.pos}")
            return False
        fatal = 10_000 if gs.movement.no_fall_dmg else self.fatal_depth
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        feet_y = int((p.pos[1] + p.height) / 16.0)
        sign = 1 if p.direction == "right" else -1

        def _ground_drop(cx: int, from_y: int) -> int:
            for dy in range(0, 60):
                t = tw.tile_at(cx, from_y + dy)
                if t is not None and t.solid:
                    return dy
            return 60

        gap_start = None
        gap_width = 0
        ground_y = feet_y
        max_cum = 0
        drops_log: list[int] = []
        reason = None

        for i in range(1, self.lookahead + 1):
            cx = pcx + sign * i
            d = _ground_drop(cx, ground_y)
            drops_log.append(d)
            if d >= self.fatal_depth:
                gap_width += 1
                if gap_start is None:
                    gap_start = i
                if gap_width > self.jump_reach:
                    reason = f"gap_wide_at_i{i}"
                    break
            elif d > self.jump_recover:
                gap_width += 1
                if gap_start is None:
                    gap_start = i
                if gap_width > self.jump_reach:
                    reason = f"gap_wide_at_i{i}"
                    break
            else:
                gap_start = None
                gap_width = 0
                ground_y = ground_y + d
                cum = ground_y - feet_y
                if cum > max_cum:
                    max_cum = cum
                if cum >= fatal:
                    reason = f"slope_drop_cum{cum}"
                    break

        result = reason is not None
        diag(
            "cliff_edge",
            f"pos={p.pos} dir={p.direction} pcx={pcx} feet_y={feet_y} "
            f"drops={drops_log} max_cum={max_cum} fatal={fatal} "
            f"jump_reach={self.jump_reach} reason={reason} result={result}",
        )
        return result


class IsCaveEntrance(Condition):
    """Forward-overhead rectangle mostly covered by solid tiles = cave entrance.
    Scan forward `forward` cols × up `up` rows above player head.
    Column is "capped" if it contains any solid in the rect.
    If capped_cols >= min_cols → cave entrance."""

    def __init__(self, forward: int = 20, up: int = 8, min_cols: int = 10, name: str = ""):
        super().__init__(name)
        self.forward = forward
        self.up = up
        self.min_cols = min_cols

    def check(self, ctx: TickContext) -> bool:
        from terraria_agent.diag_log import diag
        gs = ctx.game_state
        tw = gs.tile_window
        if not tw or not tw.rows:
            return False
        p = gs.player
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        head_y = int(p.pos[1] / 16.0)
        sign = 1 if p.direction == "right" else -1

        capped_cols = 0
        for i in range(1, self.forward + 1):
            cx = pcx + sign * i
            for dy in range(1, self.up + 1):
                t = tw.tile_at(cx, head_y - dy)
                if t is not None and t.solid:
                    capped_cols += 1
                    break

        result = capped_cols >= self.min_cols
        diag(
            "cliff_edge",
            f"cave_entrance pos={p.pos} dir={p.direction} pcx={pcx} head_y={head_y} "
            f"capped_cols={capped_cols}/{self.forward} min={self.min_cols} result={result}",
        )
        return result


class HasChestNearby(Condition):
    """Chebyshev gap between player AABB (expanded by max_gap on each side) and any unlooted chest."""

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
            if o.type != "chest" or o.tile_pos in ctx.looted_chests:
                continue
            cx, cy = o.tile_pos
            c_x1, c_x2 = cx, cx + 1
            c_y1, c_y2 = cy, cy + 1
            dx = max(0, p_x1 - c_x2, c_x1 - p_x2)
            dy = max(0, p_y1 - c_y2, c_y1 - p_y2)
            if max(dx, dy) <= self.max_gap:
                return True
        return False
