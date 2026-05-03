from __future__ import annotations

import time
from dataclasses import dataclass
from terraria_agent.models.game_state import GameState
from terraria_agent.cerebellum.terra_blind_client import scan_surface, _jump_peak_tiles

_EDGE_THRESHOLD = 6
_WALKABLE_RISE = 1
_JUMPABLE_RISE = 6
_FORWARD_SCAN = 20
_OPPOSITE_SCAN = 40
_TRIGGER_DIST = 8
_ARRIVE_THRESHOLD = 3
_LIVING_WOOD = {191, 192}


@dataclass
class NavAction:
    action: str
    dist: int
    delta: int


def _find_edges(surface, tw) -> set[int]:
    edges = set()
    prev_wx = None
    for rx in range(tw.width):
        wx = tw.origin[0] + rx
        sy = surface.get(wx)
        if prev_wx is not None:
            prev_sy = surface.get(prev_wx)
            if sy is not None and prev_sy is not None and abs(sy - prev_sy) > _EDGE_THRESHOLD:
                edges.add(prev_wx)
                edges.add(wx)
        prev_wx = wx
    return edges


def _next_action(state: GameState) -> NavAction | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None
    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    sign = 1 if p.direction == "right" else -1
    surface = scan_surface(tw)
    base_y = surface.get(pcx, feet_y)
    edges = _find_edges(surface, tw)
    for i in range(1, _FORWARD_SCAN + 1):
        wx = pcx + sign * i
        if wx not in edges:
            continue
        left_sy = surface.get(wx, base_y)
        opposite = None
        for j in range(1, _OPPOSITE_SCAN + 1):
            owx = wx + sign * j
            if owx not in edges:
                continue
            osy = surface.get(owx)
            if osy is not None and osy <= left_sy + 2:
                opposite = (owx, osy)
                break
        if opposite is None:
            for j in range(1, _OPPOSITE_SCAN + 1):
                owx = wx + sign * j
                if owx not in edges:
                    continue
                osy = surface.get(owx)
                if osy is not None:
                    opposite = (owx, osy)
                    break
        if opposite is None:
            return NavAction(action="bridge", dist=i, delta=0)
        owx, osy = opposite
        rise = base_y - osy
        if rise > _JUMPABLE_RISE:
            return NavAction(action="bridge", dist=owx - pcx, delta=rise)
        if rise > _WALKABLE_RISE:
            return NavAction(action="jump", dist=owx - pcx, delta=rise)
        return NavAction(action="walk", dist=owx - pcx, delta=rise)
    return NavAction(action="walk", dist=_FORWARD_SCAN, delta=0)


def _in_water(state: GameState) -> bool:
    tw = state.tile_window
    if tw is None:
        return False
    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    for dy in range(-2, 1):
        t = tw.tile_at(pcx, feet_y + dy)
        if t is not None and t.water:
            return True
    return False


def _living_tree_ahead(state: GameState, sign: int) -> bool:
    tw = state.tile_window
    if tw is None:
        return False
    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    for i in range(1, 10):
        wx = pcx + sign * i
        for dy in range(-5, 3):
            t = tw.tile_at(wx, feet_y + dy)
            if t is not None and t.type in _LIVING_WOOD:
                return True
    return False


def _overhead_blocked(state: GameState) -> bool:
    tw = state.tile_window
    if tw is None:
        return False
    p = state.player
    head_y = int(p.pos[1] / 16.0)
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    for col in (pcx, pcx + 1):
        for dy in range(1, 4):
            t = tw.tile_at(col, head_y - dy)
            if t is not None and t.solid:
                return True
    return False


class Navigator:
    def __init__(self, controller, load_skill_fn) -> None:
        self._ctrl = controller
        self._load = load_skill_fn
        self._state = "idle"
        self._target_x: int | None = None
        self._target_y: int | None = None
        self._direction = "right"

    def set_direction(self, direction: str) -> None:
        self._direction = direction

    def tick(self, state: GameState) -> dict | None:
        p = state.player
        pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
        feet_y = int((p.pos[1] + p.height) / 16.0)
        sign = 1 if self._direction == "right" else -1

        if _in_water(state):
            return {"jump": True, self._direction: True}

        if self._state == "idle":
            action = _next_action(state)
            if action and action.action != "walk" and action.dist <= _TRIGGER_DIST:
                self._target_x = pcx + sign * action.dist
                self._target_y = feet_y - action.delta
                print(f"[nav] E检测 dist={action.dist} delta={action.delta} → pillar target=({self._target_x},{self._target_y})")
                self._state = "stop"
                return {}
            if _living_tree_ahead(state, sign):
                print("[nav] 生命树，挖掘前进")
                return {"use_item": True, "sc": 1, "selected_slot": 1,
                        "mx": sign * 2, "my": 0, self._direction: True}
            return {self._direction: True}

        elif self._state == "stop":
            if abs(p.vel[0]) < 0.5:
                self._state = "pillar"
            return {}

        elif self._state == "pillar":
            if _overhead_blocked(state):
                dig = [{"use_item": True, "sc": 1, "selected_slot": 1, "mx": 0, "my": -5, "jump": True}] * 15 + \
                      [{"use_item": True, "sc": 1, "selected_slot": 1, "mx": 0, "my": -5}] * 15
                self._ctrl.replay_skill(dig)
                time.sleep(30 / 60.0)
                return None
            jump_peak = _jump_peak_tiles(state.movement)
            rise = feet_y - self._target_y
            print(f"[nav] pillar rise={rise:.1f} peak={jump_peak:.1f}")
            if rise <= jump_peak:
                print("[nav] pillar完成 → bridge")
                self._state = "bridge"
                return None
            frames = self._load("pillar_jump_2_height")
            if self._direction == "left":
                from terraria_agent.agent import _mirror_frame
                frames = [_mirror_frame(f) for f in frames]
            self._ctrl.replay_skill(frames)
            time.sleep(len(frames) / 60.0)
            return None

        elif self._state == "bridge":
            dx = (self._target_x - pcx) * sign
            print(f"[nav] bridge dx={dx}")
            if dx <= _ARRIVE_THRESHOLD:
                print("[nav] bridge完成 → jump")
                self._state = "jump"
                return None
            frames = self._load(f"bridge_{self._direction}_2")
            self._ctrl.replay_skill(frames)
            time.sleep(len(frames) / 60.0)
            return None

        elif self._state == "jump":
            print(f"[nav] jump pos=({pcx},{feet_y}) target=({self._target_x},{self._target_y})")
            jump_frames = [{"jump": True, self._direction: True}] * 15 + [{self._direction: True}] * 30
            self._ctrl.replay_skill(jump_frames)
            time.sleep(45 / 60.0)
            self._state = "idle"
            self._target_x = None
            self._target_y = None
            return None

        return None

    @property
    def active(self) -> bool:
        return self._state != "idle"
