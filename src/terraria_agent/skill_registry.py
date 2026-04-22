from __future__ import annotations

from terraria_agent.geometry import player_center_world
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.models.game_state import GameState
from terraria_agent.models.task_queue import TaskQueue
from terraria_agent.spinal_cord.actions.combat import AttackNearest, EnsureWeaponSlot
from terraria_agent.spinal_cord.actions.interaction import OpenChest, LootAll
from terraria_agent.spinal_cord.context import TickContext

_TILE = 16.0

_SIMPLE: dict[str, dict] = {
    "explore_right":      {"ctrl": {"right": True}, "duration": 5.0},
    "explore_left":       {"ctrl": {"left": True}, "duration": 5.0},
    "jump_right":         {"ctrl": {"right": True, "jump": True}, "duration": 0.5},
    "jump_left":          {"ctrl": {"left": True, "jump": True}, "duration": 0.5},
    "descend":            {"ctrl": {"down": True}, "duration": 1.0},
    "retreat_right":      {"ctrl": {"right": True, "jump": True}, "duration": 3.0},
    "retreat_left":       {"ctrl": {"left": True, "jump": True}, "duration": 3.0},
    "loot":               {"ctrl": {"loot_all": True}, "duration": 0.1},
    "heal":               {"ctrl": {"quick_heal": True}, "duration": 0.1},
}


def _make_ctx(state: GameState) -> TickContext:
    tq = TaskQueue(goal="", task_queue=[])
    return TickContext(game_state=state, task_queue=tq)


def _actions_to_ctrl(actions: list[GameAction], state: GameState) -> dict:
    ctrl: dict = {}
    for a in actions:
        if a.action == ActionType.MOVE:
            ctrl[a.direction] = True
        elif a.action == ActionType.JUMP:
            ctrl["jump"] = True
        elif a.action == ActionType.ATTACK:
            ctrl["use_item"] = True
            if a.target:
                pcx, pcy = player_center_world(state.player)
                ctrl["mouse_x"] = round((a.target[0] - pcx) / _TILE)
                ctrl["mouse_y"] = round((a.target[1] - pcy) / _TILE)
        elif a.action == ActionType.SWITCH_SLOT:
            ctrl["selected_slot"] = a.slot
        elif a.action == ActionType.INTERACT:
            ctrl["interact"] = True
            if a.tile:
                ctrl["tile_x"], ctrl["tile_y"] = a.tile
        elif a.action == ActionType.LOOT_ALL:
            ctrl["loot_all"] = True
        elif a.action == ActionType.QUICK_HEAL:
            ctrl["quick_heal"] = True
    return ctrl


def _skill_fight_nearest(state: GameState) -> dict | None:
    if not state.enemies:
        return None
    ctx = _make_ctx(state)
    EnsureWeaponSlot().execute(ctx)
    AttackNearest().execute(ctx)
    ctrl = _actions_to_ctrl(ctx.action_buffer, state)
    if not ctrl:
        return None
    return {"ctrl": ctrl, "duration": 2.0}


def _skill_fight_moving_right(state: GameState) -> dict | None:
    result = _skill_fight_nearest(state)
    if result is None:
        return None
    result["ctrl"]["right"] = True
    result["ctrl"]["jump"] = True
    return result


def _skill_fight_moving_left(state: GameState) -> dict | None:
    result = _skill_fight_nearest(state)
    if result is None:
        return None
    result["ctrl"]["left"] = True
    result["ctrl"]["jump"] = True
    return result


def _skill_open_chest(state: GameState) -> dict | None:
    chests = [o for o in state.objects if o.type == "chest"]
    if not chests:
        return None
    ctx = _make_ctx(state)
    OpenChest().execute(ctx)
    ctrl = _actions_to_ctrl(ctx.action_buffer, state)
    if not ctrl:
        return None
    return {"ctrl": ctrl, "duration": 0.1}


def _skill_loot_chest(state: GameState) -> dict | None:
    ctx = _make_ctx(state)
    LootAll().execute(ctx)
    ctrl = _actions_to_ctrl(ctx.action_buffer, state)
    if not ctrl:
        return None
    return {"ctrl": ctrl, "duration": 0.1}


_DYNAMIC: dict[str, object] = {
    "fight_nearest":       _skill_fight_nearest,
    "fight_moving_right":  _skill_fight_moving_right,
    "fight_moving_left":   _skill_fight_moving_left,
    "open_chest":          _skill_open_chest,
    "loot_chest":          _skill_loot_chest,
}

SKILL_NAMES: list[str] = list(_SIMPLE) + list(_DYNAMIC)


def execute(name: str, state: GameState) -> dict | None:
    if name in _SIMPLE:
        return _SIMPLE[name]
    fn = _DYNAMIC.get(name)
    if fn is None:
        return None
    return fn(state)
