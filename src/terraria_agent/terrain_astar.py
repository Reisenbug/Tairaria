from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from terraria_agent.models.game_state import GameState, TileWindow, MovementInfo
from terraria_agent.cerebellum.terra_blind_client import (
    scan_skyline, _jump_envelope, _TILE_PX,
)

_LIVING_WOOD = {191, 192}  # Living Wood, Leaf Block
_GOAL_RANGE = 60
_WALK_COST = 1
_JUMP_COST = 1
_SKILL_COST = 3


@dataclass
class NavEdge:
    action: str
    dx: int
    dy: int
    cost: float


@dataclass(order=True)
class _Node:
    f: float
    wx: int = field(compare=False)
    wy: int = field(compare=False)


def _is_water(tw: TileWindow, wx: int, wy: int) -> bool:
    t = tw.tile_at(wx, wy)
    return t is not None and t.water


def _has_living_tree(tw: TileWindow, skyline: dict[int, int], wx1: int, wx2: int) -> bool:
    for wx in range(min(wx1, wx2), max(wx1, wx2) + 1):
        wy = skyline.get(wx)
        if wy is None:
            continue
        for dy in range(-5, 3):
            t = tw.tile_at(wx, wy + dy)
            if t is not None and t.type in _LIVING_WOOD:
                return True
    return False


def _jump_peak(movement: MovementInfo) -> float:
    js = movement.jump_speed
    grav = max(movement.gravity, 0.01)
    hold_speed = js - grav
    phase1 = hold_speed * (movement.jump_height + 1)
    phase2 = hold_speed * hold_speed / (2.0 * grav)
    return (phase1 + phase2) / _TILE_PX


def _edge_cost(action: str, dx: int, dy: int, in_water: bool) -> float:
    if action == "walk":
        c = _WALK_COST * abs(dx)
    elif action == "jump":
        c = _JUMP_COST
    elif action == "pillar":
        c = math.ceil(dy / 2) * _SKILL_COST
    elif action == "bridge":
        c = math.ceil(abs(dx) / 2.5) * _SKILL_COST
    else:
        c = (math.ceil(dy / 2) + math.ceil(abs(dx) / 2.5)) * _SKILL_COST
    return c * (2 if in_water else 1)


def _build_edge(tw: TileWindow, skyline: dict[int, int], movement: MovementInfo,
                src_wx: int, src_wy: int, dst_wx: int, dst_wy: int) -> Optional[NavEdge]:
    dx = dst_wx - src_wx
    dy = src_wy - dst_wy
    adx = abs(dx)
    sign = 1 if dx > 0 else -1

    has_gap = any(skyline.get(src_wx + sign * i) is None for i in range(1, adx))
    in_water = _is_water(tw, src_wx, src_wy - 1)
    peak = _jump_peak(movement)
    envelope = _jump_envelope(movement, max_cols=adx + 1)

    if adx <= 1 and abs(dy) <= 1 and not has_gap:
        return NavEdge("walk", dx, dy, _edge_cost("walk", dx, dy, in_water))

    if adx < len(envelope):
        reachable_dy = -envelope[adx]
        if not has_gap and 0 < dy <= reachable_dy:
            return NavEdge("jump", dx, dy, _edge_cost("jump", dx, dy, in_water))
        if not has_gap and dy <= 0:
            return NavEdge("walk", dx, dy, _edge_cost("walk", adx, dy, in_water))

    if not has_gap and dy > peak:
        return NavEdge("pillar", dx, dy, _edge_cost("pillar", dx, dy, in_water))

    if has_gap and 0 < dy <= peak:
        return NavEdge("bridge", dx, dy, _edge_cost("bridge", dx, dy, in_water))

    if has_gap and dy > peak:
        return NavEdge("pillar_bridge", dx, dy, _edge_cost("pillar_bridge", dx, dy, in_water))

    return None


def astar(state: GameState, sign: int) -> list[tuple[int, int, NavEdge]] | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    movement = state.movement

    skyline = scan_skyline(tw)
    start_wx = pcx
    start_wy = skyline.get(pcx, feet_y)

    goal_wx = pcx + sign * _GOAL_RANGE
    goal_wy = skyline.get(goal_wx)
    if goal_wy is None:
        for offset in range(1, 10):
            for d in (offset, -offset):
                gw = goal_wx + d
                if gw in skyline:
                    goal_wx, goal_wy = gw, skyline[gw]
                    break
            if goal_wy is not None:
                break
    if goal_wy is None:
        return []

    if _has_living_tree(tw, skyline, start_wx, goal_wx):
        return None

    col_set = set(skyline.keys())
    g: dict[int, float] = {start_wx: 0.0}
    prev: dict[int, tuple[int, NavEdge] | None] = {start_wx: None}
    heap = [_Node(float(abs(goal_wx - start_wx)), start_wx, start_wy)]

    while heap:
        node = heapq.heappop(heap)
        cx, cy = node.wx, node.wy

        if cx == goal_wx:
            path = []
            wx = goal_wx
            while prev[wx] is not None:
                pwx, edge = prev[wx]
                path.append((wx, skyline[wx], edge))
                wx = pwx
            path.reverse()
            return path

        cur_g = g.get(cx, math.inf)
        for nx in col_set:
            if sign * (nx - cx) <= 0 or abs(nx - cx) > 20:
                continue
            ny = skyline[nx]
            edge = _build_edge(tw, skyline, movement, cx, cy, nx, ny)
            if edge is None:
                continue
            ng = cur_g + edge.cost
            if ng < g.get(nx, math.inf):
                g[nx] = ng
                prev[nx] = (cx, edge)
                heapq.heappush(heap, _Node(ng + abs(goal_wx - nx), nx, ny))

    return []
