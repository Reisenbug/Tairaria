from __future__ import annotations

from terraria_agent.geometry import player_center_world, world_to_screen, tile_offset_world
from terraria_agent.models.actions import ActionType, GameAction
from terraria_agent.models.game_state import GameState, TerrainType
from terraria_agent.models.task_queue import TaskQueue
from terraria_agent.spinal_cord.actions.interaction import OpenChest, LootAll
from terraria_agent.spinal_cord.context import TickContext

_TILE = 16.0

_SIMPLE: dict[str, dict] = {
    "explore_right":      {"ctrl": {"right": True}, "duration": 5.0},
    "explore_left":       {"ctrl": {"left": True}, "duration": 5.0},
    "descend":            {"ctrl": {"down": True}, "duration": 1.0},
    "retreat_right":      {"ctrl": {"right": True}, "duration": 3.0},
    "retreat_left":       {"ctrl": {"left": True}, "duration": 3.0},
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
    nearest = min(state.enemies, key=lambda e: e.distance)
    p = state.player
    pcx = p.pos[0] + p.width / 2.0
    pcy = p.pos[1] + p.height / 2.0
    ncx = nearest.pos[0] + nearest.width / 2.0
    ncy = nearest.pos[1] + nearest.height / 2.0
    mx = (ncx - pcx) / _TILE
    my = (ncy - pcy) / _TILE
    ctrl: dict = {"use_item": True, "mx": mx, "my": my}
    weapon_slot = next(
        (s.slot_index for s in state.inventory_slots[:10] if s.is_weapon),
        None,
    )
    if weapon_slot is not None and weapon_slot != state.player.selected_slot:
        ctrl["selected_slot"] = weapon_slot
    return {"ctrl": ctrl, "duration": 2.0}


def _skill_fight_moving_right(state: GameState) -> dict | None:
    result = _skill_fight_nearest(state)
    if result is None:
        return None
    result["ctrl"]["right"] = True
    return result


def _skill_fight_moving_left(state: GameState) -> dict | None:
    result = _skill_fight_nearest(state)
    if result is None:
        return None
    result["ctrl"]["left"] = True
    return result


def _skill_dig_forward(state: GameState) -> dict | None:
    pickaxe = next((s for s in state.inventory_slots[:10] if s.is_pickaxe), None)
    if pickaxe is None:
        return None
    p = state.player
    sign = 1.0 if p.direction == "right" else -1.0
    target_world = tile_offset_world(p, sign * 1.5, 0.0)
    screen_xy = world_to_screen(target_world, state.camera)
    ctrl: dict = {"use_item": True, "screen_xy": screen_xy}
    if pickaxe.slot_index != p.selected_slot:
        ctrl["selected_slot"] = pickaxe.slot_index
    direction = "right" if sign > 0 else "left"
    ctrl[direction] = True
    return {"ctrl": ctrl, "duration": 2.0}


def _skill_build_bridge(state: GameState) -> dict | None:
    platform_slot = next((s for s in state.inventory_slots[:10] if s.is_platform), None)
    if platform_slot is None:
        return None
    p = state.player
    direction = p.direction
    ctrl: dict = {
        "use_item": True,
        direction: True,
        "selected_slot": platform_slot.slot_index,
    }
    return {"ctrl": ctrl, "duration": 3.0}


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


_MOD_SKILLS: set[str] = {"pillar_jump", "cave_bypass"}

_DYNAMIC: dict[str, object] = {
    "fight_nearest":       _skill_fight_nearest,
    "fight_moving_right":  _skill_fight_moving_right,
    "fight_moving_left":   _skill_fight_moving_left,
    "dig_forward":         _skill_dig_forward,
    "build_bridge":        _skill_build_bridge,
    "open_chest":          _skill_open_chest,
    "loot_chest":          _skill_loot_chest,
}

SKILL_NAMES: list[str] = list(_SIMPLE) + list(_DYNAMIC) + list(_MOD_SKILLS)


def execute(name: str, state: GameState, controller=None) -> dict | None:
    if name in _MOD_SKILLS:
        if controller is None:
            return None
        direction = state.player.direction
        rise_tiles = 1
        walk_back = 2
        if name == "pillar_jump" and state.terrain_scan is not None:
            rise_tiles = max(1, int(state.terrain_scan.depth_or_height) - 7)
        controller.fire_skill(name, direction, rise_tiles=rise_tiles, walk_back=walk_back)
        duration = rise_tiles * 0.5 + 3.0
        return {"ctrl": {direction: True}, "duration": duration}
    if name in _SIMPLE:
        return _SIMPLE[name]
    fn = _DYNAMIC.get(name)
    if fn is None:
        return None
    return fn(state)
