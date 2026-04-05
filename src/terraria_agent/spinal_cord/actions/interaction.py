from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext

VALUABLE_DROPS = {"fruit", "gold_coin", "pet"}


class ChopTree(Action):
    def execute(self, ctx: TickContext) -> Status:
        trees = [o for o in ctx.game_state.objects if o.type == "tree"]
        if not trees:
            return Status.FAILURE
        for i, item in enumerate(ctx.game_state.hotbar):
            if item and "axe" in item:
                ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=i))
                break
        nearest = min(trees, key=lambda o: o.distance)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=nearest.pos))
        return Status.SUCCESS


class PickUpValuableDrop(Action):
    def execute(self, ctx: TickContext) -> Status:
        valuables = [
            o for o in ctx.game_state.objects
            if o.type in VALUABLE_DROPS
        ]
        if not valuables:
            return Status.FAILURE
        nearest = min(valuables, key=lambda o: o.distance)
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction="right" if nearest.pos[0] > ctx.game_state.player.pos[0] else "left"))
        ctx.action_buffer.append(GameAction(action=ActionType.PICK_UP))
        return Status.RUNNING if nearest.distance > 10.0 else Status.SUCCESS


class OpenChest(Action):
    def execute(self, ctx: TickContext) -> Status:
        chests = [o for o in ctx.game_state.objects if o.type == "chest"]
        if not chests:
            return Status.FAILURE
        nearest = min(chests, key=lambda o: o.distance)
        ctx.action_buffer.append(GameAction(action=ActionType.INTERACT, target=nearest.pos))
        return Status.SUCCESS


class PickUp(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.PICK_UP))
        return Status.SUCCESS
