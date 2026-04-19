from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.geometry import world_to_screen
from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class AttackNearest(Action):
    def execute(self, ctx: TickContext) -> Status:
        if not ctx.game_state.enemies:
            return Status.FAILURE
        cur_slot = ctx.game_state.player.selected_slot
        held = next((s for s in ctx.game_state.inventory_slots[:10] if s.slot_index == cur_slot), None)
        if held is None or not held.is_weapon:
            return Status.FAILURE
        nearest = min(ctx.game_state.enemies, key=lambda e: e.distance)
        screen_xy = world_to_screen(nearest.pos, ctx.game_state.camera)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=screen_xy))
        return Status.SUCCESS


class SwitchToSword(Action):
    def execute(self, ctx: TickContext) -> Status:
        for i, item in enumerate(ctx.game_state.hotbar):
            if item and "sword" in item:
                ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=i))
                return Status.SUCCESS
        return Status.FAILURE


class SwitchToBestWeapon(Action):
    def execute(self, ctx: TickContext) -> Status:
        weapon_priority = ["sword", "bow", "gun", "yoyo", "spear"]
        for weapon in weapon_priority:
            for i, item in enumerate(ctx.game_state.hotbar):
                if item and weapon in item:
                    ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=i))
                    return Status.SUCCESS
        return Status.FAILURE


class Dodge(Action):
    def execute(self, ctx: TickContext) -> Status:
        if not ctx.game_state.threats:
            return Status.FAILURE
        threat = next((t for t in ctx.game_state.threats if t.urgent), ctx.game_state.threats[0])
        dodge_dir = "right" if threat.direction == "left" else "left"
        ctx.action_buffer.append(GameAction(action=ActionType.MOVE, direction=dodge_dir))
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
        return Status.SUCCESS


class JumpOverEnemy(Action):
    def execute(self, ctx: TickContext) -> Status:
        ctx.action_buffer.append(GameAction(action=ActionType.JUMP))
        return Status.SUCCESS


class EnsureWeaponSlot(Action):
    def execute(self, ctx: TickContext) -> Status:
        cur = ctx.game_state.player.selected_slot
        held = next((s for s in ctx.game_state.inventory_slots[:10] if s.slot_index == cur), None)
        if held is not None and held.is_weapon:
            return Status.SUCCESS
        weapon = next((s for s in ctx.game_state.inventory_slots[:10] if s.is_weapon), None)
        if weapon is None:
            return Status.FAILURE
        ctx.action_buffer.append(GameAction(action=ActionType.SWITCH_SLOT, slot=weapon.slot_index))
        return Status.RUNNING
