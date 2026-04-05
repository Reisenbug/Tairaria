from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.game_state import EnemyThreat
from terraria_agent.spinal_cord.bt.leaves import Condition

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


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
