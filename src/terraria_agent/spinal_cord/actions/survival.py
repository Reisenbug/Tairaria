from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class UsePotion(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.inventory.get("potion", 0) <= 0:
            return Status.FAILURE
        for i, item in enumerate(ctx.game_state.hotbar):
            if item and "potion" in item:
                ctx.action_buffer.append(GameAction(action=ActionType.USE_ITEM, slot=i))
                return Status.SUCCESS
        return Status.FAILURE


class PlaceTorch(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.inventory.get("torch", 0) <= 0:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.PLACE_BLOCK, item="torch"))
        return Status.SUCCESS


class SignalBrainEmergency(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.interrupt_brain = True
        ctx.interrupt_reason = "emergency: low health in combat"
        return Status.SUCCESS
