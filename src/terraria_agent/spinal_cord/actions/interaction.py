from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import tile_offset_world, world_to_screen
from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext

VALUABLE_DROPS = {"fruit", "gold_coin", "pet"}

_AXE_SLOT = 2
_big_trees_chopped = 0
_BIG_TREE_LIMIT = 2
_BIG_TREE_HEIGHT = 16
is_chopping = False


def _tree_height(ctx: TickContext, tree_obj) -> int:
    tw = ctx.game_state.tile_window
    if tw is None:
        return 0
    tx, ty = tree_obj.tile_pos
    height = 0
    for dy in range(0, 40):
        t = tw.tile_at(tx, ty - dy)
        if t is not None and t.active and not t.solid:
            height += 1
        elif height > 0:
            break
    return height


def _ensure_axe(ctx: TickContext) -> None:
    if ctx.game_state.player.selected_slot != _AXE_SLOT:
        ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=_AXE_SLOT))


class ShakeTree(Action):
    def execute(self, ctx: TickContext) -> Status:
        _ensure_axe(ctx)
        if not ctx.game_state.smart_cursor:
            ctx.action_buffer.append(GameAction(action=ActionType.KEY_PRESS, item="smart_cursor"))
        facing = ctx.game_state.player.direction
        sign = 1.0 if facing == "right" else -1.0
        target = tile_offset_world(ctx.game_state.player, sign * 2.0, 0.0)
        screen_xy = world_to_screen(target, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        return Status.SUCCESS


class ChopBigTree(Action):
    def execute(self, ctx: TickContext) -> Status:
        global _big_trees_chopped, is_chopping
        if _big_trees_chopped >= _BIG_TREE_LIMIT:
            is_chopping = False
            return Status.FAILURE
        trees = [o for o in ctx.game_state.objects if o.type == "tree"]
        big_trees = [t for t in trees if _tree_height(ctx, t) >= _BIG_TREE_HEIGHT]
        if not big_trees:
            is_chopping = False
            return Status.FAILURE
        nearest = min(big_trees, key=lambda o: o.distance)
        if nearest.distance > 4.0:
            is_chopping = False
            return Status.FAILURE
        is_chopping = True
        _ensure_axe(ctx)
        screen_xy = world_to_screen(nearest.pos, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        ctx.bt_trace.append(f"ChopBig({_big_trees_chopped}/{_BIG_TREE_LIMIT})")
        return Status.RUNNING


class BigTreeChopped(Action):
    def execute(self, ctx: TickContext) -> Status:
        global _big_trees_chopped, is_chopping
        _big_trees_chopped += 1
        is_chopping = False
        ctx.bt_trace.append(f"BigTreeDone({_big_trees_chopped}/{_BIG_TREE_LIMIT})")
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


class EnsureSmartCursorOn(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.smart_cursor:
            return Status.SUCCESS
        ctx.action_buffer.append(GameAction(action=ActionType.KEY_PRESS, item="smart_cursor"))
        ctx.bt_trace.append("SmartCursor->ON")
        return Status.RUNNING


class OpenChest(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.chest_open:
            ctx.bt_trace.append("OpenChest: already open")
            return Status.SUCCESS
        chests = [o for o in ctx.game_state.objects if o.type == "chest"]
        if not chests:
            return Status.FAILURE
        nearest = min(chests, key=lambda o: o.distance)
        player_screen = world_to_screen(ctx.game_state.player.pos, ctx.game_state.camera)
        chest_screen = world_to_screen(nearest.pos, ctx.game_state.camera)
        nearby = (
            (player_screen[0] + chest_screen[0]) / 2,
            (player_screen[1] + chest_screen[1]) / 2,
        )
        ctx.action_buffer.append(GameAction(action=ActionType.INTERACT, target=nearby))
        ctx.bt_trace.append(f"OpenChest@{int(nearby[0])},{int(nearby[1])}")
        return Status.RUNNING


class LootAll(Action):
    def execute(self, ctx: TickContext) -> Status:
        if not ctx.game_state.chest_open:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.LOOT_ALL))
        ctx.bt_trace.append("LootAll")
        return Status.SUCCESS


class PickUp(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.PICK_UP))
        return Status.SUCCESS
