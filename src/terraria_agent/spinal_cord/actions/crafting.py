from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class CraftPlatforms(Action):
    def execute(self, ctx: TickContext) -> Status:
        wood = ctx.game_state.inventory.get("wood", 0)
        if wood < 1:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.CRAFT, item="platform", quantity=wood))
        return Status.SUCCESS
