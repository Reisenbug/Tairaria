from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import tile_offset_world, world_to_screen
from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


def _emit_move(ctx: TickContext, direction: str) -> None:
    ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))


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


class BuildBridge(Action):
    """EXCLUSIVE task: walk forward while holding place-key with SmartCursor on.
    Terraria auto-selects the reachable empty tile in facing direction.
    Completes when IsCliffEdge clears (can walk safely again)."""

    def execute(self, ctx: TickContext) -> Status:
        from terraria_agent.spinal_cord.conditions.environment import IsCliffEdge
        if not IsCliffEdge().check(ctx):
            return Status.SUCCESS

        platform_slot = next(
            (s.slot_index for s in ctx.game_state.inventory_slots[:10] if s.is_platform),
            None,
        )
        if platform_slot is None:
            return Status.FAILURE

        if not ctx.game_state.smart_cursor:
            ctx.action_buffer.append(GameAction(action=ActionType.KEY_PRESS, item="smart_cursor"))
            return Status.RUNNING

        if ctx.game_state.player.selected_slot != platform_slot:
            ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=platform_slot))
            return Status.RUNNING

        direction = ctx.game_state.player.direction
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))
        ctx.action_buffer.append(GameAction(action=ActionType.PLACE_BLOCK, item="platform"))
        ctx.bt_trace.append(f"BuildBridge({direction})")
        return Status.RUNNING


class JumpOverCave(Action):
    """Skirt cave entrance: jump + keep walking forward.
    Relies on mod auto-jump to climb overhang. FAILURE if still on ground
    and not moving after a few ticks (= overhang too high → bot stops)."""

    def __init__(self, stuck_limit: int = 6, name: str = ""):
        super().__init__(name)
        self.stuck_limit = stuck_limit
        self._stuck_ticks = 0

    def execute(self, ctx: TickContext) -> Status:
        p = ctx.game_state.player
        direction = p.direction
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))
        if self._head_clear(ctx):
            ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
            ctx.bt_trace.append(f"JumpOverCave({direction},jump)")
        else:
            ctx.bt_trace.append(f"JumpOverCave({direction},blocked)")
        on_ground = abs(p.velocity[1]) <= 0.5
        moving = abs(p.velocity[0]) > 0.3
        if on_ground and not moving:
            self._stuck_ticks += 1
            if self._stuck_ticks >= self.stuck_limit:
                self._stuck_ticks = 0
                return Status.FAILURE
        else:
            self._stuck_ticks = 0
        return Status.RUNNING

    @staticmethod
    def _head_clear(ctx: TickContext) -> bool:
        gs = ctx.game_state
        tw = gs.tile_window
        if not tw or not tw.rows:
            return True
        p = gs.player
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        head_y = int(p.pos[1] / 16.0)
        for dy in range(1, 3):
            t = tw.tile_at(pcx, head_y - dy)
            if t is not None and t.solid:
                return False
        return True

    def reset(self) -> None:
        self._stuck_ticks = 0


class PillarJump(Action):
    """Rise N tiles by jumping + holding platform-place below feet.
    Starts a /place hold (cursor anchored to tile below-front of feet), then
    emits JUMP edges until N tiles gained or budget exhausted. Always issues
    /place_stop on exit. Requires platform in hotbar."""

    def __init__(self, target_rise: int = 3, budget_ticks: int = 40, name: str = ""):
        super().__init__(name)
        self.target_rise = target_rise
        self.budget_ticks = budget_ticks
        self._start_y: float | None = None
        self._ticks = 0
        self._place_started = False

    def execute(self, ctx: TickContext) -> Status:
        p = ctx.game_state.player
        platform_slot = next(
            (s.slot_index for s in ctx.game_state.inventory_slots[:10] if s.is_platform),
            None,
        )
        if platform_slot is None:
            return self._finish(ctx, Status.FAILURE)

        if self._start_y is None:
            self._start_y = p.pos[1]
        self._ticks += 1

        sign = 1 if p.direction == "right" else -1
        dx = 1 if sign > 0 else -2

        if not self._place_started:
            ctx.action_buffer.append(GameAction(
                action=ActionType.PLACE,
                dx=dx, dy=1, slot=platform_slot,
                duration_frames=self.budget_ticks * 12,
                smart_cursor=False,
            ))
            self._place_started = True

        on_ground = abs(p.velocity[1]) <= 0.5
        if on_ground:
            ctx.action_buffer.append(GameAction(action=ActionType.JUMP))

        rise = (self._start_y - p.pos[1]) / 16.0
        ctx.bt_trace.append(f"PillarJump(rise={rise:.1f}/{self.target_rise})")
        if rise >= self.target_rise:
            return self._finish(ctx, Status.SUCCESS)
        if self._ticks >= self.budget_ticks:
            return self._finish(ctx, Status.FAILURE)
        return Status.RUNNING

    def _finish(self, ctx: TickContext, status: Status) -> Status:
        if self._place_started:
            ctx.action_buffer.append(GameAction(action=ActionType.PLACE_STOP))
        self.reset()
        return status

    def reset(self) -> None:
        self._start_y = None
        self._ticks = 0
        self._place_started = False


class Swim(Action):
    def execute(self, ctx: TickContext) -> Status:
        direction = ctx.game_state.player.direction
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=direction))
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
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


_STUCK_VEL_THRESHOLD = 0.3
_STUCK_JUMP_LIMIT = 3


class StuckJump(Action):
    def __init__(self, name: str = "StuckJump"):
        super().__init__(name)
        self._stuck_ticks = 0
        self._jump_count = 0

    def execute(self, ctx: TickContext) -> Status:
        player = ctx.game_state.player
        on_ground = player.velocity[1] == 0.0
        moving = abs(player.velocity[0]) > _STUCK_VEL_THRESHOLD

        if moving:
            self._stuck_ticks = 0
            self._jump_count = 0
            return Status.FAILURE

        if not on_ground:
            return Status.FAILURE

        has_move = any(
            a.action == ActionType.MOVE for a in ctx.action_buffer
        )
        if not has_move:
            self._stuck_ticks = 0
            return Status.FAILURE

        self._stuck_ticks += 1
        if self._stuck_ticks < 2:
            return Status.FAILURE

        if self._jump_count >= _STUCK_JUMP_LIMIT:
            self._jump_count = 0
            self._stuck_ticks = 0
            ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
            facing = player.direction
            sign = 1.0 if facing == "right" else -1.0
            from terraria_agent.geometry import tile_offset_world, world_to_screen
            target = tile_offset_world(player, sign * 1.0, 0.0)
            screen_xy = world_to_screen(target, ctx.game_state.camera)
            ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
            ctx.bt_trace.append("StuckMine")
            return Status.SUCCESS

        self._jump_count += 1
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
        ctx.bt_trace.append(f"StuckJump({self._jump_count}/{_STUCK_JUMP_LIMIT})")
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
        target = None
        if ctx.active_goal is not None:
            tt = ctx.active_goal.target_tile
            for o in targets:
                if o.tile_pos == tt:
                    target = o
                    break
        if target is None:
            target = min(targets, key=lambda o: o.distance)
        if target.distance <= self.reach_tiles:
            return Status.SUCCESS
        player = ctx.game_state.player
        player_cx = player.pos[0] + player.width / 2.0
        direction = "right" if target.pos[0] > player_cx else "left"
        _emit_move(ctx, direction)
        return Status.RUNNING
