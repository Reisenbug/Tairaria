from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class MoveLeft(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction="left"))
        return Status.SUCCESS


class MoveRight(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction="right"))
        return Status.SUCCESS


class Jump(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
        return Status.SUCCESS


class PlacePlatform(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.inventory.get("platform", 0) <= 0:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.PLACE_BLOCK, item="platform"))
        return Status.SUCCESS


class MoveToObject(Action):
    def __init__(self, object_type: str, name: str = ""):
        super().__init__(name)
        self.object_type = object_type

    def execute(self, ctx: TickContext) -> Status:
        targets = [o for o in ctx.game_state.objects if o.type == self.object_type]
        if not targets:
            return Status.FAILURE
        nearest = min(targets, key=lambda o: o.distance)
        if nearest.distance < 10.0:
            return Status.SUCCESS
        player_x = ctx.game_state.player.pos[0]
        direction = "right" if nearest.pos[0] > player_x else "left"
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))
        return Status.RUNNING
