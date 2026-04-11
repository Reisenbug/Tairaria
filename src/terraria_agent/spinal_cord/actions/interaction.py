from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import world_to_screen
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
        screen_xy = world_to_screen(nearest.pos, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
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
        if ctx.smart_cursor:
            player_screen = world_to_screen(ctx.game_state.player.pos, ctx.game_state.camera)
            chest_screen = world_to_screen(nearest.pos, ctx.game_state.camera)
            nearby = (
                (player_screen[0] + chest_screen[0]) / 2,
                (player_screen[1] + chest_screen[1]) / 2,
            )
            ctx.action_buffer.append(GameAction(action=ActionType.INTERACT, target=nearby))
            ctx.bt_trace.append(f"OpenChest(sc=on)@{int(nearby[0])},{int(nearby[1])}")
        else:
            screen_xy = world_to_screen(nearest.pos, ctx.game_state.camera)
            ctx.action_buffer.append(GameAction(action=ActionType.INTERACT, target=screen_xy))
            ctx.bt_trace.append(f"OpenChest(sc=off)@{screen_xy[0]},{screen_xy[1]}")
        return Status.SUCCESS


class PickUp(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.PICK_UP))
        return Status.SUCCESS
