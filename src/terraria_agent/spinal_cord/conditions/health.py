from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.spinal_cord.bt.leaves import Condition

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class IsHealthCritical(Condition):
    def __init__(self, threshold: float = 0.2, name: str = ""):
        super().__init__(name)
        self.threshold = threshold

    def check(self, ctx: TickContext) -> bool:
        p = ctx.game_state.player
        return p.hp / p.max_hp < self.threshold


class IsHealthLow(Condition):
    def __init__(self, threshold: float = 0.5, name: str = ""):
        super().__init__(name)
        self.threshold = threshold

    def check(self, ctx: TickContext) -> bool:
        p = ctx.game_state.player
        return p.hp / p.max_hp < self.threshold
