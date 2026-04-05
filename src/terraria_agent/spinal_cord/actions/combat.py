from __future__ import annotations

from typing import TYPE_CHECKING

from terraria_agent.models.actions import GameAction, ActionType
from terraria_agent.spinal_cord.bt.core import Status
from terraria_agent.spinal_cord.bt.leaves import Action

if TYPE_CHECKING:
    from terraria_agent.spinal_cord.context import TickContext


class AttackNearest(Action):
    def execute(self, ctx: TickContext) -> Status:
        if not ctx.game_state.enemies:
            return Status.FAILURE
        nearest = min(ctx.game_state.enemies, key=lambda e: e.distance)
        ctx.action_buffer.append(GameAction(action=ActionType.ATTACK, target=nearest.pos))
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
