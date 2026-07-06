from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import player_center_world
from terraria_agent.models.game_state import CombatMode, Enemy, EnemyThreat, GameState
from terraria_agent.spinal_cord.bt.leaves import Condition

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext

_TILE_SIZE = 16.0

_MODE_ENGAGE_THREATS = {
    CombatMode.AGGRESSIVE: {EnemyThreat.WEAK, EnemyThreat.MEDIUM, EnemyThreat.DANGEROUS, EnemyThreat.BOSS},
    CombatMode.CAUTIOUS: {EnemyThreat.DANGEROUS, EnemyThreat.BOSS},
    CombatMode.PACIFIST: {EnemyThreat.BOSS},
    CombatMode.RETREAT: set(),
}


def _has_line_of_sight(gs: GameState, enemy: Enemy) -> bool:
    tw = gs.tile_window
    if tw is None or not tw.rows:
        return True
    ax, ay = player_center_world(gs.player)
    bx = enemy.pos[0] + enemy.width / 2.0
    by = enemy.pos[1] + enemy.height / 2.0
    dx = bx - ax
    dy = by - ay
    dist_tiles = ((dx * dx + dy * dy) ** 0.5) / _TILE_SIZE
    steps = max(2, int(dist_tiles * 2))
    for i in range(1, steps):
        t = i / steps
        tx = int((ax + dx * t) / _TILE_SIZE)
        ty = int((ay + dy * t) / _TILE_SIZE)
        tile = tw.tile_at(tx, ty)
        if tile is not None and tile.solid and not tile.platform:
            return False
    return True


class HasEnemiesNearby(Condition):
    def __init__(self, max_distance: float = 400.0, name: str = ""):
        super().__init__(name)
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        return any(e.distance <= self.max_distance for e in ctx.game_state.enemies)


class IsSurrounded(Condition):
    def __init__(self, min_enemies: int = 3, max_distance: float = 300.0, name: str = ""):
        super().__init__(name)
        self.min_enemies = min_enemies
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        nearby = [e for e in ctx.game_state.enemies if e.distance <= self.max_distance]
        return len(nearby) >= self.min_enemies


class EnemyIsWeak(Condition):
    def check(self, ctx: TickContext) -> bool:
        return any(e.threat == EnemyThreat.WEAK for e in ctx.game_state.enemies)


class EnemyIsMedium(Condition):
    def check(self, ctx: TickContext) -> bool:
        return any(e.threat == EnemyThreat.MEDIUM for e in ctx.game_state.enemies)


class EnemyIsDangerous(Condition):
    def check(self, ctx: TickContext) -> bool:
        return any(
            e.threat in (EnemyThreat.DANGEROUS, EnemyThreat.BOSS)
            for e in ctx.game_state.enemies
        )


class HasUrgentThreat(Condition):
    def check(self, ctx: TickContext) -> bool:
        return any(t.urgent for t in ctx.game_state.threats)


class IsEnemyBlockingPath(Condition):
    def __init__(self, max_distance: float = 4.0, name: str = ""):
        super().__init__(name)
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        player = ctx.game_state.player
        facing_right = player.direction == "right"
        px = player.pos[0] + player.width / 2.0
        py_top = player.pos[1]
        py_bot = player.pos[1] + player.height
        for e in ctx.game_state.enemies:
            if e.distance > self.max_distance:
                continue
            ex = e.pos[0] + e.width / 2.0
            ahead = (ex > px) if facing_right else (ex < px)
            if not ahead:
                continue
            ey_top = e.pos[1]
            ey_bot = e.pos[1] + e.height
            if ey_bot < py_top or ey_top > py_bot:
                continue
            if not _has_line_of_sight(ctx.game_state, e):
                continue
            return True
        return False


class ShouldEngage(Condition):
    def __init__(self, max_distance: float = 25.0, name: str = ""):
        super().__init__(name)
        self.max_distance = max_distance

    def check(self, ctx: TickContext) -> bool:
        engage = _MODE_ENGAGE_THREATS.get(ctx.combat_mode, set())
        if not engage:
            return False
        for e in ctx.game_state.enemies:
            if e.distance > self.max_distance:
                continue
            if e.threat not in engage:
                continue
            if not _has_line_of_sight(ctx.game_state, e):
                continue
            return True
        return False
