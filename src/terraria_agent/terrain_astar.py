from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from terraria_agent.models.game_state import GameState, TileWindow, MovementInfo
from terraria_agent.cerebellum.terra_blind_client import (
    scan_skyline, scan_standable, _jump_envelope, _is_standable_at, _TILE_PX,
)

_LIVING_WOOD = {191, 192}  # Living Wood, Leaf Block
_GOAL_RANGE = 40
_WALK_COST = 1
_JUMP_COST = 1
_SKILL_COST = 3


@dataclass
class NavEdge:
    action: str
    dx: int
    dy: int
    cost: float
    reason: str = ""


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


def _jump_clear(tw: TileWindow, src_wx: int, src_wy: int, dst_wx: int,
                envelope: list[int], sign: int) -> bool:
    adx = abs(dst_wx - src_wx)
    for i in range(adx + 1):
        arc_y = src_wy + envelope[i]
        cx = src_wx + sign * i
        for col_off in range(2):
            for dy in range(1, 4):
                t = tw.tile_at(cx + col_off, arc_y - dy)
                if t is not None and t.solid and not t.platform:
                    return False
    return True


def _has_floor_gap(tw: TileWindow, cx: int, nx: int, ny: int, sign: int) -> bool:
    for x in range(cx, nx + sign, sign):
        if not _is_standable_at(tw, x, ny):
            return True
    return False


def _build_edge(tw: TileWindow, skyline: dict[int, int], movement: MovementInfo,
                src_wx: int, src_wy: int, dst_wx: int, dst_wy: int) -> Optional[NavEdge]:
    dx = dst_wx - src_wx
    dy = src_wy - dst_wy
    adx = abs(dx)
    sign = 1 if dx > 0 else -1

    in_water = _is_water(tw, src_wx, src_wy - 1)
    peak = _jump_peak(movement)
    envelope = _jump_envelope(movement, max_cols=adx + 1)

    if adx <= 1 and abs(dy) <= 1:
        return NavEdge("walk", dx, dy, _edge_cost("walk", dx, dy, in_water))

    if adx < len(envelope):
        reachable_dy = -envelope[adx]
        if 0 < dy <= reachable_dy:
            if not _jump_clear(tw, src_wx, src_wy, dst_wx, envelope, sign):
                return None
            return NavEdge("jump", dx, dy, _edge_cost("jump", dx, dy, in_water))
        if dy <= 0:
            if _has_floor_gap(tw, src_wx, dst_wx, dst_wy, sign):
                return NavEdge("bridge", dx, dy, _edge_cost("bridge", dx, dy, in_water),
                               f"floor_gap adx={adx} dy={dy}")
            return NavEdge("walk", dx, dy, _edge_cost("walk", adx, dy, in_water))

    if dy > peak:
        return NavEdge("pillar_bridge", dx, dy, _edge_cost("pillar_bridge", dx, dy, in_water),
                       f"dy={dy} > peak={peak:.1f}")

    return NavEdge("bridge", dx, dy, _edge_cost("bridge", dx, dy, in_water),
                   f"adx={adx} >= envelope={len(envelope)} dy={dy} peak={peak:.1f}")


def astar(state: GameState, sign: int) -> list[tuple[int, int, NavEdge]] | None:
    tw = state.tile_window
    if tw is None or not tw.rows:
        return None

    p = state.player
    pcx = int((p.pos[0] + p.width / 2.0) / 16.0)
    feet_y = int((p.pos[1] + p.height) / 16.0)
    movement = state.movement

    skyline = scan_skyline(tw)
    standable = scan_standable(tw)

    start_wx = pcx
    start_wy = skyline.get(pcx, feet_y)

    goal_wx = pcx + sign * _GOAL_RANGE
    goal_wy = skyline.get(goal_wx)
    if goal_wy is None:
        for r in range(_GOAL_RANGE, 0, -1):
            gw = pcx + sign * r
            if gw in skyline:
                goal_wx, goal_wy = gw, skyline[gw]
                break
    if goal_wy is None:
        return []

    if _has_living_tree(tw, skyline, start_wx, goal_wx):
        return None

    peak = _jump_peak(movement)
    max_dy = int(math.ceil(peak)) + 2

    g: dict[tuple[int, int], float] = {(start_wx, start_wy): 0.0}
    prev: dict[tuple[int, int], tuple[tuple[int, int], NavEdge] | None] = {(start_wx, start_wy): None}
    heap = [_Node(float(abs(goal_wx - start_wx) + abs(goal_wy - start_wy)), start_wx, start_wy)]
    fail_reasons: dict[str, int] = {}

    while heap:
        node = heapq.heappop(heap)
        cx, cy = node.wx, node.wy

        if cx == goal_wx and cy == goal_wy:
            path = []
            pos = (goal_wx, goal_wy)
            while prev[pos] is not None:
                ppos, edge = prev[pos]
                path.append((pos[0], pos[1], edge))
                pos = ppos
            path.reverse()
            return path

        cur_g = g.get((cx, cy), math.inf)
        for (nx, ny) in standable:
            if sign * (nx - cx) <= 0 or abs(nx - cx) > 40:
                continue
            if abs(ny - cy) > max_dy + 10:
                continue
            adx = abs(nx - cx)
            edge = _build_edge(tw, skyline, movement, cx, cy, nx, ny)
            if edge is None:
                dy = cy - ny
                envelope = _jump_envelope(movement, max_cols=adx + 1)
                if adx <= 1 and abs(dy) <= 1:
                    reason = f"walk_blocked adx={adx} dy={dy}"
                elif adx < len(envelope):
                    reachable_dy = -envelope[adx]
                    if 0 < dy <= reachable_dy:
                        reason = f"jump_overhead_blocked adx={adx} dy={dy}"
                    elif dy <= 0:
                        reason = f"walk_blocked adx={adx} dy={dy}"
                    else:
                        reason = f"dy_out_of_range adx={adx} dy={dy} reachable={reachable_dy:.1f}"
                elif dy <= 0:
                    reason = f"downslope_too_far adx={adx} dy={dy}"
                else:
                    reason = f"unknown adx={adx} dy={dy}"
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
                continue
            ng = cur_g + edge.cost
            npos = (nx, ny)
            if ng < g.get(npos, math.inf):
                g[npos] = ng
                prev[npos] = ((cx, cy), edge)
                h = abs(goal_wx - nx) + abs(goal_wy - ny)
                heapq.heappush(heap, _Node(ng + h, nx, ny))

    reached = [(wx, wy) for (wx, wy) in g if wx != start_wx]
    furthest = max(reached, key=lambda pos: sign * pos[0], default=(start_wx, start_wy))
    print(f"[astar] no path ({start_wx},{start_wy})→({goal_wx},{goal_wy}) furthest={furthest} fail_reasons={fail_reasons}")
    return []
