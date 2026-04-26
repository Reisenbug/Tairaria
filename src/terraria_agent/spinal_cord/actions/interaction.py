from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import tile_offset_world, world_to_screen
from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext

VALUABLE_DROPS = {"fruit", "gold_coin", "pet"}

_big_trees_chopped = 0
_BIG_TREE_LIMIT = 2
_BIG_TREE_HEIGHT = 16


_TREE_TRUNK_TYPES = (5, 72, 323)


def _tree_height(ctx: TickContext, tree_obj) -> int:
    tw = ctx.game_state.tile_window
    if tw is None:
        return 0
    tx, ty = tree_obj.tile_pos
    height = 0
    for dy in range(0, 40):
        t = tw.tile_at(tx, ty - dy)
        if t is not None and t.active and t.type in _TREE_TRUNK_TYPES:
            height += 1
        elif height > 0:
            break
    return height


def _find_axe_slot(ctx: TickContext) -> int | None:
    for s in ctx.game_state.inventory_slots[:10]:
        if s.is_axe:
            return s.slot_index
    return None


def _ensure_axe(ctx: TickContext) -> bool:
    slot = _find_axe_slot(ctx)
    if slot is None:
        return False
    if ctx.game_state.player.selected_slot != slot:
        ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=slot))
    return True


class ShakeTree(Action):
    """Only acts if there's actually a tree in strike range; else SUCCESS (no axe swap)."""

    def execute(self, ctx: TickContext) -> Status:
        p = ctx.game_state.player
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        pcy = int((p.pos[1] + p.height / 2.0) / 16.0)
        sign = 1 if p.direction == "right" else -1
        tw = ctx.game_state.tile_window
        tree_in_range = False
        if tw is not None:
            for dx in range(1, 4):
                for dy in range(-3, 3):
                    t = tw.tile_at(pcx + sign * dx, pcy + dy)
                    if t is not None and t.active and t.type in (5, 72, 323):
                        tree_in_range = True
                        break
                if tree_in_range:
                    break
        if not tree_in_range:
            return Status.SUCCESS
        if not _ensure_axe(ctx):
            return Status.SUCCESS
        facing = ctx.game_state.player.direction
        s = 1.0 if facing == "right" else -1.0
        target = tile_offset_world(ctx.game_state.player, s * 2.0, 0.0)
        screen_xy = world_to_screen(target, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        return Status.SUCCESS


class ChopBigTree(Action):
    def execute(self, ctx: TickContext) -> Status:
        global _big_trees_chopped
        if _big_trees_chopped >= _BIG_TREE_LIMIT:
            return Status.FAILURE
        trees = [o for o in ctx.game_state.objects if o.type == "tree"]
        big_trees = [t for t in trees if _tree_height(ctx, t) >= _BIG_TREE_HEIGHT]
        if not big_trees:
            return Status.FAILURE
        target = None
        if ctx.active_goal and ctx.active_goal.kind == "chop_tree":
            tt = ctx.active_goal.target_tile
            for t in big_trees:
                if t.tile_pos == tt:
                    target = t
                    break
        if target is None:
            target = min(big_trees, key=lambda o: o.distance)
        if target.distance > 5.0:
            if ctx.active_goal and ctx.active_goal.kind == "chop_tree":
                ctx.active_goal.attempts += 1
            return Status.FAILURE
        if not _ensure_axe(ctx):
            return Status.FAILURE
        screen_xy = world_to_screen(target.pos, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        ctx.bt_trace.append(f"ChopBig({_big_trees_chopped}/{_BIG_TREE_LIMIT})")
        return Status.RUNNING


class BigTreeChopped(Action):
    def execute(self, ctx: TickContext) -> Status:
        global _big_trees_chopped
        _big_trees_chopped += 1
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


class OpenChest(Action):
    def execute(self, ctx: TickContext) -> Status:
        if ctx.game_state.chest_open:
            ctx.bt_trace.append("OpenChest: already open")
            return Status.SUCCESS
        chests = [o for o in ctx.game_state.objects if o.type == "chest"]
        if not chests:
            return Status.FAILURE
        nearest = min(chests, key=lambda o: o.distance)
        tx, ty = nearest.tile_pos
        ctx.action_buffer.append(GameAction(action=ActionType.INTERACT, tile=(tx, ty)))
        ctx.bt_trace.append(f"OpenChest@tile({tx},{ty})")
        return Status.RUNNING


class LootAll(Action):
    def execute(self, ctx: TickContext) -> Status:
        if not ctx.game_state.chest_open:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.LOOT_ALL))
        ctx.bt_trace.append("LootAll")
        return Status.SUCCESS


class MarkChestLooted(Action):
    def execute(self, ctx: TickContext) -> Status:
        chests = [o for o in ctx.game_state.objects if o.type == "chest"]
        if chests:
            nearest = min(chests, key=lambda o: o.distance)
            ctx.looted_chests.add(nearest.tile_pos)
        return Status.SUCCESS


class PickUp(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.PICK_UP))
        return Status.SUCCESS
