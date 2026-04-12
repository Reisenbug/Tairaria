from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import tile_offset_world, world_to_screen
from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


_STUCK_VELOCITY = 0.1


def _emit_move(ctx: TickContext, direction: str) -> None:
    ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))
    if abs(ctx.game_state.player.velocity[0]) < _STUCK_VELOCITY:
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))


class MoveLeft(Action):
    def execute(self, ctx: TickContext) -> Status:
        _emit_move(ctx, "left")
        return Status.SUCCESS


class MoveRight(Action):
    def execute(self, ctx: TickContext) -> Status:
        _emit_move(ctx, "right")
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


class MineForward(Action):
    def __init__(self, dx_tiles: float = 1.0, dy_tiles: float = 0.0, name: str = ""):
        super().__init__(name)
        self.dx_tiles = dx_tiles
        self.dy_tiles = dy_tiles

    def execute(self, ctx: TickContext) -> Status:
        pickaxe_slot = None
        for slot in ctx.game_state.inventory_slots[:10]:
            if slot.is_pickaxe:
                pickaxe_slot = slot.slot_index
                break
        if pickaxe_slot is None:
            return Status.FAILURE
        if ctx.game_state.player.selected_slot != pickaxe_slot:
            ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=pickaxe_slot))

        facing = ctx.game_state.player.direction
        sign = 1.0 if facing == "right" else -1.0
        target_world = tile_offset_world(ctx.game_state.player, sign * self.dx_tiles, self.dy_tiles)
        screen_xy = world_to_screen(target_world, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        ctx.bt_trace.append(f"MineForward({facing},slot={pickaxe_slot})@{screen_xy[0]},{screen_xy[1]}")
        return Status.SUCCESS


class MoveToObject(Action):
    def __init__(self, object_type: str, reach_tiles: float = 4.0, name: str = ""):
        super().__init__(name)
        self.object_type = object_type
        self.reach_tiles = reach_tiles

    def execute(self, ctx: TickContext) -> Status:
        targets = [o for o in ctx.game_state.objects if o.type == self.object_type]
        if not targets:
            return Status.FAILURE
        nearest = min(targets, key=lambda o: o.distance)
        if nearest.distance <= self.reach_tiles:
            return Status.SUCCESS
        player_x = ctx.game_state.player.pos[0]
        direction = "right" if nearest.pos[0] > player_x else "left"
        _emit_move(ctx, direction)
        return Status.RUNNING
